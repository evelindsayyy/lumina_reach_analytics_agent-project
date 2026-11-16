# -*- coding: utf-8 -*-

"""
The Snowflake copy of the local warehouse, as SQL text.

The DuckDB file that ``mise run gen-data`` builds is the one source of truth:
:func:`read_catalog` reads its tables, keys and views, and the ``render_*``
functions turn them into Snowflake statements. The generator never learns that
Snowflake exists, so a dataset swap changes nothing here.

Everything in this module is pure (strings in, strings out) so it is tested
without an account; :mod:`.snowflake_sync` runs the statements.

Identifiers are written unquoted. Snowflake uppercases those, the
``snowflake-sqlalchemy`` dialect lowercases them back, and the agent's
unquoted ``FROM campaign`` resolves -- the same SQL as on DuckDB. A name that
Snowflake reserves would need quoting everywhere, so it is refused here, at
build time, rather than discovered by the agent at query time.
"""

import dataclasses
import re
from pathlib import Path

import sqlglot
from sqlglot import exp

#: Snowflake's reserved keywords (its "Reserved & limited keywords" page): a
#: table or column with one of these names cannot be written unquoted.
SNOWFLAKE_RESERVED = frozenset(
    """
    ACCOUNT ALL ALTER AND ANY AS BETWEEN BY CASE CAST CHECK COLUMN CONNECT
    CONNECTION CONSTRAINT CREATE CROSS CURRENT CURRENT_DATE CURRENT_TIME
    CURRENT_TIMESTAMP CURRENT_USER DATABASE DELETE DISTINCT DROP ELSE EXISTS
    FALSE FOLLOWING FOR FROM FULL GRANT GROUP GSCLUSTER HAVING ILIKE IN
    INCREMENT INNER INSERT INTERSECT INTO IS ISSUE JOIN LATERAL LEFT LIKE
    LOCALTIME LOCALTIMESTAMP MINUS NATURAL NOT NULL OF ON OR ORDER ORGANIZATION
    QUALIFY REGEXP REVOKE RIGHT RLIKE ROW ROWS SAMPLE SCHEMA SELECT SET SOME
    START TABLE TABLESAMPLE THEN TO TRIGGER TRUE TRY_CAST UNION UNIQUE UPDATE
    USING VALUES VIEW WHEN WHENEVER WHERE WINDOW WITH
    """.split()
)

#: DuckDB column type -> Snowflake column type. Integers become NUMBER(38, 0),
#: Snowflake's only integer, so ids compare and join the same way.
TYPE_MAP = {
    "BIGINT": "NUMBER(38, 0)",
    "INTEGER": "NUMBER(38, 0)",
    "SMALLINT": "NUMBER(38, 0)",
    "TINYINT": "NUMBER(38, 0)",
    "HUGEINT": "NUMBER(38, 0)",
    "DOUBLE": "FLOAT",
    "FLOAT": "FLOAT",
    "REAL": "FLOAT",
    "VARCHAR": "VARCHAR",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP_NTZ",
}

DECIMAL_PATTERN = re.compile(r"^DECIMAL\((\d+),\s*(\d+)\)$")


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str  #: As DuckDB reports it, e.g. ``BIGINT`` or ``DECIMAL(12,2)``.
    nullable: bool = True


@dataclasses.dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()


@dataclasses.dataclass(frozen=True)
class View:
    name: str
    sql: str  #: The ``CREATE VIEW`` statement, in DuckDB's dialect.


@dataclasses.dataclass(frozen=True)
class Catalog:
    tables: tuple[Table, ...]
    views: tuple[View, ...]


@dataclasses.dataclass(frozen=True)
class SnowflakeObjects:
    """
    The account-level objects the deployment uses, by name.
    """

    database: str
    warehouse: str
    role: str  #: The agent's read-only role.
    user: str  #: The agent's service user.
    monitor: str  #: The resource monitor capping the warehouse's credits.


def read_catalog(con, schema: str) -> Catalog:
    """
    The tables (with keys) and views of ``schema`` in the open DuckDB
    connection ``con``, tables and views each sorted by name.

    :raises ValueError: the schema has no tables, which is what reading the
        wrong file or the wrong schema name looks like.
    """
    rows = con.execute(
        """
        SELECT c.table_name, c.column_name, c.data_type, c.is_nullable
        FROM information_schema.columns AS c
        JOIN information_schema.tables AS t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = ? AND t.table_type = 'BASE TABLE'
        ORDER BY c.table_name, c.ordinal_position
        """,
        [schema],
    ).fetchall()
    if not rows:
        raise ValueError(f"DuckDB schema {schema!r} has no tables. Is SCHEMA_NAME right, and was `mise run gen-data` run?")
    columns: dict[str, list[Column]] = {}
    for table_name, column_name, data_type, is_nullable in rows:
        columns.setdefault(table_name, []).append(Column(column_name, data_type, nullable=is_nullable == "YES"))

    constraints = con.execute(
        """
        SELECT table_name, constraint_type, constraint_column_names,
               referenced_table, referenced_column_names
        FROM duckdb_constraints()
        WHERE schema_name = ? AND constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
        ORDER BY table_name, constraint_index
        """,
        [schema],
    ).fetchall()
    primary_keys: dict[str, tuple[str, ...]] = {}
    foreign_keys: dict[str, list[ForeignKey]] = {}
    for table_name, kind, cols, ref_table, ref_cols in constraints:
        if kind == "PRIMARY KEY":
            primary_keys[table_name] = tuple(cols)
        else:
            foreign_keys.setdefault(table_name, []).append(ForeignKey(tuple(cols), ref_table, tuple(ref_cols)))

    tables = tuple(
        Table(
            name=name,
            columns=tuple(cols),
            primary_key=primary_keys.get(name, ()),
            foreign_keys=tuple(foreign_keys.get(name, ())),
        )
        for name, cols in sorted(columns.items())
    )
    views = tuple(
        View(name, sql)
        for name, sql in con.execute(
            "SELECT view_name, sql FROM duckdb_views() WHERE schema_name = ? ORDER BY view_name",
            [schema],
        ).fetchall()
    )
    return Catalog(tables=tables, views=views)


def snowflake_type(duckdb_type: str) -> str:
    """
    The Snowflake column type for a DuckDB one.

    :raises ValueError: a type with no mapping, so a new column type in the
        generator fails the sync instead of loading as something else.
    """
    normalized = duckdb_type.strip().upper()
    match = DECIMAL_PATTERN.match(normalized)
    if match:
        return f"NUMBER({match.group(1)}, {match.group(2)})"
    try:
        return TYPE_MAP[normalized]
    except KeyError:
        raise ValueError(f"DuckDB type {duckdb_type!r} has no Snowflake type in TYPE_MAP")


def checked_name(name: str, what: str) -> str:
    """
    ``name``, if Snowflake accepts it unquoted.

    :raises ValueError: it is a reserved word; rename it in the generator.
    """
    if name.upper() in SNOWFLAKE_RESERVED:
        raise ValueError(f"{what} {name!r} is reserved in Snowflake; rename it in the dataset's generator")
    return name


def render_table_ddl(table: Table, schema: str) -> str:
    """
    ``CREATE TABLE`` for ``table``, with its types, ``NOT NULL`` and primary
    key. Snowflake does not enforce keys, but it records them, and schema
    reflection shows them to the agent exactly as DuckDB's do.
    """
    checked_name(table.name, "Table")
    parts = [
        f"{checked_name(c.name, 'Column')} {snowflake_type(c.type)}{'' if c.nullable else ' NOT NULL'}"
        for c in table.columns
    ]
    if table.primary_key:
        parts.append(f"PRIMARY KEY ({', '.join(table.primary_key)})")
    return f"CREATE TABLE {schema}.{table.name} ({', '.join(parts)})"


def render_foreign_keys(table: Table, schema: str) -> list[str]:
    """
    One ``ALTER TABLE ... ADD FOREIGN KEY`` per foreign key of ``table``. Run
    after every table exists, so declaration order never matters.
    """
    return [
        f"ALTER TABLE {schema}.{table.name} ADD FOREIGN KEY ({', '.join(fk.columns)}) "
        f"REFERENCES {schema}.{fk.ref_table} ({', '.join(fk.ref_columns)})"
        for fk in table.foreign_keys
    ]


def render_view_ddl(duckdb_sql: str) -> str:
    """
    A DuckDB ``CREATE VIEW`` as a Snowflake ``CREATE OR REPLACE VIEW``.

    Every identifier is unquoted: DuckDB quotes names such as ``"conversion"``,
    and a quoted lowercase name in Snowflake is case-sensitive, so it would miss
    the table, whose unquoted name Snowflake stored uppercase.
    """
    tree = sqlglot.parse_one(duckdb_sql.strip().rstrip(";"), read="duckdb")
    for identifier in tree.find_all(exp.Identifier):
        identifier.set("quoted", False)
    tree.set("replace", True)
    return tree.sql(dialect="snowflake")


def render_schema_sql(catalog: Catalog, schema: str) -> list[str]:
    """
    Rebuild ``schema`` from scratch: the schema, every table, every foreign
    key, every view. Replacing the whole schema is what makes a sync
    idempotent: no table survives from a previous dataset.
    """
    statements = [f"CREATE OR REPLACE SCHEMA {schema}"]
    statements += [render_table_ddl(t, schema) for t in catalog.tables]
    for table in catalog.tables:
        statements += render_foreign_keys(table, schema)
    statements += [render_view_ddl(v.sql) for v in catalog.views]
    return statements


def render_account_sql(
    objects: SnowflakeObjects,
    schema: str,
    public_key_body: str,
    credit_quota: int,
) -> list[str]:
    """
    The account-level setup, each step under the least role that can run it:
    SYSADMIN owns the warehouse and the database, ACCOUNTADMIN alone may create
    and attach a resource monitor, SECURITYADMIN owns the role and the user.

    The cost guardrails: an X-Small warehouse that suspends after 60 idle
    seconds, a 60-second statement timeout, and a monthly credit quota that
    suspends the warehouse when it is spent.

    :param public_key_body: the service user's public key, PEM without the
        BEGIN / END lines and newlines, as Snowflake expects it.
    :raises ValueError: ``credit_quota`` is not positive.
    """
    if credit_quota < 1:
        raise ValueError(f"The monthly credit quota must be at least 1, got {credit_quota}")
    o = objects
    warehouse_settings = (
        "WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE STATEMENT_TIMEOUT_IN_SECONDS = 60"
    )
    return [
        "USE ROLE SYSADMIN",
        f"CREATE WAREHOUSE IF NOT EXISTS {o.warehouse} WITH {warehouse_settings} INITIALLY_SUSPENDED = TRUE",
        f"ALTER WAREHOUSE {o.warehouse} SET {warehouse_settings}",
        "USE ROLE ACCOUNTADMIN",
        f"CREATE RESOURCE MONITOR IF NOT EXISTS {o.monitor} WITH CREDIT_QUOTA = {credit_quota} "
        f"FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY "
        f"TRIGGERS ON 80 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND ON 110 PERCENT DO SUSPEND_IMMEDIATE",
        f"ALTER RESOURCE MONITOR {o.monitor} SET CREDIT_QUOTA = {credit_quota}",
        f"ALTER WAREHOUSE {o.warehouse} SET RESOURCE_MONITOR = {o.monitor}",
        "USE ROLE SYSADMIN",
        f"CREATE DATABASE IF NOT EXISTS {o.database}",
        "USE ROLE SECURITYADMIN",
        f"CREATE ROLE IF NOT EXISTS {o.role}",
        # custom roles roll up to SYSADMIN, so an admin can always see what they own
        f"GRANT ROLE {o.role} TO ROLE SYSADMIN",
        f"GRANT USAGE ON WAREHOUSE {o.warehouse} TO ROLE {o.role}",
        f"GRANT USAGE ON DATABASE {o.database} TO ROLE {o.role}",
        f"CREATE USER IF NOT EXISTS {o.user} TYPE = SERVICE DEFAULT_ROLE = {o.role} "
        f"DEFAULT_WAREHOUSE = {o.warehouse} RSA_PUBLIC_KEY = '{public_key_body}'",
        # a second run may carry a new key; the user must not keep the old one
        f"ALTER USER {o.user} SET RSA_PUBLIC_KEY = '{public_key_body}'",
        f"GRANT ROLE {o.role} TO USER {o.user}",
    ]


def render_read_grants(objects: SnowflakeObjects, schema: str) -> list[str]:
    """
    ``USAGE`` on the schema and ``SELECT`` on everything in it. Run after the
    schema is rebuilt, since replacing it drops the grants it held.
    """
    target = f"{objects.database}.{schema}"
    return [
        "USE ROLE SECURITYADMIN",
        f"GRANT USAGE ON SCHEMA {target} TO ROLE {objects.role}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA {target} TO ROLE {objects.role}",
        f"GRANT SELECT ON ALL VIEWS IN SCHEMA {target} TO ROLE {objects.role}",
    ]


def render_load_sql(path_parquet: Path, schema: str, table: str) -> tuple[str, str]:
    """
    ``PUT`` one Parquet file to the table's stage, then ``COPY INTO`` the table
    by column name (and drop the staged file).
    """
    return (
        f"PUT 'file://{Path(path_parquet).as_posix()}' @{schema}.%{table} OVERWRITE = TRUE",
        f"COPY INTO {schema}.{table} FROM @{schema}.%{table} "
        f"FILE_FORMAT = (TYPE = PARQUET) MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE PURGE = TRUE",
    )


def export_parquet(con, catalog: Catalog, schema: str, dir_out: Path) -> list[Path]:
    """
    Write every table of ``catalog`` to ``dir_out/<table>.parquet`` from the
    open DuckDB connection ``con``, in catalog order.
    """
    dir_out = Path(dir_out)
    dir_out.mkdir(parents=True, exist_ok=True)
    paths = []
    for table in catalog.tables:
        path = dir_out / f"{table.name}.parquet"
        con.execute(f"COPY (SELECT * FROM {schema}.\"{table.name}\") TO '{path.as_posix()}' (FORMAT PARQUET)")
        paths.append(path)
    return paths
