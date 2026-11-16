# -*- coding: utf-8 -*-

"""
Check the deployed agent end to end, the way the web app will call it.

1. Signs a test user in to the deployment's Cognito user pool (created on the
   first run with a random password kept in git-ignored ``tmp/``; nothing is
   printed) and gets an access token.
2. Asks the agent one question with that token, over AgentCore's HTTPS
   invocation endpoint, and prints the streamed answer.
3. Checks the agent refuses a call with no token, and one signed with your
   own AWS credentials (SigV4): the JWT authorizer accepts nothing else.

Run it as ``mise run ac-test`` (= ``agent-app test-deployed [--question ...]``)
after ``mise run ac-deploy``. It writes to AWS only to create the test user,
once.
"""

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
import boto3

from ..paths import path_enum

REGION = "us-east-2"
STACK_NAME = "AgentCore-LuminaReachAnalytics-dev"
TEST_USER_EMAIL = "deploy-test@example.com"
PATH_TEST_USER = path_enum.dir_tmp / "deployed-test-user.json"
DEFAULT_QUESTION = "Which three campaigns spent the most, and what was each one's CPA?"


def stack_outputs(session: boto3.Session) -> dict[str, str]:  # pragma: no cover - needs AWS
    stack = session.client("cloudformation").describe_stacks(StackName=STACK_NAME)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def test_user_password(cognito, user_pool_id: str) -> str:  # pragma: no cover - needs AWS
    """The test user's password, creating the user on the first run."""
    if PATH_TEST_USER.is_file():
        saved = json.loads(PATH_TEST_USER.read_text())
        if saved.get("user_pool_id") == user_pool_id:
            return saved["password"]
    password = secrets.token_urlsafe(24) + "aA1"
    try:
        cognito.admin_create_user(
            UserPoolId=user_pool_id,
            Username=TEST_USER_EMAIL,
            UserAttributes=[
                {"Name": "email", "Value": TEST_USER_EMAIL},
                {"Name": "email_verified", "Value": "true"},
            ],
            MessageAction="SUPPRESS",
        )
    except cognito.exceptions.UsernameExistsException:
        pass
    cognito.admin_set_user_password(UserPoolId=user_pool_id, Username=TEST_USER_EMAIL, Password=password, Permanent=True)
    PATH_TEST_USER.parent.mkdir(parents=True, exist_ok=True)
    PATH_TEST_USER.write_text(json.dumps({"user_pool_id": user_pool_id, "password": password}))
    PATH_TEST_USER.chmod(0o600)
    print(f"Created the test user {TEST_USER_EMAIL} (password in {PATH_TEST_USER.name}, git-ignored)")
    return password


def access_token(session: boto3.Session, outputs: dict[str, str]) -> str:  # pragma: no cover - needs AWS
    cognito = session.client("cognito-idp")
    password = test_user_password(cognito, outputs["UserPoolId"])
    result = cognito.admin_initiate_auth(
        UserPoolId=outputs["UserPoolId"],
        ClientId=outputs["WebClientId"],
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": TEST_USER_EMAIL, "PASSWORD": password},
    )
    return result["AuthenticationResult"]["AccessToken"]


def invocation_url(runtime_arn: str) -> str:
    escaped = urllib.parse.quote(runtime_arn, safe="")
    return f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{escaped}/invocations?qualifier=DEFAULT"


def chat_body(question: str) -> bytes:
    return json.dumps(
        {
            "id": "deployed-test",
            "trigger": "submit-message",
            "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": question}]}],
        }
    ).encode()


def session_headers() -> dict[str, str]:
    # AgentCore wants a session id of at least 33 characters
    return {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": f"deployed-test-{uuid.uuid4()}",
    }


def post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:  # pragma: no cover - network
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def stream_text(text: str) -> list[tuple[str, str]]:
    """
    The (type, text) of every reasoning and text delta in an AI SDK v5 stream.
    """
    out = []
    for line in text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            event = json.loads(line[len("data: "):])
            if event.get("type") in ("reasoning-delta", "text-delta"):
                out.append((event["type"], event["delta"]))
    return out


def sigv4_post(session: boto3.Session, url: str, body: bytes) -> int:  # pragma: no cover - network
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    request = AWSRequest(method="POST", url=url, data=body, headers=session_headers())
    SigV4Auth(session.get_credentials(), "bedrock-agentcore", REGION).add_auth(request)
    return post(url, body, dict(request.headers))[0]


def run(question: str = DEFAULT_QUESTION) -> int:  # pragma: no cover - needs AWS
    session = boto3.Session(region_name=REGION)
    outputs = stack_outputs(session)
    url = invocation_url(outputs["AgentRuntimeArn"])
    body = chat_body(question)

    token = access_token(session, outputs)
    status, text = post(url, body, {**session_headers(), "Authorization": f"Bearer {token}"})
    print(f"With a Cognito access token: HTTP {status}")
    if status == 200:
        for kind, delta in stream_text(text):
            print(f"--- {kind}\n{delta}\n")
    else:
        print(text[:500])

    no_token = post(url, body, session_headers())[0]
    signed = sigv4_post(session, url, body)
    print(f"With no token: HTTP {no_token}; signed with your AWS credentials: HTTP {signed}")
    refused = no_token in (401, 403) and signed in (401, 403)
    print("OK: only a Cognito token gets in" if refused else "UNEXPECTED: a call without a token was not refused")
    return 0 if status == 200 and refused else 1

