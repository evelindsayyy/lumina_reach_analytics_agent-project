# -*- coding: utf-8 -*-

"""
The agent runtime's HTTP contract, through the real ``BedrockAgentCoreApp``
(Starlette's test client, so no port), with the agent factory stubbed.
"""

import json

import pytest
from starlette.testclient import TestClient

from agent_app.ai_sdk_adapter import SSE_HEADERS
from agent_app.paths import path_enum
from agent_app.runtimes import analytics_agent
from agent_app.runtimes.analytics_agent import make_agent
from agent_app.runtimes.analytics_agent import new_mcp_client


class StubAgent:
    def __init__(self, history):
        self.messages = list(history)

    def __call__(self, question):
        self.messages.append({"role": "assistant", "content": [{"text": f"You asked: {question}"}]})

        class Result:
            class metrics:
                accumulated_usage = {"inputTokens": 1, "outputTokens": 1}

        return Result()

    def cleanup(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(analytics_agent, "build_agent", StubAgent)
    return TestClient(analytics_agent.app)


def events(response) -> list:
    """The SSE events of a response body, ``[DONE]`` included as a string."""
    out = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            data = line[len("data: "):]
            out.append(data if data == "[DONE]" else json.loads(data))
    return out


CHAT = {
    "id": "chat-1",
    "trigger": "submit-message",
    "messages": [
        {"id": "m1", "role": "user", "parts": [{"type": "text", "text": "Which engine is cheaper?"}]}
    ],
}


def test_ping_is_healthy(client):
    response = client.get("/ping")
    assert response.status_code == 200


def test_invocations_answer_in_the_ai_sdk_stream_format(client):
    response = client.post("/invocations", json=CHAT)
    assert response.status_code == 200
    for key, value in SSE_HEADERS.items():
        assert response.headers[key] == value

    stream = events(response)
    assert [e["type"] for e in stream[:-1]] == [
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert stream[1]["delta"] == "You asked: Which engine is cheaper?"
    assert stream[-1] == "[DONE]"


def test_a_malformed_body_is_a_400_before_any_agent(client, monkeypatch):
    def factory(history):
        raise AssertionError("must not be built")

    monkeypatch.setattr(analytics_agent, "build_agent", factory)
    response = client.post("/invocations", json={"messages": "not a list"})
    assert response.status_code == 400


def test_make_agent_carries_the_history_and_prints_nothing():
    from strands.handlers.callback_handler import null_callback_handler
    from strands.models import BedrockModel

    history = [{"role": "user", "content": [{"text": "earlier question"}]}]
    agent = make_agent(model=BedrockModel(model_id="test"), history=history, tools=[])
    assert agent.messages == history
    assert agent.system_prompt == path_enum.path_bi_agent_system_prompt_content
    assert agent.callback_handler is null_callback_handler


def test_new_mcp_client_does_not_connect_until_used():
    """Building the client is free: the agent opens it, cleanup closes it."""
    mcp_client = new_mcp_client("http://127.0.0.1:1/mcp")
    assert mcp_client is not None


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.runtimes.analytics_agent",
        preview=False,
    )
