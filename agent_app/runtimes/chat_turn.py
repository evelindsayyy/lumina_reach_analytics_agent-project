# -*- coding: utf-8 -*-

"""
One chat turn, from the AI SDK request to the reply the UI streams.

Every dependency is a parameter (the agent factory, the DynamoDB client, the
config), so a test drives a whole turn with stubs: no model, no MCP server, no
AWS. :mod:`.analytics_agent` passes the real ones.

**A new agent per turn.** The conversation so far arrives with every request
(the UI resends it) and becomes the new agent's history, so no turn can see
another user's messages. The in-process app shared one cached agent and cleared
its history at the start of each request, which two concurrent chats could
interleave.
"""

import typing as T
import logging
import contextlib
import dataclasses

from ..utils import debug
from ..quota import check_quota
from ..quota import check_user_quota
from ..quota import get_user_app_id
from ..quota import increment_usage
from ..quota import QuotaExceededError
from ..agent_response import agent_error_message
from ..agent_response import parse_agent_response
from ..ai_sdk_adapter import get_last_user_message_text
from ..ai_sdk_adapter import request_body_to_agent_history

if T.TYPE_CHECKING:  # pragma: no cover
    from strands import Agent

    from ..config import Config
    from ..vendor.vercel_ai_sdk import RequestBody

logger = logging.getLogger(__name__)

#: Builds the agent for one turn from the conversation so far.
AgentFactory = T.Callable[[list[dict]], "Agent"]

NO_MESSAGE_MESSAGE = "Error: No message content found in request."

#: Shown when the monthly cap is reached. A constant, not a model call: the
#: whole point is that this path spends nothing.
QUOTA_EXCEEDED_MESSAGE = (
    "This demo runs on a monthly token budget, and it has been used up for this "
    "billing cycle. The chat will start working again when the budget resets at "
    "the beginning of next month. Thanks for trying it out."
)

#: Shown when one signed-in user has used their own share of the month.
USER_QUOTA_EXCEEDED_MESSAGE = (
    "You have used this month's questions for your account. Each account gets "
    "a fixed number per month so that everyone trying the demo gets a turn; "
    "yours reset at the beginning of next month."
)

#: An empty answer would stream an empty text block: a reasoning block with
#: nothing under it, which reads as a hang. A visible non-answer is debuggable.
EMPTY_ANSWER_MESSAGE = (
    "I worked through this but did not produce a final message. "
    "The reasoning above has what I found. Ask me to restate it."
)


@dataclasses.dataclass(frozen=True)
class TurnReply:
    """What the UI shows for one turn: the answer, and the reasoning above it."""

    answer: str
    reasoning: str = ""


def _usage_of(agent_result) -> tuple[int, int]:
    """
    The (input, output) tokens of one turn. The agent is new for the turn, so
    its accumulated usage is exactly this turn's.
    """
    usage = getattr(agent_result.metrics, "accumulated_usage", None) or {}
    return (
        int(usage.get("inputTokens", 0) or 0),
        int(usage.get("outputTokens", 0) or 0),
    )


def _close(agent) -> None:
    """Close the agent's MCP connection. A failing close must not fail the turn."""
    with contextlib.suppress(Exception):
        agent.cleanup()


def run_chat_turn(
    request_body: "RequestBody",
    new_agent: AgentFactory,
    dynamodb_client,
    config: "Config",
    user_id: str | None = None,
) -> TurnReply:
    """
    Answer the newest user message of ``request_body``.

    Never raises: a refusal, a missing message, an unreachable MCP server and a
    failed model call all come back as a :class:`TurnReply` the reader can
    understand, with the details in the log.

    Args:
        request_body: the AI SDK request, the whole conversation so far.
        new_agent: builds the agent for this turn from the history.
        dynamodb_client: for the monthly spend cap (off unless configured).
        config: the app config.
        user_id: who is asking (the JWT ``sub``), for the per-user cap. None
            locally, where nobody signs in and only the deployment-wide caps apply.
    """
    question = get_last_user_message_text(request_body)
    if not question:
        return TurnReply(NO_MESSAGE_MESSAGE)

    # Refuse before spending. A no-op when the cap is off, and it swallows its
    # own infrastructure faults, so only an actual refusal reaches the except.
    try:
        check_quota(dynamodb_client, config)
    except QuotaExceededError as e:
        debug(f"[Quota] blocked: {e}")
        return TurnReply(QUOTA_EXCEEDED_MESSAGE)
    try:
        check_user_quota(dynamodb_client, config, user_id)
    except QuotaExceededError as e:
        debug(f"[Quota] user blocked: {e}")
        return TurnReply(USER_QUOTA_EXCEEDED_MESSAGE)

    history = request_body_to_agent_history(request_body)
    debug(f"[Agent] {len(history)} history messages")

    agent = None
    try:
        # Building the agent opens the MCP connection, so it can fail too.
        agent = new_agent(history)
        start_index = len(agent.messages)
        agent_result = agent(question)
    except Exception as e:
        logger.exception("[Agent] turn failed")
        return TurnReply(agent_error_message(e))
    finally:
        if agent is not None:
            _close(agent)

    input_tokens, output_tokens = _usage_of(agent_result)
    increment_usage(
        dynamodb_client,
        config,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    if user_id:
        increment_usage(
            dynamodb_client,
            config,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            app_id=get_user_app_id(config, user_id),
        )

    thinking, answer = parse_agent_response(agent.messages, start_index)
    debug(f"[Agent] thinking {len(thinking)} chars, answer {len(answer)} chars")
    return TurnReply(answer or EMPTY_ANSWER_MESSAGE, thinking)
