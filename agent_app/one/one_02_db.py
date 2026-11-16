# -*- coding: utf-8 -*-

"""Database mixin for the One class."""

import typing as T
from functools import cached_property

import sqlalchemy as sa

from ..constants import DbTypeEnum, WarehouseEngineEnum
from ..db_schema.api import new_schema_info
from ..db_schema.api import new_database_info
from ..db_schema.api import encode_database_info
from ..db_schema.snapshot import SchemaSnapshot
from ..db_schema.snapshot import load_snapshot
from ..nl2sql.guardrails import GuardrailError
from ..nl2sql.guardrails import GuardrailPolicy
from ..nl2sql.guardrails import load_policy
from ..nl2sql.guardrails import reflect_table_columns
from ..nl2sql.guardrails import validate_sql
from ..paths import path_enum
from ..sql_utils import execute_sql_query
from ..warehouse.dialect import transpile_to_duckdb
from ..warehouse.engines import SnowflakeSettings
from ..warehouse.engines import find_duckdb_file
from ..warehouse.engines import new_duckdb_engine
from ..warehouse.engines import new_snowflake_engine

if T.TYPE_CHECKING:  # pragma: no cover
    from .one_00_main import One


class DbMixin:
    """Mixin providing database connection and query execution capabilities."""

    @cached_property
    def engine(self: "One") -> sa.Engine:
        """
        The engine everything is served from, chosen by ``WAREHOUSE_ENGINE``:
        the local DuckDB file, or the Snowflake schema.

        Either way, scoped to ``SCHEMA_NAME``: the agent writes
        ``FROM campaign`` and never names the schema.
        """
        config = self.config
        if config.warehouse_engine == WarehouseEngineEnum.SNOWFLAKE.value:
            settings = SnowflakeSettings(
                account=config.snowflake_account or "",
                user=config.snowflake_user or "",
                role=config.snowflake_role or "",
                warehouse=config.snowflake_warehouse or "",
                database=config.snowflake_database or "",
                private_key_pem=config.snowflake_private_key_pem or "",
            )
            return new_snowflake_engine(settings, schema_name=config.schema_name)
        path = config.duckdb_path or find_duckdb_file()
        return new_duckdb_engine(path, schema_name=config.schema_name)

    @property
    def db_type(self: "One") -> DbTypeEnum:
        """The engine behind :attr:`engine`, as the schema encoder labels it."""
        return DbTypeEnum.get_by_value(self.config.warehouse_engine)

    @cached_property
    def reflected_metadata(self: "One") -> sa.MetaData:
        """
        Every table **and view** of the schema, reflected once per process.

        Views are included on purpose: the reference-date view and the
        attribution view are part of what the agent may query, so both the
        schema it is shown and the guardrail allowlist must contain them.

        The schema goes on the MetaData, not only on reflect(): the encoder
        labels the block with ``metadata.schema``.
        """
        metadata = sa.MetaData(schema=self.config.schema_name)
        metadata.reflect(bind=self.engine, schema=self.config.schema_name, views=True)
        if not metadata.tables:  # pragma: no cover - needs an empty warehouse
            raise RuntimeError(
                f"Schema {self.config.schema_name!r} has no tables. An absent "
                f"schema and an empty one look identical to the reflector, so "
                f"this is almost certainly a warehouse that was never built. "
                f"Locally, build it with `mise run gen-data`."
            )
        return metadata

    @cached_property
    def schema_snapshot(self: "One") -> SchemaSnapshot | None:
        """
        The build-time snapshot a deployed MCP runtime ships with, when it is
        one of this schema on this engine. None locally: there is no file.
        """
        return load_snapshot(
            path_enum.path_schema_snapshot_json,
            schema_name=self.config.schema_name,
            warehouse_engine=self.config.warehouse_engine,
        )

    @cached_property
    def database_schema_str(self: "One") -> str:
        """
        The database schema, encoded in the compact format the agent reads:
        from the shipped snapshot if there is one, else reflected live.
        """
        snapshot = self.schema_snapshot
        return snapshot.schema_str if snapshot else self.encode_reflected_schema()

    def new_schema_snapshot(self: "One") -> SchemaSnapshot:
        """
        A snapshot of the live schema, ignoring any shipped one: what
        ``agent-app ac-gen`` ships with the MCP runtime.
        """
        return SchemaSnapshot(
            schema_name=self.config.schema_name,
            warehouse_engine=self.config.warehouse_engine,
            schema_str=self.encode_reflected_schema(),
            table_columns=reflect_table_columns(self.reflected_metadata),
        )

    def encode_reflected_schema(self: "One") -> str:
        """The live schema, reflected and encoded (about 30 s on a cold Snowflake)."""
        schema_info = new_schema_info(
            engine=self.engine,
            metadata=self.reflected_metadata,
            schema_name=self.config.schema_name,
        )
        database_info = new_database_info(
            name=self.config.schema_name,
            db_type=self.db_type,
            schemas=[schema_info],
        )
        return encode_database_info(database_info=database_info)

    @cached_property
    def guardrail_policy(self: "One") -> GuardrailPolicy:
        """
        What the SQL guardrails allow: the tables and columns (from the shipped
        snapshot if there is one, else reflected), plus the dataset's rules in
        ``data/sql-policy.toml``.
        """
        snapshot = self.schema_snapshot
        table_columns = snapshot.table_columns if snapshot else reflect_table_columns(self.reflected_metadata)
        return load_policy(
            path_toml=path_enum.path_sql_policy_toml,
            schema_name=self.config.schema_name,
            table_columns=table_columns,
        )

    def execute_sql_query(self: "One", sql: str) -> str:
        """
        Run the agent's SQL and return the result as a Markdown table.

        Three steps, every failure returned as text for the model to fix:

        1. the guardrails (Snowflake dialect) refuse or rewrite it;
        2. on DuckDB, the validated SQL is transpiled;
        3. it runs in a transaction that is always rolled back.
        """
        try:
            validated = validate_sql(sql, self.guardrail_policy)
        except GuardrailError as e:
            return f"Error: rejected by the SQL guardrails. {e}"
        runnable = validated.sql
        if self.config.warehouse_engine == WarehouseEngineEnum.DUCKDB.value:
            runnable = transpile_to_duckdb(runnable)
        result = execute_sql_query(engine=self.engine, sql=runnable)
        notes = []
        # the LIMIT it adds is not worth the model's attention; the date is
        clock_rewrites = [r for r in validated.rewrites if not r.startswith("LIMIT")]
        if clock_rewrites:
            notes.append("rewritten: " + "; ".join(clock_rewrites))
        if validated.conversion_source:
            label = self.guardrail_policy.conversion_source_labels.get(
                validated.conversion_source, validated.conversion_source
            )
            notes.append(f"conversions are from {label}")
        if not notes or result.startswith("Error"):
            return result
        return result + "\n\n(" + "; ".join(notes) + ")"
