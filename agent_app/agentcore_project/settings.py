# -*- coding: utf-8 -*-

"""
The deployment's settings: fixed names here, the rest from the environment
(``.env.defaults`` for what may be published, ``.env`` for the Snowflake
account) and the AWS account the developer's credentials belong to.
"""

import dataclasses

from ..paths import path_enum

#: The AgentCore project, as the CLI names its stack (``AgentCore-<project>-<target>``).
PROJECT_NAME = "LuminaReachAnalytics"
#: The one deployment target.
TARGET_NAME = "dev"
#: The runtimes' Python, the version of this repo's ``.venv`` and ``uv.lock``.
RUNTIME_PYTHON = "3.13"
RUNTIME_VERSION = "PYTHON_" + RUNTIME_PYTHON.replace(".", "_")
#: The SSM SecureString of the Snowflake service user's private key. Written
#: by ``agent-app snowflake-key-deploy``, read by the MCP runtime's role only.
SNOWFLAKE_KEY_PARAM_NAME = "/lumina-reach-analytics/snowflake-private-key"

DIR_AGENTCORE = path_enum.dir_project_root / "agentcore"
PATH_AGENTCORE_JSON = DIR_AGENTCORE / "agentcore.json"
PATH_AWS_TARGETS_JSON = DIR_AGENTCORE / "aws-targets.json"
PATH_APP_CONFIG_JSON = DIR_AGENTCORE / "app-config.json"
#: The runtimes' code directories (``codeLocation``), a git-ignored build output.
DIR_CODEZIP = path_enum.dir_project_root / "build" / "agentcore"

#: The web app's sign-in callback route, under each of WEB_ORIGINS.
AUTH_CALLBACK_PATH = "/api/auth/callback"


@dataclasses.dataclass(frozen=True)
class DeploySettings:
    account_id: str
    region: str
    model_id: str  #: The agent's Bedrock model (an inference profile ID).
    cognito_domain_prefix: str
    web_origins: tuple[str, ...]  #: Where the web app runs, e.g. ``http://localhost:3000``.
    snowflake: dict[str, str]  #: The ``SNOWFLAKE_*`` settings the MCP runtime connects with.
    schema_name: str


#: The Snowflake settings the MCP runtime needs, by environment variable.
SNOWFLAKE_VARS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
)


def deploy_settings_from_env(config, get_env, account_id: str) -> DeploySettings:
    """
    The settings of the deployment from the local config.

    :raises ValueError: naming every setting that is missing.
    """
    snowflake = {
        "SNOWFLAKE_ACCOUNT": config.snowflake_account,
        "SNOWFLAKE_USER": config.snowflake_user,
        "SNOWFLAKE_ROLE": config.snowflake_role,
        "SNOWFLAKE_WAREHOUSE": config.snowflake_warehouse,
        "SNOWFLAKE_DATABASE": config.snowflake_database,
    }
    values = {
        **snowflake,
        "AGENTCORE_LLM_MODEL_ID": get_env("AGENTCORE_LLM_MODEL_ID"),
        "COGNITO_DOMAIN_PREFIX": get_env("COGNITO_DOMAIN_PREFIX"),
        "WEB_ORIGINS": get_env("WEB_ORIGINS"),
        "AWS_REGION": config.aws_region,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Set these before generating the AgentCore project: {', '.join(missing)}")
    origins = tuple(o.strip().rstrip("/") for o in values["WEB_ORIGINS"].split(",") if o.strip())
    return DeploySettings(
        account_id=account_id,
        region=values["AWS_REGION"],
        model_id=values["AGENTCORE_LLM_MODEL_ID"],
        cognito_domain_prefix=values["COGNITO_DOMAIN_PREFIX"],
        web_origins=origins,
        snowflake={k: str(v) for k, v in snowflake.items()},
        schema_name=config.schema_name,
    )
