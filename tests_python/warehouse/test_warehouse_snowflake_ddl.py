# -*- coding: utf-8 -*-

"""
Reading the DuckDB catalog and rendering it as Snowflake DDL. Fictional
fixtures (``acme``); no network.
"""

import duckdb
import pytest
import sqlglot

from agent_app.warehouse import snowflake_ddl as ddl

SCHEMA = "acme"


@pytest.fixture
def duckdb_file(tmp_path):
    path = tmp_path / "acme_widgets.duckdb"
    con = duckdb.connect(str(path))
    con.execute(f"CREATE SCHEMA {SCHEMA}")
    con.execute(
        f"""
        CREATE TABLE {SCHEMA}.region (
            region_id BIGINT PRIMARY KEY,
            region_name VARCHAR NOT NULL
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE {SCHEMA}.orders (
            order_id BIGINT PRIMARY KEY,
            region_id BIGINT REFERENCES {SCHEMA}.region (region_id),
            amount DOUBLE,
            placed_at TIMESTAMP,
            placed_on DATE,
            is_test BOOLEAN,
            price DECIMAL(12, 2)
        )
        """
    )
    con.execute(f"INSERT INTO {SCHEMA}.region VALUES (1, 'North'), (2, 'South')")
    con.execute(
        f"""INSERT INTO {SCHEMA}.orders VALUES
        (10, 1, 9.5, '2026-01-01 10:00:00', '2026-01-01', false, 9.50)"""
    )
    con.execute(
        f"""CREATE VIEW {SCHEMA}.v_region_sales AS
        SELECT r.region_name, sum(o.amount) AS sales
        FROM {SCHEMA}.orders AS o JOIN {SCHEMA}.region AS r ON r.region_id = o.region_id
        GROUP BY r.region_name"""
    )
    con.close()
    return path


@pytest.fixture
def catalog(duckdb_file):
    con = duckdb.connect(str(duckdb_file), read_only=True)
    try:
        return ddl.read_catalog(con, SCHEMA)
    finally:
        con.close()


OBJECTS = ddl.SnowflakeObjects(
    database="ACME",
    warehouse="ACME_WH",
    role="ACME_READER",
    user="ACME_SVC",
    monitor="ACME_WH_MONITOR",
)


class TestReadCatalog:
    def test_tables_columns_and_keys(self, catalog):
        names = [t.name for t in catalog.tables]
        assert names == ["orders", "region"]
        orders = catalog.tables[0]
        assert [c.name for c in orders.columns][:3] == ["order_id", "region_id", "amount"]
        assert orders.primary_key == ("order_id",)
        assert orders.foreign_keys == (ddl.ForeignKey(("region_id",), "region", ("region_id",)),)
        region = catalog.tables[1]
        assert region.columns[1] == ddl.Column("region_name", "VARCHAR", nullable=False)

    def test_views(self, catalog):
        assert [v.name for v in catalog.views] == ["v_region_sales"]
        assert "sum" in catalog.views[0].sql.lower()

    def test_an_empty_schema_is_an_error(self, duckdb_file):
        con = duckdb.connect(str(duckdb_file), read_only=True)
        try:
            with pytest.raises(ValueError, match="no tables"):
                ddl.read_catalog(con, "nope")
        finally:
            con.close()


class TestReservedNames:
    def test_a_snowflake_reserved_word_is_refused(self, catalog):
        table = ddl.Table(name="order", columns=(ddl.Column("id", "BIGINT"),))
        with pytest.raises(ValueError, match="reserved"):
            ddl.render_table_ddl(table, SCHEMA)

    def test_a_reserved_column_is_refused(self):
        table = ddl.Table(name="sale", columns=(ddl.Column("group", "BIGINT"),))
        with pytest.raises(ValueError, match="'group'"):
            ddl.render_table_ddl(table, SCHEMA)


class TestSnowflakeType:
    @pytest.mark.parametrize(
        "duckdb_type, expected",
        [
            ("BIGINT", "NUMBER(38, 0)"),
            ("INTEGER", "NUMBER(38, 0)"),
            ("DOUBLE", "FLOAT"),
            ("VARCHAR", "VARCHAR"),
            ("TIMESTAMP", "TIMESTAMP_NTZ"),
            ("DATE", "DATE"),
            ("BOOLEAN", "BOOLEAN"),
            ("DECIMAL(12,2)", "NUMBER(12, 2)"),
        ],
    )
    def test_mapping(self, duckdb_type, expected):
        assert ddl.snowflake_type(duckdb_type) == expected

    def test_an_unknown_type_is_refused(self):
        with pytest.raises(ValueError, match="no Snowflake type"):
            ddl.snowflake_type("BLOB")


class TestRenderSchema:
    def test_every_statement_parses_as_snowflake(self, catalog):
        for statement in ddl.render_schema_sql(catalog, SCHEMA):
            sqlglot.parse_one(statement, read="snowflake")

    def test_the_schema_is_rebuilt_from_scratch(self, catalog):
        statements = ddl.render_schema_sql(catalog, SCHEMA)
        assert statements[0] == f"CREATE OR REPLACE SCHEMA {SCHEMA}"

    def test_tables_before_foreign_keys_before_views(self, catalog):
        statements = ddl.render_schema_sql(catalog, SCHEMA)
        kinds = [s.split()[0] + " " + s.split()[1] for s in statements[1:]]
        last_table = max(i for i, k in enumerate(kinds) if k == "CREATE TABLE")
        first_fk = kinds.index("ALTER TABLE")
        first_view = min(i for i, k in enumerate(kinds) if k == "CREATE OR")
        assert last_table < first_fk < first_view

    def test_table_ddl_keeps_types_nullability_and_primary_key(self, catalog):
        region = ddl.render_table_ddl(catalog.tables[1], SCHEMA)
        assert region == (
            f"CREATE TABLE {SCHEMA}.region (region_id NUMBER(38, 0) NOT NULL, "
            f"region_name VARCHAR NOT NULL, PRIMARY KEY (region_id))"
        )

    def test_foreign_keys_are_declared(self, catalog):
        assert ddl.render_foreign_keys(catalog.tables[0], SCHEMA) == [
            f"ALTER TABLE {SCHEMA}.orders ADD FOREIGN KEY (region_id) REFERENCES {SCHEMA}.region (region_id)"
        ]

    def test_views_are_transpiled_and_unquoted(self, catalog):
        view = ddl.render_view_ddl(catalog.views[0].sql)
        assert view.startswith(f"CREATE OR REPLACE VIEW {SCHEMA}.v_region_sales AS")
        # a quoted lowercase name is case-sensitive in Snowflake and would miss
        # the unquoted (so uppercased) table
        assert '"' not in view


class TestRenderAccountSql:
    def statements(self, quota=2):
        return ddl.render_account_sql(OBJECTS, SCHEMA, public_key_body="MIIBkey", credit_quota=quota)

    def test_every_statement_parses_as_snowflake(self):
        for statement in self.statements():
            if statement.startswith(("CREATE RESOURCE MONITOR", "ALTER RESOURCE MONITOR")):
                continue  # sqlglot has no grammar for resource monitors
            sqlglot.parse_one(statement, read="snowflake")

    def test_cost_guardrails(self):
        text = "\n".join(self.statements(quota=3))
        assert "WAREHOUSE_SIZE = XSMALL" in text
        assert "AUTO_SUSPEND = 60" in text
        assert "STATEMENT_TIMEOUT_IN_SECONDS = 60" in text
        assert "CREDIT_QUOTA = 3" in text
        assert "ON 100 PERCENT DO SUSPEND" in text
        assert f"ALTER WAREHOUSE {OBJECTS.warehouse} SET RESOURCE_MONITOR = {OBJECTS.monitor}" in text

    def test_the_role_can_only_read(self):
        statements = self.statements() + ddl.render_read_grants(OBJECTS, SCHEMA)
        grants = [s for s in statements if s.startswith("GRANT") and "ROLE ACME_READER" in s]
        privileges = {s.split()[1] for s in grants if " ON " in s}
        assert privileges == {"USAGE", "SELECT"}

    def test_the_service_user_has_a_key_and_no_password(self):
        text = "\n".join(self.statements())
        assert "TYPE = SERVICE" in text
        assert "RSA_PUBLIC_KEY = 'MIIBkey'" in text
        assert "PASSWORD" not in text

    def test_each_step_runs_as_the_least_role_that_can(self):
        roles = [s.split()[-1] for s in self.statements() if s.startswith("USE ROLE")]
        assert roles == ["SYSADMIN", "ACCOUNTADMIN", "SYSADMIN", "SECURITYADMIN"]

    @pytest.mark.parametrize("quota", [0, -1])
    def test_the_quota_must_be_positive(self, quota):
        with pytest.raises(ValueError, match="credit quota"):
            self.statements(quota=quota)


class TestRenderGrants:
    def test_select_on_what_exists_after_the_build(self):
        assert ddl.render_read_grants(OBJECTS, SCHEMA) == [
            "USE ROLE SECURITYADMIN",
            f"GRANT USAGE ON SCHEMA ACME.{SCHEMA} TO ROLE ACME_READER",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA ACME.{SCHEMA} TO ROLE ACME_READER",
            f"GRANT SELECT ON ALL VIEWS IN SCHEMA ACME.{SCHEMA} TO ROLE ACME_READER",
        ]


class TestRenderLoad:
    def test_put_then_copy(self, tmp_path):
        path = tmp_path / "region.parquet"
        put, copy = ddl.render_load_sql(path, SCHEMA, "region")
        assert put == f"PUT 'file://{path.as_posix()}' @{SCHEMA}.%region OVERWRITE = TRUE"
        assert copy.startswith(f"COPY INTO {SCHEMA}.region FROM @{SCHEMA}.%region")
        assert "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE" in copy

    def test_parquet_export_writes_one_file_per_table(self, duckdb_file, catalog, tmp_path):
        con = duckdb.connect(str(duckdb_file), read_only=True)
        try:
            paths = ddl.export_parquet(con, catalog, SCHEMA, tmp_path / "out")
            assert [p.stem for p in paths] == ["orders", "region"]
            assert con.execute(f"SELECT count(*) FROM '{paths[1]}'").fetchone()[0] == 2
        finally:
            con.close()
