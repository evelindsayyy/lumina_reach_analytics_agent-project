# -*- coding: utf-8 -*-

"""
The generated AgentCore project. Fictional account and names; no AWS.
"""

import dataclasses
import json
import tomllib

import pytest

from agent_app.agentcore_project import codezip
from agent_app.agentcore_project import gen
from agent_app.agentcore_project import project_files as pf
from agent_app.agentcore_project import settings as s
from agent_app.db_schema.snapshot import SchemaSnapshot
from agent_app.runtimes.common import AGENT_RUNTIME_NAME, MCP_RUNTIME_NAME


@dataclasses.dataclass
class FakeConfig:
    snowflake_account: str | None = "acme-test"
    snowflake_user: str | None = "ACME_SVC"
    snowflake_role: str | None = "ACME_READER"
    snowflake_warehouse: str | None = "ACME_WH"
    snowflake_database: str | None = "ACME"
    aws_region: str | None = "us-east-2"
    schema_name: str = "acme_widgets"


ENV = {
    "AGENTCORE_LLM_PROVIDER": "bedrock",
    "AGENTCORE_LLM_MODEL_ID": "us.acme.model-v1",
    "COGNITO_DOMAIN_PREFIX": "acme-login",
    "WEB_ORIGINS": "http://localhost:3000, https://acme.example/ ",
}


SNAPSHOT = SchemaSnapshot(
    schema_name="acme_widgets",
    warehouse_engine="snowflake",
    schema_str="snowflake Database acme_widgets(...)",
    table_columns={"widget": frozenset({"widget_id"})},
)


def settings(**env_overrides) -> s.DeploySettings:
    env = {**ENV, **env_overrides}
    return s.deploy_settings_from_env(FakeConfig(), env.get, account_id="111122223333")


class TestDeploySettings:
    def test_origins_are_trimmed(self):
        assert settings().web_origins == ("http://localhost:3000", "https://acme.example")

    def test_an_unknown_provider_is_refused(self):
        with pytest.raises(ValueError, match="AGENTCORE_LLM_PROVIDER"):
            settings(AGENTCORE_LLM_PROVIDER="openai")

    def test_every_missing_setting_is_named(self):
        config = FakeConfig(snowflake_account=None)
        with pytest.raises(ValueError) as e:
            s.deploy_settings_from_env(config, {}.get, account_id="111122223333")
        for name in ("SNOWFLAKE_ACCOUNT", "AGENTCORE_LLM_PROVIDER", "AGENTCORE_LLM_MODEL_ID", "COGNITO_DOMAIN_PREFIX", "WEB_ORIGINS"):
            assert name in str(e.value)


class TestRuntimeEnvVars:
    def test_the_agent_holds_no_warehouse_setting(self):
        agent = pf.runtime_env_vars(settings())[AGENT_RUNTIME_NAME]
        assert not [k for k in agent if k.startswith("SNOWFLAKE") or k == "WAREHOUSE_ENGINE"]
        assert agent["LLM_PROVIDER"] == "bedrock"
        assert agent["LLM_MODEL_ID"] == "us.acme.model-v1"
        assert agent["QUOTA_ENABLED"] == "true"

    def test_on_bedrock_the_agent_has_no_secret(self):
        agent = pf.runtime_env_vars(settings())[AGENT_RUNTIME_NAME]
        assert not [k for k in agent if k.endswith("_SSM_PARAM")]
        assert pf.build_app_config(settings())["agentUsesBedrock"] is True

    def test_on_anthropic_the_agent_gets_its_key_name_only(self):
        st = settings(AGENTCORE_LLM_PROVIDER="Anthropic", AGENTCORE_LLM_MODEL_ID="claude-acme")
        envs = pf.runtime_env_vars(st)
        agent, mcp = envs[AGENT_RUNTIME_NAME], envs[MCP_RUNTIME_NAME]
        assert agent["LLM_PROVIDER"] == "anthropic"
        assert agent["ANTHROPIC_API_KEY_SSM_PARAM"] == s.ANTHROPIC_KEY_PARAM_NAME
        assert "ANTHROPIC_API_KEY" not in agent
        assert "ANTHROPIC_API_KEY_SSM_PARAM" not in mcp
        assert pf.build_app_config(st)["agentUsesBedrock"] is False

    def test_the_mcp_server_gets_the_key_name_not_the_key(self):
        mcp = pf.runtime_env_vars(settings())[MCP_RUNTIME_NAME]
        assert mcp["WAREHOUSE_ENGINE"] == "snowflake"
        assert mcp["SNOWFLAKE_PRIVATE_KEY_SSM_PARAM"] == s.SNOWFLAKE_KEY_PARAM_NAME
        assert "SNOWFLAKE_PRIVATE_KEY" not in mcp
        assert "LLM_PROVIDER" not in mcp

    def test_both_know_they_are_in_agentcore(self):
        for env in pf.runtime_env_vars(settings()).values():
            assert env["IS_AGENTCORE_RUNTIME"] == "true"
            assert env["SCHEMA_NAME"] == "acme_widgets"


class TestProjectFiles:
    def test_agentcore_json(self):
        data = pf.build_agentcore_json(settings())
        assert data["name"] == s.PROJECT_NAME and data["version"] == 2
        runtimes = {r["name"]: r for r in data["runtimes"]}
        assert runtimes[MCP_RUNTIME_NAME]["protocol"] == "MCP"
        assert runtimes[AGENT_RUNTIME_NAME]["protocol"] == "HTTP"
        for name, runtime in runtimes.items():
            assert runtime["codeLocation"] == f"build/agentcore/{name}"
            assert runtime["runtimeVersion"] == s.RUNTIME_VERSION
            # inbound auth of the agent is set by the stack, which knows the user pool
            assert "authorizerType" not in runtime

    def test_empty_project_declares_nothing(self):
        assert "runtimes" not in pf.build_empty_agentcore_json()

    def test_targets(self):
        assert pf.build_aws_targets_json(settings()) == [
            {"name": s.TARGET_NAME, "description": "The demo deployment", "account": "111122223333", "region": "us-east-2"}
        ]

    def test_app_config_has_a_callback_per_origin(self):
        cfg = pf.build_app_config(settings())
        assert cfg["callbackUrls"] == [
            "http://localhost:3000/api/auth/callback",
            "https://acme.example/api/auth/callback",
        ]
        assert cfg["logoutUrls"] == ["http://localhost:3000/", "https://acme.example/"]
        assert cfg["cognitoDomainPrefix"] == "acme-login"

    def test_write_json_reports_a_change_only(self, tmp_path):
        path = tmp_path / "sub" / "a.json"
        assert pf.write_json(path, {"a": 1}) is True
        assert pf.write_json(path, {"a": 1}) is False
        assert json.loads(path.read_text()) == {"a": 1}


class TestCodeZip:
    def test_main_py_of_each_protocol(self):
        assert "import app" not in codezip.render_main_py("runtimes.analytics_mcp", is_http=False)
        http = codezip.render_main_py("runtimes.analytics_agent", is_http=True)
        assert "from agent_app.runtimes.analytics_agent import main" in http
        assert "from agent_app.runtimes.analytics_agent import app" in http

    def test_requirements_drop_comments_and_editables(self):
        text = "# header\nboto3==1.43.0\n\n-e .\nmcp==1.28.1 ; python_version >= '3.10'\n"
        assert codezip.parse_requirements(text) == ["boto3==1.43.0", "mcp==1.28.1 ; python_version >= '3.10'"]

    def test_pyproject_is_valid_toml(self):
        text = codezip.render_pyproject_toml("AcmeMcp", ['mcp==1.28.1 ; python_version >= "3.10"'])
        data = tomllib.loads(text)
        assert data["project"]["name"] == "acmemcp"
        assert data["project"]["dependencies"] == ['mcp==1.28.1 ; python_version >= "3.10"']

    def test_assembled_dir_mirrors_the_repo_root(self, tmp_path):
        dir_runtime = tmp_path / "AcmeMcp"
        (dir_runtime / ".venv").mkdir(parents=True)  # agentcore dev's, must survive
        codezip.assemble_runtime_dir(dir_runtime, "AcmeMcp", "runtimes.analytics_mcp", False, ["mcp==1.28.1"])
        for name in ("main.py", "pyproject.toml", ".env.defaults", "data/system-prompt.md", "agent_app/runtimes/analytics_mcp.py"):
            assert (dir_runtime / name).is_file(), name
        assert (dir_runtime / ".venv").is_dir()
        assert not (dir_runtime / "agent_app" / "agentcore_project").exists()
        assert not (dir_runtime / "agent_app" / "tests").exists()
        assert not list(dir_runtime.rglob("__pycache__"))


class TestGenerate:
    @pytest.fixture
    def into_tmp(self, monkeypatch, tmp_path):
        dir_agentcore = tmp_path / "agentcore"
        for name, value in {
            "DIR_AGENTCORE": dir_agentcore,
            "PATH_AGENTCORE_JSON": dir_agentcore / "agentcore.json",
            "PATH_AWS_TARGETS_JSON": dir_agentcore / "aws-targets.json",
            "PATH_APP_CONFIG_JSON": dir_agentcore / "app-config.json",
            "DIR_CODEZIP": tmp_path / "build" / "agentcore",
        }.items():
            monkeypatch.setattr(s, name, value)
        return tmp_path

    def test_generate_all(self, into_tmp):
        gen.generate_all(settings(), ["mcp==1.28.1"], SNAPSHOT)
        assert len(json.loads((into_tmp / "agentcore" / "agentcore.json").read_text())["runtimes"]) == 2
        assert (into_tmp / "agentcore" / "app-config.json").is_file()
        for name in (MCP_RUNTIME_NAME, AGENT_RUNTIME_NAME):
            assert (into_tmp / "build" / "agentcore" / name / "main.py").is_file()

    def test_only_the_mcp_server_ships_the_schema_snapshot(self, into_tmp):
        """Next to the package, which is where the runtime's path_enum looks."""
        from agent_app.db_schema.snapshot import load_snapshot
        from agent_app.paths import path_enum

        gen.generate_all(settings(), ["mcp==1.28.1"], SNAPSHOT)
        dir_codezip = into_tmp / "build" / "agentcore"
        name = path_enum.path_schema_snapshot_json.name
        assert path_enum.path_schema_snapshot_json.parent == path_enum.dir_package.parent
        assert load_snapshot(dir_codezip / MCP_RUNTIME_NAME / name, "acme_widgets", "snowflake") == SNAPSHOT
        assert not (dir_codezip / AGENT_RUNTIME_NAME / name).exists()

    def test_the_snapshot_is_of_the_engine_the_mcp_server_runs(self):
        """Taken here on DuckDB, which needs no account; deployed it is Snowflake."""
        from agent_app.api import one

        snapshot = gen.schema_snapshot(one.config, "duckdb")
        assert snapshot.warehouse_engine == "duckdb"
        assert snapshot.schema_str.startswith("duckdb Database")
        assert s.MCP_WAREHOUSE_ENGINE == "snowflake"
        assert pf.runtime_env_vars(settings())[MCP_RUNTIME_NAME]["WAREHOUSE_ENGINE"] == s.MCP_WAREHOUSE_ENGINE

    def test_generate_teardown(self, into_tmp):
        gen.generate_teardown(settings())
        assert "runtimes" not in json.loads((into_tmp / "agentcore" / "agentcore.json").read_text())


class TestDeployedCheck:
    def test_invocation_url_escapes_the_arn(self):
        from agent_app.agentcore_project import deployed_check as dc

        url = dc.invocation_url("arn:aws:bedrock-agentcore:us-east-2:111122223333:runtime/acme-x1")
        assert url.endswith("/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-2%3A111122223333%3Aruntime%2Facme-x1/invocations?qualifier=DEFAULT")

    def test_session_id_is_long_enough(self):
        from agent_app.agentcore_project import deployed_check as dc

        assert len(dc.session_headers()["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"]) >= 33

    def test_chat_body_is_an_ai_sdk_request(self):
        from agent_app.agentcore_project import deployed_check as dc
        from agent_app.vendor.vercel_ai_sdk import RequestBody

        RequestBody.model_validate(json.loads(dc.chat_body("How many widgets?")))

    def test_stream_text_keeps_reasoning_and_text(self):
        from agent_app.agentcore_project import deployed_check as dc

        text = (
            'data: {"type":"reasoning-delta","id":"r","delta":"think"}\n\n'
            'data: {"type":"text-start","id":"t"}\n\n'
            'data: {"type":"text-delta","id":"t","delta":"42"}\n\n'
            "data: [DONE]\n\n"
        )
        assert dc.stream_text(text) == [("reasoning-delta", "think"), ("text-delta", "42")]


class TestWebEnv:
    OUTPUTS = {"CognitoDomain": "https://acme.auth.example", "WebClientId": "acmeclient", "AgentRuntimeArn": "arn:acme", "Other": "x"}

    def test_maps_the_stack_outputs(self):
        from agent_app.agentcore_project import web_env

        assert web_env.web_env(self.OUTPUTS) == {
            "COGNITO_DOMAIN": "https://acme.auth.example",
            "COGNITO_CLIENT_ID": "acmeclient",
            "AGENT_RUNTIME_ARN": "arn:acme",
        }

    def test_a_missing_output_is_named(self):
        from agent_app.agentcore_project import web_env

        with pytest.raises(KeyError, match="WebClientId"):
            web_env.web_env({"CognitoDomain": "d", "AgentRuntimeArn": "a"})

    def test_writes_a_dotenv_file(self, tmp_path):
        from agent_app.agentcore_project import web_env

        path = tmp_path / ".env.local"
        web_env.write_env_local(web_env.web_env(self.OUTPUTS), path)
        text = path.read_text()
        assert 'COGNITO_CLIENT_ID="acmeclient"' in text and text.startswith("# Generated")
