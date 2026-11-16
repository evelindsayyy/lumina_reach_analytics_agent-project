# -*- coding: utf-8 -*-

"""
The files of ``agentcore/`` that ``agent-app ac-gen`` writes, all git-ignored
because they carry the account ID and the Snowflake account:

- ``agentcore.json``: the two runtimes, each with only its own ``envVars``.
- ``aws-targets.json``: the one target.
- ``app-config.json``: what the CDK stack (``agentcore/cdk/lib/cdk-stack.ts``)
  needs beyond ``agentcore.json``: the SSM parameter, the Cognito domain, the
  web app's URLs.

Pure functions of :class:`.settings.DeploySettings`, tested without AWS.
"""

import json
from pathlib import Path

from ..runtime import IS_AGENTCORE_RUNTIME_VAR, IS_AGENTCORE_RUNTIME_VALUE
from ..config import SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR
from ..runtimes.common import AGENT_RUNTIME_NAME, MCP_RUNTIME_NAME
from . import settings as s


def runtime_env_vars(settings: s.DeploySettings) -> dict[str, dict[str, str]]:
    """
    Each runtime's environment, by runtime name. Disjoint on purpose: the
    agent gets the model and the quota and no warehouse setting at all; the
    MCP server gets the warehouse and the name (not the value) of its key.
    """
    common = {
        IS_AGENTCORE_RUNTIME_VAR: IS_AGENTCORE_RUNTIME_VALUE,
        "AWS_REGION": settings.region,
        "SCHEMA_NAME": settings.schema_name,
    }
    return {
        MCP_RUNTIME_NAME: {
            **common,
            "WAREHOUSE_ENGINE": "snowflake",
            **settings.snowflake,
            SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR: s.SNOWFLAKE_KEY_PARAM_NAME,
        },
        AGENT_RUNTIME_NAME: {
            **common,
            "LLM_PROVIDER": "bedrock",
            "LLM_MODEL_ID": settings.model_id,
            # the table's name arrives from the stack (addEnvironmentVariable)
            "QUOTA_ENABLED": "true",
        },
    }


def build_empty_agentcore_json() -> dict:
    """
    An ``agentcore.json`` that declares nothing: deploying it destroys the
    target's stack (the CLI's own teardown).
    """
    return {"name": s.PROJECT_NAME, "version": 2, "managedBy": "CDK"}


def build_agentcore_json(settings: s.DeploySettings) -> dict:
    """
    The two runtimes. The MCP server is listed first; the stack binds it to
    the agent. Inbound auth of the agent (Cognito JWT) is set in the stack,
    which knows the user pool.
    """
    env_vars = runtime_env_vars(settings)
    runtimes = []
    for name, protocol in ((MCP_RUNTIME_NAME, "MCP"), (AGENT_RUNTIME_NAME, "HTTP")):
        runtimes.append(
            {
                "name": name,
                "build": "CodeZip",
                "entrypoint": "main.py",
                "codeLocation": f"{s.DIR_CODEZIP.relative_to(s.DIR_AGENTCORE.parent).as_posix()}/{name}",
                "runtimeVersion": s.RUNTIME_VERSION,
                "protocol": protocol,
                "envVars": [{"name": k, "value": v} for k, v in env_vars[name].items()],
            }
        )
    return {**build_empty_agentcore_json(), "runtimes": runtimes}


def build_aws_targets_json(settings: s.DeploySettings) -> list[dict]:
    return [
        {
            "name": s.TARGET_NAME,
            "description": "The demo deployment",
            "account": settings.account_id,
            "region": settings.region,
        }
    ]


def build_app_config(settings: s.DeploySettings) -> dict:
    return {
        "agentRuntimeName": AGENT_RUNTIME_NAME,
        "mcpRuntimeName": MCP_RUNTIME_NAME,
        "snowflakeKeyParamName": s.SNOWFLAKE_KEY_PARAM_NAME,
        "cognitoDomainPrefix": settings.cognito_domain_prefix,
        "callbackUrls": [f"{o}{s.AUTH_CALLBACK_PATH}" for o in settings.web_origins],
        "logoutUrls": [f"{o}/" for o in settings.web_origins],
    }


def write_json(path: Path, data: dict | list) -> bool:
    """
    Write ``data`` as indented JSON; True if the file changed.
    """
    content = json.dumps(data, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True
