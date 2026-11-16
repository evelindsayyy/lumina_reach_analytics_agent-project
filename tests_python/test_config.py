# -*- coding: utf-8 -*-

"""
Test for Config.

Signature-level only: build a Config, touch every property and method, and check
the shape of what comes back. No environment mutation, no network, no I/O.
"""

import pytest

from agent_app.config import SCHEMA_NAME_PATTERN, Config
from agent_app.runtime import runtime


class TestConfig:
    def test_defaults(self):
        """A bare Config() fills in the selected provider's default model.

        The default is ``openai`` rather than ``bedrock`` on purpose: it needs
        one API key and no cloud account, which is the lowest barrier for
        someone opening this repo for the first time.
        """
        config = Config()
        assert config.llm_provider == "openai"
        assert config.model_id  # filled in by __post_init__

    def test_unknown_provider(self):
        """An unsupported LLM_PROVIDER fails loudly instead of silently."""
        with pytest.raises(ValueError):
            Config(llm_provider="llama")

    def test_llm_api_key(self):
        """llm_api_key returns the selected provider's key; bedrock has none."""
        assert Config(llm_provider="anthropic", anthropic_api_key="k").llm_api_key == "k"
        assert Config(llm_provider="openai", openai_api_key="k").llm_api_key == "k"
        assert Config(llm_provider="google", google_api_key="k").llm_api_key == "k"
        assert Config(llm_provider="bedrock").llm_api_key is None

    def test_validate(self):
        """validate() checks only the selected provider's credential."""
        Config(openai_api_key="k").validate()  # the default provider
        Config(llm_provider="bedrock", aws_region="us-east-1").validate()
        with pytest.raises(ValueError):
            Config().validate()  # openai, no key
        with pytest.raises(ValueError):
            Config(llm_provider="bedrock").validate()  # no region

    def test_factories(self):
        """Each factory returns a usable Config."""
        assert isinstance(Config.new_in_local_runtime(), Config)
        assert isinstance(Config.new_in_vercel_runtime(), Config)
        assert isinstance(Config.new(), Config)


class TestQuotaConfig:
    def test_cap_on_without_a_table_is_refused(self):
        """
        Caught at start-up rather than on some user's first request. The check
        used to live in ``quota._table``, where a misconfigured public
        deployment booted fine and failed the moment someone typed.
        """
        with pytest.raises(ValueError, match="DYNAMODB_TABLE_NAME_QUOTA"):
            Config(quota_enabled=True)

    def test_cap_on_with_a_table_is_fine(self):
        assert Config(
            quota_enabled=True, dynamodb_table_name_quota="my-quota"
        ).quota_enabled is True

    def test_cap_off_needs_no_table(self):
        assert Config().quota_enabled is False


class TestFactories:
    """
    Two runtimes, one shared reader, exactly one difference between them.

    ``new_from_env_var`` does the reading; the factories differ only in whether
    they hand it AWS credentials. These tests pin that difference, because it is
    the entire reason there are two factories rather than one.
    """

    def test_new_from_env_var_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("SCHEMA_NAME", "acme_widgets")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("WAREHOUSE_ENGINE", "Snowflake")
        monkeypatch.setenv("QUOTA_ENABLED", "true")
        monkeypatch.setenv("DYNAMODB_TABLE_NAME_QUOTA", "my-quota")
        config = Config.new_from_env_var()
        assert config.schema_name == "acme_widgets"
        assert config.llm_provider == "openai"
        assert config.warehouse_engine == "snowflake"
        assert config.quota_enabled is True

    def test_new_from_env_var_never_reads_aws_credentials(self, monkeypatch):
        """
        The trap this guards: boto3 checks the environment BEFORE
        ~/.aws/credentials, so a placeholder picked up here would shadow a
        working local profile and Bedrock would fail with an opaque
        UnrecognizedClientException.
        """
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAPLACEHOLDER")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "shhh")
        config = Config.new_from_env_var()
        assert config.aws_access_key_id is None
        assert config.aws_secret_access_key is None

    def test_overrides_win_over_the_environment(self, monkeypatch):
        """How a runtime states its one difference, instead of copying the lot."""
        monkeypatch.setenv("SCHEMA_NAME", "from_env")
        assert Config.new_from_env_var(schema_name="acme_override").schema_name == (
            "acme_override"
        )

    def test_local_leaves_aws_to_the_credential_chain(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAPLACEHOLDER")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "shhh")
        config = Config.new_in_local_runtime()
        assert config.aws_access_key_id is None
        assert config.aws_secret_access_key is None

    def test_vercel_takes_aws_from_the_environment(self, monkeypatch):
        """Serverless has no ~/.aws, so there is no chain to fall back to."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAREAL")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "real")
        config = Config.new_in_vercel_runtime()
        assert config.aws_access_key_id == "AKIAREAL"
        assert config.aws_secret_access_key == "real"

    def test_new_dispatches_to_the_vercel_factory(self, monkeypatch):
        """
        `new()` exists only to pick a factory, and picking the Vercel one is the
        half that never happens on a laptop. Forcing it here is what stops a
        broken dispatch from shipping green.

        `runtime` caches its answer, so the cache has to be dropped on the way
        in and on the way out -- a stale True would leak into every later test.
        """
        runtime.__dict__.pop("_is_vercel", None)
        try:
            monkeypatch.setenv("VERCEL", "1")
            monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAREAL")
            monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "real")
            assert runtime.is_vercel()
            # Reading AWS from the environment is what only the Vercel factory
            # does, so it is the proof of which branch ran.
            assert Config.new().aws_access_key_id == "AKIAREAL"
        finally:
            runtime.__dict__.pop("_is_vercel", None)

    def test_new_dispatches_to_the_local_factory(self, monkeypatch):
        runtime.__dict__.pop("_is_vercel", None)
        try:
            monkeypatch.delenv("VERCEL", raising=False)
            monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAPLACEHOLDER")
            assert runtime.is_local()
            assert Config.new().aws_access_key_id is None
        finally:
            runtime.__dict__.pop("_is_vercel", None)

    def test_new_dispatches_to_the_agentcore_factory(self, monkeypatch):
        """The runtime signal comes from agentcore.json's envVars."""
        from agent_app.runtime import IS_AGENTCORE_RUNTIME_VAR, IS_AGENTCORE_RUNTIME_VALUE

        for name in ("_is_vercel", "_is_agentcore"):
            runtime.__dict__.pop(name, None)
        try:
            monkeypatch.delenv("VERCEL", raising=False)
            monkeypatch.setenv(IS_AGENTCORE_RUNTIME_VAR, IS_AGENTCORE_RUNTIME_VALUE)
            seen = []
            monkeypatch.setattr(Config, "new_in_agentcore_runtime", classmethod(lambda cls: seen.append(cls) or "ac"))
            assert runtime.is_agentcore()
            assert not runtime.is_local()
            assert Config.new() == "ac"
        finally:
            for name in ("_is_vercel", "_is_agentcore"):
                runtime.__dict__.pop(name, None)

    def test_placeholder_reads_as_unset(self, monkeypatch):
        """A .env copied from .env.example with "..." left in must not count."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "...")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "...")
        config = Config.new_in_vercel_runtime()
        assert config.aws_access_key_id is None
        assert config.aws_secret_access_key is None


class TestSchemaName:
    """
    The dataset's only identifier, from SCHEMA_NAME in the committed
    ``.env.defaults``.

    Checked at construction rather than at first use: the alternative failure is
    a query error from deep inside PostgreSQL, several layers from the typo. The
    value is also interpolated into a ``SET LOCAL search_path`` statement in
    ``one/one_02_db.py``, so it had better be an identifier.
    """

    @pytest.mark.parametrize("ok", ["a", "_private", "acme_widgets", "acme_2", "a" * 63])
    def test_legal_names_are_accepted(self, ok):
        assert Config(schema_name=ok).schema_name == ok
        assert SCHEMA_NAME_PATTERN.fullmatch(ok)

    @pytest.mark.parametrize(
        "bad",
        [
            "My-Schema",  # uppercase and a hyphen
            "acme widgets",  # whitespace
            "2acme",  # leading digit
            "acme;DROP",  # punctuation with no business in an identifier
            "a" * 64,  # one over PostgreSQL's limit
        ],
    )
    def test_illegal_names_are_rejected(self, bad):
        with pytest.raises(ValueError, match="SCHEMA_NAME"):
            Config(schema_name=bad)

    def test_unset_is_allowed_at_construction(self):
        """
        A bare ``Config()`` in a test must not have to know about the dataset.
        An empty schema name fails later, at reflection, with its own message.
        """
        assert Config().schema_name == ""

    def test_committed_default_is_loaded(self):
        """
        The real .env.defaults reaches Config. This is the one test that would
        catch the file being renamed, or Vercel's factory forgetting to load it.
        """
        for config in (Config.new_in_local_runtime(), Config.new_in_vercel_runtime()):
            assert SCHEMA_NAME_PATTERN.fullmatch(config.schema_name)


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.config",
        preview=False,
    )


class TestWarehouseConfig:
    def test_duckdb_is_the_default(self):
        assert Config().warehouse_engine == "duckdb"

    def test_an_unknown_engine_fails_at_start_up(self):
        with pytest.raises(ValueError, match="WAREHOUSE_ENGINE"):
            Config(warehouse_engine="postgres")

    def test_the_private_key_never_appears_in_repr(self):
        assert "BEGIN" not in repr(Config(snowflake_private_key_pem="-----BEGIN PRIVATE KEY-----"))

    def test_key_from_the_env_var_wins(self, monkeypatch, tmp_path):
        from agent_app.config import read_private_key_pem

        path = tmp_path / "key.pem"
        path.write_text("from-file", encoding="utf-8")
        monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", str(path))
        monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY", "from-env")
        assert read_private_key_pem() == "from-env"

    def test_key_from_a_file(self, monkeypatch, tmp_path):
        from agent_app.config import read_private_key_pem

        path = tmp_path / "key.pem"
        path.write_text("from-file", encoding="utf-8")
        monkeypatch.delenv("SNOWFLAKE_PRIVATE_KEY", raising=False)
        monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", str(path))
        assert read_private_key_pem() == "from-file"

    def test_a_missing_key_file_is_no_key(self, monkeypatch, tmp_path):
        """A stale path must not stop a DuckDB-only machine from booting."""
        from agent_app.config import read_private_key_pem

        monkeypatch.delenv("SNOWFLAKE_PRIVATE_KEY", raising=False)
        monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", str(tmp_path / "missing.pem"))
        assert read_private_key_pem() is None

    def test_duckdb_path_override(self, monkeypatch):
        monkeypatch.setenv("DUCKDB_PATH", "/data/acme_widgets.duckdb")
        assert str(Config.new_from_env_var().duckdb_path) == "/data/acme_widgets.duckdb"


class TestSystemPromptContent:
    """The prompt is a committed file; reading it needs no infrastructure."""

    def test_reads_the_committed_prompt(self):
        from agent_app.paths import path_enum

        content = path_enum.path_bi_agent_system_prompt_content
        assert isinstance(content, str)
        assert content.strip(), "an empty system prompt would give the agent no brain"

    def test_read_once_per_process(self):
        """cached_property: the agent is rebuilt more often than the file changes."""
        from agent_app.paths import path_enum

        assert (
            path_enum.path_bi_agent_system_prompt_content
            is path_enum.path_bi_agent_system_prompt_content
        )


class TestEnvReaders:
    """
    The three readers between ``os.environ`` and a typed field. Small, but every
    branch is a decision about what a malformed value means, and getting one
    wrong changes behaviour silently rather than raising.
    """

    def test_placeholder_and_unset_both_read_as_none(self, monkeypatch):
        from agent_app.config import PLACEHOLDER, get_env

        monkeypatch.setenv("X_TEST", PLACEHOLDER)
        assert get_env("X_TEST") is None
        monkeypatch.delenv("X_TEST")
        assert get_env("X_TEST") is None

    def test_a_real_value_comes_through(self, monkeypatch):
        from agent_app.config import get_env

        monkeypatch.setenv("X_TEST", "value")
        assert get_env("X_TEST") == "value"

    @pytest.mark.parametrize("spelling", ["1", "true", "TRUE", "Yes", " on "])
    def test_bool_accepts_what_people_actually_type(self, monkeypatch, spelling):
        from agent_app.config import get_env_bool

        monkeypatch.setenv("X_FLAG", spelling)
        assert get_env_bool("X_FLAG") is True

    @pytest.mark.parametrize("spelling", ["0", "false", "NO", "Off"])
    def test_bool_falsy_spellings(self, monkeypatch, spelling):
        from agent_app.config import get_env_bool

        monkeypatch.setenv("X_FLAG", spelling)
        assert get_env_bool("X_FLAG", default=True) is False

    def test_bool_unset_takes_the_default(self, monkeypatch):
        from agent_app.config import get_env_bool

        monkeypatch.delenv("X_FLAG", raising=False)
        assert get_env_bool("X_FLAG", default=True) is True

    def test_bool_gibberish_takes_the_default(self, monkeypatch):
        """A malformed flag should leave its feature off, not stop the app booting."""
        from agent_app.config import get_env_bool

        monkeypatch.setenv("X_FLAG", "maybe")
        assert get_env_bool("X_FLAG") is False
        assert get_env_bool("X_FLAG", default=True) is True

    def test_int_parses(self, monkeypatch):
        from agent_app.config import get_env_int

        monkeypatch.setenv("X_PORT", "5432")
        assert get_env_int("X_PORT") == 5432

    def test_int_unset_or_malformed_is_none(self, monkeypatch):
        """
        None is what callers already treat as "not configured", so a typo in
        DB_PORT degrades instead of raising at import time.
        """
        from agent_app.config import get_env_int

        monkeypatch.delenv("X_PORT", raising=False)
        assert get_env_int("X_PORT") is None
        monkeypatch.setenv("X_PORT", "not-a-number")
        assert get_env_int("X_PORT") is None


class TestAgentCoreRuntime:
    """
    Inside AgentCore the one secret, the Snowflake key, comes from SSM, and
    only when the runtime names the parameter (the MCP runtime does, the agent
    does not).
    """

    class FakeSsm:
        def __init__(self):
            self.calls = []

        def get_parameter(self, Name, WithDecryption):
            self.calls.append((Name, WithDecryption))
            return {"Parameter": {"Value": "-----BEGIN PRIVATE KEY-----acme"}}

    def test_the_key_is_read_from_ssm_decrypted(self, monkeypatch):
        from agent_app.config import SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR

        from agent_app.config import ANTHROPIC_API_KEY_SSM_PARAM_VAR

        monkeypatch.setenv(SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR, "/acme/snowflake-key")
        monkeypatch.delenv(ANTHROPIC_API_KEY_SSM_PARAM_VAR, raising=False)
        monkeypatch.delenv("SNOWFLAKE_PRIVATE_KEY", raising=False)
        ssm = self.FakeSsm()
        config = Config.new_in_agentcore_runtime(ssm_client=ssm)
        assert ssm.calls == [("/acme/snowflake-key", True)]
        assert config.snowflake_private_key_pem.endswith("acme")

    def test_no_parameter_means_no_ssm_call(self, monkeypatch):
        from agent_app.config import ANTHROPIC_API_KEY_SSM_PARAM_VAR, SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR

        monkeypatch.delenv(SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR, raising=False)
        monkeypatch.delenv(ANTHROPIC_API_KEY_SSM_PARAM_VAR, raising=False)
        ssm = self.FakeSsm()
        Config.new_in_agentcore_runtime(ssm_client=ssm)
        assert ssm.calls == []

    def test_the_anthropic_key_is_read_from_its_own_parameter(self, monkeypatch):
        from agent_app.config import ANTHROPIC_API_KEY_SSM_PARAM_VAR, SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR

        monkeypatch.setenv(ANTHROPIC_API_KEY_SSM_PARAM_VAR, "/acme/anthropic-key")
        monkeypatch.delenv(SNOWFLAKE_PRIVATE_KEY_SSM_PARAM_VAR, raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        ssm = self.FakeSsm()
        config = Config.new_in_agentcore_runtime(ssm_client=ssm)
        assert ssm.calls == [("/acme/anthropic-key", True)]
        assert config.anthropic_api_key.endswith("acme")

    def test_a_value_set_directly_wins(self, monkeypatch):
        from agent_app.config import ANTHROPIC_API_KEY_SSM_PARAM_VAR

        monkeypatch.setenv(ANTHROPIC_API_KEY_SSM_PARAM_VAR, "/acme/anthropic-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "direct")
        ssm = self.FakeSsm()
        assert Config.new_in_agentcore_runtime(ssm_client=ssm).anthropic_api_key == "direct"
        assert ("/acme/anthropic-key", True) not in ssm.calls

    def test_the_per_user_cap_is_read(self, monkeypatch):
        monkeypatch.setenv("QUOTA_MAX_INVOKE_PER_USER_PER_MONTH", "7")
        assert Config.new_from_env_var().quota_max_invoke_per_user_per_month == 7
