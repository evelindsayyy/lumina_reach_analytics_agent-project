# -*- coding: utf-8 -*-

"""
The DB mixin against the real local warehouse file (``mise run gen-data``).

These read the generated dataset on purpose: what is under test is the wiring
of reflection, the guardrail policy built from it, Snowflake-to-DuckDB
transpiling, and the rolled-back execution, end to end on one engine.
"""

import pytest

from agent_app.constants import DbTypeEnum
from agent_app.one.one_00_main import one


class TestEngine:
    def test_default_engine_is_the_read_only_duckdb_file(self):
        assert one.engine.dialect.name == "duckdb"
        assert one.db_type is DbTypeEnum.DUCKDB

    def test_views_are_reflected(self):
        """The reference-date view is part of what the agent may query."""
        names = {table.name for table in one.reflected_metadata.tables.values()}
        assert "v_reference_date" in names
        assert "mv_attribution_six_models" in names

    def test_schema_str_is_labelled_duckdb(self):
        assert one.database_schema_str.startswith("duckdb Database")


class TestGuardrailPolicy:
    def test_built_from_reflection_and_the_policy_file(self):
        policy = one.guardrail_policy
        assert "daily_stats" in policy.table_columns
        assert "contact_email" in policy.sensitive_columns["agency"]
        assert policy.conversion_source_of_table["daily_stats"] == "daily_stats"


class TestDuckdbFileName:
    def test_a_file_named_like_the_schema_is_refused(self, tmp_path):
        """
        DuckDB names the catalog after the file, so ``acme.duckdb`` holding
        schema ``acme`` makes every ``acme`` reference ambiguous.
        """
        from agent_app.warehouse.engines import new_duckdb_engine

        with pytest.raises(ValueError, match="ambiguous"):
            new_duckdb_engine(tmp_path / "acme.duckdb", schema_name="acme")


class TestExecuteSqlQuery:
    def test_snowflake_sql_runs_on_duckdb(self):
        """DATEADD and CURRENT_DATE are Snowflake; they run after transpiling."""
        result = one.execute_sql_query(
            "SELECT COUNT(*) AS n FROM daily_stats "
            "WHERE report_date > DATEADD(day, -7, CURRENT_DATE)"
        )
        assert result.startswith("| ")
        assert "CURRENT_DATE -> the reference date" in result

    def test_the_conversion_source_is_named(self):
        result = one.execute_sql_query("SELECT SUM(conversions) AS c FROM daily_stats")
        assert "conversions are from engine aggregate" in result

    @pytest.mark.parametrize(
        "sql, code",
        [
            ("DELETE FROM campaign", "NOT_SELECT"),
            ("SELECT contact_email FROM agency", "SENSITIVE_COLUMN"),
            ("SELECT * FROM agency", "SENSITIVE_COLUMN"),
            ("SELECT roas_target FROM campaign", "UNKNOWN_COLUMN"),
            ("SELECT * FROM information_schema.tables", "UNKNOWN_TABLE"),
            ("SELECT AVG(search_impression_share) FROM daily_stats", "RATIO_AVG"),
            (
                (
                    "SELECT (SELECT SUM(conversions) FROM daily_stats) AS engine_conv, "
                    "(SELECT COUNT(*) FROM conversion) AS floodlight_conv"
                ),
                "CONVERSION_MIX",
            ),
        ],
    )
    def test_guardrails_reject_with_a_code(self, sql, code):
        result = one.execute_sql_query(sql)
        assert result.startswith("Error: rejected by the SQL guardrails.")
        assert code in result

    def test_an_engine_error_is_text_not_a_raise(self):
        result = one.execute_sql_query("SELECT CAST('x' AS INT) AS n FROM campaign")
        assert result.startswith("Error executing query")


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.one.one_02_db",
        preview=False,
    )
