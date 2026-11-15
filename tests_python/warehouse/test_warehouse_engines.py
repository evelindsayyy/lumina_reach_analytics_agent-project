# -*- coding: utf-8 -*-

"""
The engine adapters. Fictional fixtures (``acme``); no network: the Snowflake
engine is built but never connected.
"""

import duckdb
import pytest
import sqlalchemy as sa

from agent_app.warehouse import engines
from agent_app.warehouse.dialect import transpile_to_duckdb


def make_key_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def settings(**overrides) -> engines.SnowflakeSettings:
    values = dict(
        account="acme-test",
        user="ACME_SVC",
        role="ACME_READER",
        warehouse="ACME_WH",
        database="ACME",
        private_key_pem="",
    )
    values.update(overrides)
    return engines.SnowflakeSettings(**values)


class TestFindDuckdbFile:
    def test_the_single_file_is_found(self, tmp_path):
        (tmp_path / "acme_widgets.duckdb").touch()
        assert engines.find_duckdb_file(tmp_path).name == "acme_widgets.duckdb"

    def test_none_says_how_to_build_it(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="gen-data"):
            engines.find_duckdb_file(tmp_path)

    def test_two_are_refused(self, tmp_path):
        (tmp_path / "a.duckdb").touch()
        (tmp_path / "b.duckdb").touch()
        with pytest.raises(RuntimeError, match="a.duckdb, b.duckdb"):
            engines.find_duckdb_file(tmp_path)


class TestDuckdbEngine:
    @pytest.fixture
    def path(self, tmp_path):
        path = tmp_path / "acme_widgets.duckdb"
        connection = duckdb.connect(str(path))
        connection.execute("CREATE SCHEMA acme")
        connection.execute("CREATE TABLE acme.widget (widget_id INTEGER, cost DOUBLE)")
        connection.execute("INSERT INTO acme.widget VALUES (1, 2.5), (2, 4.0)")
        connection.close()
        return path

    def test_bare_names_resolve_to_the_schema(self, path):
        engine = engines.new_duckdb_engine(path, schema_name="acme")
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT SUM(cost) FROM widget")).scalar_one() == 6.5
        engine.dispose()

    def test_the_file_is_read_only(self, path):
        engine = engines.new_duckdb_engine(path, schema_name="acme")
        with engine.connect() as conn, pytest.raises(sa.exc.DBAPIError, match="read-only"):
            conn.execute(sa.text("DELETE FROM widget"))
        engine.dispose()


class TestSnowflakeEngine:
    def test_missing_settings_are_named(self):
        with pytest.raises(ValueError, match="SNOWFLAKE_ACCOUNT.*SNOWFLAKE_PRIVATE_KEY_PEM"):
            engines.new_snowflake_engine(settings(account=""), schema_name="acme")

    def test_builds_with_key_pair_and_no_password(self):
        engine = engines.new_snowflake_engine(settings(private_key_pem=make_key_pem()), schema_name="acme")
        assert engine.dialect.name == "snowflake"
        assert not engine.url.password
        assert engine.url.database.lower().startswith("acme")

    def test_the_key_never_appears_in_repr(self):
        assert "BEGIN" not in repr(settings(private_key_pem=make_key_pem()))

    def test_private_key_der_round_trips(self):
        assert engines.private_key_der(make_key_pem())[:1] == b"\x30"  # a DER SEQUENCE


def test_transpile_to_duckdb_rewrites_snowflake_functions():
    sql = transpile_to_duckdb("SELECT IFF(a > 0, 1, 0), DATEADD(day, -7, d) FROM t")
    assert "IFF" not in sql.upper()
    assert "INTERVAL" in sql.upper()


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.warehouse",
        is_folder=True,
        preview=False,
    )
