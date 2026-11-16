# -*- coding: utf-8 -*-

"""
Record the deployed agent's answers to the example questions, for the web app
to replay (``data/demo-answers.json``).

Why: the live demo runs on a small monthly budget, shared by every visitor.
Once it is spent, a newcomer would see nothing work. The example questions on
the chat's start screen therefore replay answers recorded from the deployed
agent, which cost nothing and are always there; typed questions stay live.

Each question is asked the way the web app asks it: as the test user of
:mod:`.deployed_check`, with a Cognito access token, over AgentCore's HTTPS
endpoint. The test user's own monthly allowance is reset before each question
(its row in the quota table), so recording all of them fits in one run; the
deployment-wide counters still count every token, so the recording is paid
from the same budget it reports.

Run it as ``mise run ac-record-demos`` (= ``agent-app record-demos``) after a
deploy, and commit the file. A refusal or a failed turn stops the run and
writes nothing.
"""

import dataclasses
import datetime
import json
import time
import tomllib

import boto3

from ..agent_response import MODEL_FAILED_MESSAGE
from ..agent_response import MODEL_THROTTLED_MESSAGE
from ..agent_response import TOOLS_UNREACHABLE_MESSAGE
from ..paths import path_enum
from ..runtimes.chat_turn import EMPTY_ANSWER_MESSAGE
from ..runtimes.chat_turn import NO_MESSAGE_MESSAGE
from ..runtimes.chat_turn import QUOTA_EXCEEDED_MESSAGE
from ..runtimes.chat_turn import USER_QUOTA_EXCEEDED_MESSAGE
from . import deployed_check as dc

#: What the agent says instead of answering. Recording one would replay a
#: refusal to every visitor.
NON_ANSWERS = frozenset(
    {
        EMPTY_ANSWER_MESSAGE,
        NO_MESSAGE_MESSAGE,
        QUOTA_EXCEEDED_MESSAGE,
        USER_QUOTA_EXCEEDED_MESSAGE,
        MODEL_FAILED_MESSAGE,
        MODEL_THROTTLED_MESSAGE,
        TOOLS_UNREACHABLE_MESSAGE,
    }
)


@dataclasses.dataclass(frozen=True)
class RecordedAnswer:
    """One example question and the deployed agent's answer to it."""

    title: str
    question: str
    reasoning: str
    answer: str
    seconds: float
    #: Input at its price (cache reads a tenth), as the quota counts it.
    input_tokens: int
    output_tokens: int


def example_questions(site_toml: str) -> list[tuple[str, str]]:
    """The (title, question) of each example on the chat's start screen."""
    actions = tomllib.loads(site_toml)["chat"]["suggestedActions"]
    return [(action["title"], action["action"]) for action in actions]


def split_stream(text: str) -> tuple[str, str]:
    """The (reasoning, answer) of an AI SDK v5 stream."""
    reasoning, answer = [], []
    for kind, delta in dc.stream_text(text):
        (reasoning if kind == "reasoning-delta" else answer).append(delta)
    return "".join(reasoning), "".join(answer)


def is_real_answer(answer: str) -> bool:
    return bool(answer.strip()) and answer.strip() not in NON_ANSWERS


def render_demo_answers(recorded_at: str, model_id: str, answers: list[RecordedAnswer]) -> str:
    """The file the web app imports, in its camelCase."""
    data = {
        "recordedAt": recorded_at,
        "model": model_id,
        "answers": [
            {
                "title": a.title,
                "question": a.question,
                "reasoning": a.reasoning,
                "answer": a.answer,
                "seconds": round(a.seconds, 1),
                "inputTokens": a.input_tokens,
                "outputTokens": a.output_tokens,
            }
            for a in answers
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def quota_table_name(session: boto3.Session) -> str:  # pragma: no cover - needs AWS
    resources = session.client("cloudformation").describe_stack_resources(StackName=dc.STACK_NAME)
    for resource in resources["StackResources"]:
        if resource["ResourceType"] == "AWS::DynamoDB::Table":
            return resource["PhysicalResourceId"]
    raise RuntimeError(f"No DynamoDB table in stack {dc.STACK_NAME}")


def run(model_id: str) -> int:  # pragma: no cover - needs AWS and the deployed agent
    from ..api import one
    from ..quota import get_usage
    from ..quota import get_user_app_id
    from ..quota import ATTR_INPUT_TOKEN, ATTR_OUTPUT_TOKEN
    from ..runtimes.jwt_claims import jwt_claims

    session = boto3.Session(region_name=dc.REGION)
    outputs = dc.stack_outputs(session)
    url = dc.invocation_url(outputs["AgentRuntimeArn"])
    token = dc.access_token(session, outputs)
    dynamodb = session.client("dynamodb")
    config = dataclasses.replace(one.config, quota_enabled=True, dynamodb_table_name_quota=quota_table_name(session))
    user_key = {"app_id": {"S": get_user_app_id(config, str(jwt_claims(token)["sub"]))}}

    recorded = []
    questions = example_questions(path_enum.path_site_toml.read_text(encoding="utf-8"))
    for index, (title, question) in enumerate(questions, start=1):
        dynamodb.delete_item(TableName=config.dynamodb_table_name_quota, Key=user_key)
        started = time.monotonic()
        status, text = dc.post(url, dc.chat_body(question), {**dc.session_headers(), "Authorization": f"Bearer {token}"})
        seconds = time.monotonic() - started
        reasoning, answer = split_stream(text)
        if status != 200 or not is_real_answer(answer):
            print(f"FAILED on {title!r}: HTTP {status}: {answer[:300] or text[:300]}")
            return 1
        usage = get_usage(dynamodb, config, user_key["app_id"]["S"])
        recorded.append(
            RecordedAnswer(
                title=title,
                question=question,
                reasoning=reasoning,
                answer=answer,
                seconds=seconds,
                input_tokens=usage[ATTR_INPUT_TOKEN],
                output_tokens=usage[ATTR_OUTPUT_TOKEN],
            )
        )
        print(
            f"[{index}/{len(questions)}] {title}: {seconds:.0f} s, "
            f"{usage[ATTR_INPUT_TOKEN]:,} input (at its price) + {usage[ATTR_OUTPUT_TOKEN]:,} output tokens"
        )
    # leave the test user a fresh allowance for `mise run ac-test`
    dynamodb.delete_item(TableName=config.dynamodb_table_name_quota, Key=user_key)

    recorded_at = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    path_enum.path_demo_answers_json.write_text(render_demo_answers(recorded_at, model_id, recorded), encoding="utf-8")
    print(f"Wrote {len(recorded)} answers to {path_enum.path_demo_answers_json.relative_to(path_enum.dir_project_root)}")
    return 0
