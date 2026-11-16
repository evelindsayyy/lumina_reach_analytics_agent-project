# -*- coding: utf-8 -*-

"""
The ``AnalyticsAgent`` runtime: the analytics agent, served by
:class:`BedrockAgentCoreApp` (``POST /invocations`` and ``GET /ping`` on port
8080; the same server runs locally).

The request body is the one the chat UI posts (the AI SDK request, with the
whole conversation), and the response is the AI SDK v5 UI message stream the UI
parses, so the web tier forwards both untouched.

The agent's data tools come from the ``AnalyticsMcp`` runtime over MCP. This
process never opens a warehouse connection, so its execution role needs no
warehouse credentials.

Run it with ``python -m agent_app.runtimes.analytics_agent``.
"""

import httpx
import pydantic
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext
from mcp.client.streamable_http import streamablehttp_client
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse
from strands import Agent
from strands.agent import ModelRetryStrategy
from strands.tools.mcp import MCPClient

from ..one.api import one
from ..paths import path_enum
from ..ai_sdk_adapter import ai_sdk_streaming_response
from ..vendor.vercel_ai_sdk import RequestBody
from .common import AGENT_PORT
from .common import AGENT_RUNTIME_NAME
from .common import MCP_RUNTIME_NAME
from .chat_turn import run_chat_turn
from .mcp_connection import get_mcp_connection
from .jwt_claims import user_id_from_headers


#: How hard to retry a throttled model call: three attempts, about six seconds
#: of waiting in all. The strands default (six attempts, up to four minutes) is
#: right for a batch job and wrong for a chat turn: a daily token cap does not
#: clear in minutes, and the reader would watch a spinner for two of them
#: before learning that. The web tier's request timeout is in the same range.
MODEL_RETRY_STRATEGY = ModelRetryStrategy(max_attempts=3, initial_delay=2, max_delay=10)


def new_mcp_client(url: str, auth: httpx.Auth | None = None) -> MCPClient:
    """
    An MCP client of the server at ``url``. The agent opens it when it is built
    and ``agent.cleanup()`` closes it.
    """
    return MCPClient(lambda: streamablehttp_client(url, auth=auth))


def make_agent(model, history: list[dict], tools: list) -> Agent:
    """
    The analytics agent on ``model``, continuing ``history``, with ``tools``.
    Prints nothing (``callback_handler=None``): the reply goes back as one
    stream, not to stdout.
    """
    return Agent(
        model=model,
        system_prompt=path_enum.path_bi_agent_system_prompt_content,
        messages=history,
        tools=tools,
        callback_handler=None,
        retry_strategy=MODEL_RETRY_STRATEGY,
    )


def build_agent(history: list[dict]) -> Agent:  # pragma: no cover - opens MCP
    """
    :func:`make_agent` with the dependencies of this process: the model of
    ``LLM_PROVIDER``, the ``AnalyticsMcp`` tools (a local URL, or the deployed
    runtime signed with SigV4), and the agent's own debug report tool.
    """
    url, auth = get_mcp_connection(MCP_RUNTIME_NAME, one.boto_ses)
    return make_agent(
        model=one.model,
        history=history,
        tools=[new_mcp_client(url, auth), one.tool_write_debug_report],
    )


app = BedrockAgentCoreApp()


def parse_request_body(payload: dict) -> RequestBody:
    """
    The AI SDK request in ``payload``. One that does not validate is a 400 with
    pydantic's errors, before any model or MCP call.
    """
    try:
        return RequestBody.model_validate(payload)
    except pydantic.ValidationError as e:
        errors = e.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=400, detail=str(errors))


@app.entrypoint
def invoke(payload: dict, context: RequestContext | None = None) -> StreamingResponse:
    """
    Answer the newest message of the conversation in ``payload``, as an AI SDK
    v5 UI message stream. A sync entrypoint, so the app runs it on a worker
    thread and concurrent requests do not block each other.

    ``context`` carries the request headers. Deployed, its ``Authorization``
    holds the caller's JWT, already verified by AgentCore; its ``sub`` is the
    user the per-user cap counts.
    """
    request_body = parse_request_body(payload)
    user_id = user_id_from_headers(context.request_headers if context else None)
    # No client while the cap is off: building one parses the DynamoDB service
    # model, on every request, for calls that return before using it.
    dynamodb_client = one.dynamodb_client() if one.config.quota_enabled else None
    reply = run_chat_turn(
        request_body,
        new_agent=build_agent,
        dynamodb_client=dynamodb_client,
        config=one.config,
        user_id=user_id,
    )
    return ai_sdk_streaming_response(reply.answer, reasoning_text=reply.reasoning)


def main():  # pragma: no cover - blocks until stopped
    """
    Check the model's credentials, then serve on port 8080, blocking until
    stopped. A missing API key fails here, at startup, with the variable named.
    """
    one.config.validate()
    print(
        f"{AGENT_RUNTIME_NAME}: LLM_PROVIDER={one.config.llm_provider!r}, "
        f"model {one.config.model_id!r}, serving on port {AGENT_PORT}",
        flush=True,
    )
    app.run(port=AGENT_PORT)


if __name__ == "__main__":  # pragma: no cover
    main()
