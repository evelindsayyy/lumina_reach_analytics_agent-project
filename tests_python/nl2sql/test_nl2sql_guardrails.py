# -*- coding: utf-8 -*-

"""
The SQL guardrails, against a fictional ``acme`` dataset.

Every fixture is made up (widgets, plants, resellers) so that a dataset swap
never turns these tests into a description of a domain that no longer exists:
the guardrails are generic, and so are their tests.

- ``widget_stats`` carries the *stats* source of sales (``sales``,
  ``sales_value``) and a share column (``shelf_share``).
- ``order_event`` is the *events* source: every column of it counts.
- ``reseller_report`` is the *reseller* source (``sales``).
- ``plant.manager_email`` is sensitive.
"""

import pytest
import sqlalchemy as sa

from agent_app.nl2sql.guardrails import DEFAULT_LIMIT
from agent_app.nl2sql.guardrails import GuardrailError
from agent_app.nl2sql.guardrails import load_policy
from agent_app.nl2sql.guardrails import reflect_table_columns
from agent_app.nl2sql.guardrails import validate_sql

TABLE_COLUMNS = {
    "plant": frozenset({"plant_id", "plant_name", "manager_email"}),
    "widget": frozenset({"widget_id", "plant_id", "widget_name", "status"}),
    "widget_stats": frozenset({"report_date", "widget_id", "cost", "impressions", "sales", "sales_value", "shelf_share"}),
    "order_event": frozenset({"order_id", "widget_id", "order_time", "order_value"}),
    "reseller_report": frozenset({"report_date", "widget_id", "sales"}),
    "v_reference_date": frozenset({"reference_date"}),
}

POLICY_TOML = """
[sensitive]
columns = ["plant.manager_email"]

[ratios]
share_columns = ["shelf_share"]

[[conversion_source]]
name = "stats"
label = "widget stats"
tables = { widget_stats = ["sales", "sales_value"] }

[[conversion_source]]
name = "events"
label = "order events"
tables = { order_event = [] }

[[conversion_source]]
name = "reseller"
label = "reseller report"
tables = { reseller_report = ["sales"] }
"""


@pytest.fixture(scope="module")
def policy(tmp_path_factory):
    path = tmp_path_factory.mktemp("policy") / "sql-policy.toml"
    path.write_text(POLICY_TOML, encoding="utf-8")
    return load_policy(path, schema_name="acme", table_columns=TABLE_COLUMNS)


def code_of(sql, policy):
    with pytest.raises(GuardrailError) as info:
        validate_sql(sql, policy)
    return info.value.code


class TestPasses:
    def test_simple_select_gets_a_limit(self, policy):
        result = validate_sql("SELECT widget_name FROM widget", policy)
        assert result.sql.endswith(f"LIMIT {DEFAULT_LIMIT}")
        assert result.tables == ["widget"]
        assert result.conversion_source is None

    def test_own_limit_kept(self, policy):
        result = validate_sql("SELECT widget_name FROM widget LIMIT 5", policy)
        assert result.sql.endswith("LIMIT 5")
        assert result.rewrites == []

    def test_joins_aliases_ctes_and_schema_prefix(self, policy):
        sql = """
            WITH top AS (SELECT s.widget_id, SUM(s.cost) AS spend FROM acme.widget_stats s GROUP BY s.widget_id)
            SELECT w.widget_name, p.plant_name, t.spend
            FROM top t JOIN widget w ON w.widget_id = t.widget_id
            JOIN plant p ON p.plant_id = w.plant_id
            ORDER BY t.spend DESC
        """
        result = validate_sql(sql, policy)
        assert result.tables == ["plant", "widget", "widget_stats"]

    def test_clock_rewritten_to_reference_date(self, policy):
        result = validate_sql("SELECT SUM(cost) FROM widget_stats WHERE report_date > DATEADD(day, -7, CURRENT_DATE)", policy)
        assert "CURRENT_DATE" not in result.sql
        assert "v_reference_date" in result.sql
        assert any("reference date" in r for r in result.rewrites)

    def test_one_source_is_reported(self, policy):
        result = validate_sql("SELECT SUM(sales) / NULLIF(SUM(cost), 0) FROM widget_stats", policy)
        assert result.conversion_source == "stats"

    def test_an_event_table_is_its_source_whatever_columns_are_read(self, policy):
        result = validate_sql("SELECT COUNT(*) FROM order_event", policy)
        assert result.conversion_source == "events"

    def test_cost_only_join_is_not_a_mix(self, policy):
        """Joining two source tables is fine when only one carries conversions."""
        sql = "SELECT SUM(s.cost), COUNT(r.sales) FROM widget_stats s JOIN reseller_report r ON r.widget_id = s.widget_id"
        assert validate_sql(sql, policy).conversion_source == "reseller"

    def test_count_star_on_sensitive_table_passes(self, policy):
        """COUNT(*) reads no column, so it exposes nothing."""
        validate_sql("SELECT COUNT(*) FROM plant", policy)

    def test_weighted_share_and_avg_of_plain_column_pass(self, policy):
        validate_sql("SELECT SUM(shelf_share * impressions) / SUM(impressions) FROM widget_stats", policy)
        validate_sql("SELECT AVG(cost) FROM widget_stats", policy)

    def test_select_alias_in_order_by(self, policy):
        validate_sql("SELECT SUM(cost) AS spend FROM widget_stats ORDER BY spend DESC", policy)


class TestRejects:
    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM widget",
            "UPDATE widget SET status = 'Paused'",
            "INSERT INTO widget SELECT * FROM widget",
            "DROP TABLE widget",
            "CREATE TABLE x AS SELECT 1",
            "ALTER TABLE widget ADD COLUMN x INT",
            "MERGE INTO widget USING widget w2 ON 1 = 1 WHEN MATCHED THEN DELETE",
            "COPY INTO widget FROM @stage",
            "GRANT SELECT ON widget TO ROLE public",
            "TRUNCATE TABLE widget",
            "USE ROLE accountadmin",
            "CALL some_procedure()",
            "SELECT SYSTEM$WHITELIST()",
        ],
    )
    def test_not_select(self, sql, policy):
        assert code_of(sql, policy) == "NOT_SELECT"

    def test_multi_statement(self, policy):
        assert code_of("SELECT 1; DROP TABLE widget", policy) == "MULTI_STATEMENT"

    def test_parse_error(self, policy):
        assert code_of("SELEC cost FRM widget_stats", policy) == "PARSE_ERROR"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM raw.widget_stats",
            "SELECT * FROM information_schema.tables",
            "SELECT * FROM other_db.acme.widget",
            "SELECT * FROM users",
        ],
    )
    def test_unknown_table(self, sql, policy):
        assert code_of(sql, policy) == "UNKNOWN_TABLE"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT revenue FROM widget_stats",
            "SELECT s.revenue FROM widget_stats s",
            "SELECT x.cost FROM widget_stats s",
        ],
    )
    def test_unknown_column(self, sql, policy):
        assert code_of(sql, policy) == "UNKNOWN_COLUMN"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT plant_name, manager_email FROM plant",
            "SELECT p.manager_email FROM plant p",
            "SELECT * FROM plant",
            "SELECT p.* FROM plant p",
        ],
    )
    def test_sensitive_column(self, sql, policy):
        assert code_of(sql, policy) == "SENSITIVE_COLUMN"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT SUM(s.sales) + SUM(o.order_value) FROM widget_stats s, order_event o",
            "SELECT SUM(s.sales), SUM(r.sales) FROM widget_stats s JOIN reseller_report r ON r.widget_id = s.widget_id",
            "SELECT (SELECT SUM(sales) FROM widget_stats) + (SELECT COUNT(*) FROM order_event)",
        ],
    )
    def test_conversion_mix(self, sql, policy):
        assert code_of(sql, policy) == "CONVERSION_MIX"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT AVG(cost / sales) FROM widget_stats",
            "SELECT AVG(shelf_share) FROM widget_stats",
            "SELECT AVG(s.shelf_share) FROM widget_stats s",
        ],
    )
    def test_ratio_avg(self, sql, policy):
        assert code_of(sql, policy) == "RATIO_AVG"

    def test_error_message_is_actionable(self, policy):
        with pytest.raises(GuardrailError) as info:
            validate_sql("SELECT revenue FROM widget_stats", policy)
        assert "widget_stats" in info.value.message
        assert str(info.value).startswith("UNKNOWN_COLUMN: ")

    def test_mix_message_names_both_sources(self, policy):
        with pytest.raises(GuardrailError) as info:
            validate_sql("SELECT SUM(s.sales) + SUM(o.order_value) FROM widget_stats s, order_event o", policy)
        assert "widget stats" in info.value.message
        assert "order events" in info.value.message


class TestLoadPolicy:
    def write(self, tmp_path, text):
        path = tmp_path / "sql-policy.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_misspelled_sensitive_column_fails_loudly(self, tmp_path):
        """A typo must not silently switch the rule off."""
        path = self.write(tmp_path, '[sensitive]\ncolumns = ["plant.manager_emial"]\n')
        with pytest.raises(ValueError, match="manager_emial"):
            load_policy(path, schema_name="acme", table_columns=TABLE_COLUMNS)

    def test_an_unknown_source_table_fails(self, tmp_path):
        path = self.write(tmp_path, '[[conversion_source]]\nname = "x"\nlabel = "x"\ntables = { nope = [] }\n')
        with pytest.raises(ValueError, match="nope"):
            load_policy(path, schema_name="acme", table_columns=TABLE_COLUMNS)

    def test_an_unknown_source_column_fails(self, tmp_path):
        path = self.write(tmp_path, '[[conversion_source]]\nname = "x"\nlabel = "x"\ntables = { widget_stats = ["profit"] }\n')
        with pytest.raises(ValueError, match="profit"):
            load_policy(path, schema_name="acme", table_columns=TABLE_COLUMNS)

    def test_an_empty_file_is_a_policy_with_no_rules(self, tmp_path):
        policy = load_policy(self.write(tmp_path, ""), schema_name="ACME", table_columns=TABLE_COLUMNS)
        assert policy.schema_name == "acme"
        assert policy.sensitive_columns == {}
        validate_sql("SELECT * FROM plant", policy)


def test_reflect_table_columns_lower_cases_tables_and_views():
    metadata = sa.MetaData(schema="acme")
    sa.Table("Widget", metadata, sa.Column("Widget_ID", sa.Integer), sa.Column("Cost", sa.Float))
    assert reflect_table_columns(metadata) == {"widget": frozenset({"widget_id", "cost"})}


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.nl2sql.guardrails",
        preview=False,
    )
