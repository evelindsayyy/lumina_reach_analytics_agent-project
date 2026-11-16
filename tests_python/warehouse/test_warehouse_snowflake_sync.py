# -*- coding: utf-8 -*-

"""
The parts of the Snowflake sync that need no account. Fictional fixtures.
"""

import dataclasses
import stat

import pytest

from agent_app.warehouse import snowflake_sync as sync


class TestKeyPair:
    def test_a_missing_key_is_created_private(self, tmp_path):
        path = tmp_path / "keys" / "svc.pem"
        keys = sync.load_or_create_key_pair(path)
        assert keys.created
        assert path.read_text().startswith("-----BEGIN PRIVATE KEY-----")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert "-----" not in keys.public_key_body
        assert "\n" not in keys.public_key_body

    def test_an_existing_key_is_reused(self, tmp_path):
        """A re-sync must not invalidate the key a deployment already holds."""
        path = tmp_path / "svc.pem"
        first = sync.load_or_create_key_pair(path)
        second = sync.load_or_create_key_pair(path)
        assert not second.created
        assert second.public_key_body == first.public_key_body


class TestAdminKey:
    def test_the_alter_user_sets_the_public_key(self):
        assert sync.render_admin_key_sql("ME", "MIIBkey") == "ALTER USER ME SET RSA_PUBLIC_KEY = 'MIIBkey';"

    def test_a_missing_admin_key_names_the_command(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="wh-snowflake-admin-key"):
            sync.admin_private_key_der(tmp_path / "none.pem")

    def test_an_admin_key_loads_as_der(self, tmp_path):
        path = tmp_path / "admin.pem"
        sync.load_or_create_key_pair(path)
        assert sync.admin_private_key_der(path)[:1] == b"0"  # DER starts with a SEQUENCE


class TestCountDifferences:
    def test_equal_counts(self):
        assert sync.count_differences({"a": 2, "b": 3}, {"a": 2, "b": 3}) == []

    def test_a_short_or_missing_table_is_reported(self):
        assert sync.count_differences({"a": 2, "b": 3}, {"a": 1}) == [
            "a: DuckDB 2 rows, Snowflake 1",
            "b: DuckDB 3 rows, Snowflake 0",
        ]


@dataclasses.dataclass
class FakeConfig:
    snowflake_account: str | None = "acme-test"
    snowflake_user: str | None = "ACME_SVC"
    snowflake_role: str | None = "ACME_READER"
    snowflake_warehouse: str | None = "ACME_WH"
    snowflake_database: str | None = "ACME"


def env_of(values):
    def get_env(name):
        return values.get(name)

    def get_env_int(name):
        value = values.get(name)
        return None if value is None else int(value)

    return get_env, get_env_int


class TestSettingsFromEnv:
    def test_defaults(self):
        settings = sync.settings_from_env(FakeConfig(), *env_of({"SNOWFLAKE_ADMIN_USER": "ME"}))
        assert settings.admin_user == "ME"
        assert settings.objects.monitor == "ACME_WH_MONITOR"
        assert settings.credit_quota == sync.DEFAULT_CREDIT_QUOTA
        assert settings.path_private_key == sync.DEFAULT_PATH_PRIVATE_KEY

    def test_overrides(self, tmp_path):
        env = {
            "SNOWFLAKE_ADMIN_USER": "ME",
            "SNOWFLAKE_MONTHLY_CREDIT_QUOTA": "5",
            "SNOWFLAKE_PRIVATE_KEY_PATH": str(tmp_path / "k.pem"),
        }
        settings = sync.settings_from_env(FakeConfig(), *env_of(env))
        assert settings.credit_quota == 5
        assert settings.path_private_key == tmp_path / "k.pem"

    def test_every_missing_variable_is_named(self):
        config = FakeConfig(snowflake_account=None, snowflake_role="")
        with pytest.raises(ValueError) as e:
            sync.settings_from_env(config, *env_of({}))
        message = str(e.value)
        for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_ADMIN_USER", "SNOWFLAKE_ROLE"):
            assert name in message
        assert "SNOWFLAKE_USER" not in message
