# -*- coding: utf-8 -*-

"""
One chat turn end to end, with a stub agent: no model, no MCP server, no AWS.
"""

import types

import pytest
from strands.types.exceptions import MCPClientInitializationError
from strands.types.exceptions import ModelThrottledException

from agent_app.agent_response import MODEL_FAILED_MESSAGE
from agent_app.agent_response import MODEL_THROTTLED_MESSAGE
from agent_app.agent_response import TOOLS_UNREACHABLE_MESSAGE
from agent_app.one.api import one
from agent_app.quota import QuotaExceededError
from agent_app.runtimes import chat_turn
from agent_app.runtimes.chat_turn import EMPTY_ANSWER_MESSAGE
from agent_app.runtimes.chat_turn import NO_MESSAGE_MESSAGE
from agent_app.runtimes.chat_turn import QUOTA_EXCEEDED_MESSAGE
from agent_app.runtimes.chat_turn import run_chat_turn
from agent_app.vendor.vercel_ai_sdk import RequestBody


def text_message(role: str, text: str) -> dict:
    return {"id": f"{role}-{len(text)}", "role": role, "parts": [{"type": "text", "text": text}]}


def conversation(*texts: str) -> RequestBody:
    """Alternating user / assistant messages, ending with the user's question."""
    roles = ["user", "assistant"]
    messages = [text_message(roles[i % 2], t) for i, t in enumerate(texts)]
    return RequestBody(id="chat-1", messages=messages)


class StubAgent:
    """Enough of a strands Agent for a turn: messages, a call, a cleanup."""

    def __init__(self, history, replies=(), error=None, usage=None):
        self.messages = list(history)
        self.replies = list(replies)
        self.error = error
        self.usage = usage or {"inputTokens": 120, "outputTokens": 30}
        self.asked = None
        self.closed = False

    def __call__(self, question):
        if self.error:
            raise self.error
        self.asked = question
        self.messages.append({"role": "user", "content": [{"text": question}]})
        for text in self.replies:
            self.messages.append({"role": "assistant", "content": [{"text": text}]})
        return types.SimpleNamespace(
            metrics=types.SimpleNamespace(accumulated_usage=self.usage)
        )

    def cleanup(self):
        self.closed = True


@pytest.fixture
def metered(monkeypatch):
    """Record what the turn reports to the spend counter."""
    calls = []
    monkeypatch.setattr(
        chat_turn,
        "increment_usage",
        lambda client, config, input_tokens, output_tokens: calls.append(
            (input_tokens, output_tokens)
        ),
    )
    return calls


def turn(request_body, factory):
    return run_chat_turn(request_body, new_agent=factory, dynamodb_client=None, config=one.config)


class TestAnswers:
    def test_the_question_and_the_history_reach_a_new_agent(self, metered):
        built = []

        def factory(history):
            built.append(StubAgent(history, replies=["There are 1,024 campaigns."]))
            return built[-1]

        reply = turn(conversation("Hi", "Hello! Ask me anything.", "How many campaigns?"), factory)

        agent = built[0]
        assert agent.asked == "How many campaigns?"
        assert [m["role"] for m in agent.messages[:2]] == ["user", "assistant"]
        assert reply.answer == "There are 1,024 campaigns."
        assert reply.reasoning == ""

    def test_thinking_is_split_from_the_answer(self, metered):
        factory = lambda h: StubAgent(h, replies=["<thinking>count rows</thinking>1,024"])
        reply = turn(conversation("How many campaigns?"), factory)
        assert reply == chat_turn.TurnReply(answer="1,024", reasoning="count rows")

    def test_the_turn_is_metered_and_the_agent_closed(self, metered):
        built = []

        def factory(history):
            built.append(StubAgent(history, replies=["ok"], usage={"inputTokens": 7, "outputTokens": 3}))
            return built[-1]

        turn(conversation("Q"), factory)
        assert metered == [(7, 3)]
        assert built[0].closed

    def test_an_empty_answer_says_so(self, metered):
        reply = turn(conversation("Q"), lambda h: StubAgent(h, replies=["<thinking>hm</thinking>"]))
        assert reply.answer == EMPTY_ANSWER_MESSAGE
        assert reply.reasoning == "hm"


class TestRefusalsAndFailures:
    def test_no_question_builds_no_agent(self):
        def factory(history):
            raise AssertionError("must not be built")

        assert turn(RequestBody(messages=[]), factory).answer == NO_MESSAGE_MESSAGE

    def test_a_spent_quota_builds_no_agent(self, monkeypatch):
        def refuse(client, config):
            raise QuotaExceededError("over")

        def factory(history):
            raise AssertionError("must not be built")

        monkeypatch.setattr(chat_turn, "check_quota", refuse)
        assert turn(conversation("Q"), factory).answer == QUOTA_EXCEEDED_MESSAGE

    @pytest.mark.parametrize(
        "error, message",
        [
            (ModelThrottledException("Too many tokens per day"), MODEL_THROTTLED_MESSAGE),
            (RuntimeError("boom"), MODEL_FAILED_MESSAGE),
        ],
    )
    def test_a_failed_model_call_is_a_sentence_and_still_closes(self, error, message, metered):
        built = []

        def factory(history):
            built.append(StubAgent(history, error=error))
            return built[-1]

        assert turn(conversation("Q"), factory).answer == message
        assert built[0].closed
        assert metered == []

    def test_an_unreachable_mcp_server_is_named(self):
        def factory(history):
            raise MCPClientInitializationError("connection refused")

        assert turn(conversation("Q"), factory).answer == TOOLS_UNREACHABLE_MESSAGE


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.runtimes.chat_turn",
        preview=False,
    )


class TestPerUserQuota:
    def test_a_user_over_their_cap_is_refused_before_any_agent(self, monkeypatch):
        from agent_app.runtimes.chat_turn import USER_QUOTA_EXCEEDED_MESSAGE

        def over(client, config, user_id):
            raise QuotaExceededError("per-user")

        monkeypatch.setattr(chat_turn, "check_user_quota", over)

        def factory(history):  # pragma: no cover - the point is that it is not reached
            raise AssertionError("must not be built")

        reply = run_chat_turn(
            conversation("How many campaigns?"), new_agent=factory, dynamodb_client=None, config=one.config, user_id="u-1"
        )
        assert reply.answer == USER_QUOTA_EXCEEDED_MESSAGE

    def test_a_signed_in_turn_counts_for_the_deployment_and_the_user(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            chat_turn,
            "increment_usage",
            lambda client, config, input_tokens, output_tokens, app_id=None: calls.append(app_id),
        )
        run_chat_turn(
            conversation("How many campaigns?"),
            new_agent=lambda history: StubAgent(history, replies=["Twelve."]),
            dynamodb_client=None,
            config=one.config,
            user_id="u-1",
        )
        assert calls[0] is None  # the deployment-wide row
        assert calls[1].endswith(":user:u-1:" + calls[1].rsplit(":", 1)[1])

    def test_an_anonymous_turn_counts_once(self, metered):
        run_chat_turn(
            conversation("How many campaigns?"),
            new_agent=lambda history: StubAgent(history, replies=["Twelve."]),
            dynamodb_client=None,
            config=one.config,
        )
        assert len(metered) == 1
