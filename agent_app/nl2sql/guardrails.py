# -*- coding: utf-8 -*-

"""
The guardrails every SQL the agent writes passes before it runs: parsed into
an AST with sqlglot (Snowflake dialect), checked, and rewritten.

Generic on purpose. What exists (tables, views, columns) comes from the
database schema itself, reflected; what is forbidden for this dataset
(sensitive columns, conversion sources, share columns) comes from
``data/sql-policy.toml``. A dataset swap changes neither this module nor its
tests.

Checks, in order:

1. ``PARSE_ERROR``: not valid SQL.
2. ``MULTI_STATEMENT``: more than one statement.
3. ``NOT_SELECT``: anything but a read query (DML, DDL, COPY, GRANT, CALL, ...),
   at the root or anywhere inside, or a ``SYSTEM$`` function.
4. ``UNKNOWN_TABLE``: a table outside the dataset's schema.
5. ``SENSITIVE_COLUMN``: a sensitive column, or ``*`` projected over a table
   that has one (``COUNT(*)`` reads no column and is fine).
6. ``UNKNOWN_COLUMN``: a column of no table in the query (an invented field).
7. ``CONVERSION_MIX``: conversions of more than one source.
8. ``RATIO_AVG``: ``AVG`` of a ratio or of a share column.

Rewrites: ``CURRENT_DATE`` and its kin become the data's reference date, so a
relative window never drifts with the calendar; a query without ``LIMIT``
gets one.

This is not the only safety layer: ``execute_sql_query`` still runs every
query in a transaction that is always rolled back, on a read-only connection.
The guardrails stop the wrong query early with an actionable message; the
transaction stops whatever slips through.
"""

import dataclasses
import tomllib
from pathlib import Path

import sqlalchemy as sa
import sqlglot
from sqlglot import exp

from ..warehouse.dialect import SQL_DIALECT

#: Rows a query returns at most unless it sets its own LIMIT.
DEFAULT_LIMIT = 1000

#: Statement types that change something.
_WRITE_TYPES = tuple(
    getattr(exp, name)
    for name in ["Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command", "Copy", "Grant", "Use", "TruncateTable", "Set", "Describe", "Show"]
    if hasattr(exp, name)
)

#: Functions that read the clock, rewritten to the reference date.
_CLOCK_FUNCTIONS = {"GETDATE", "SYSDATE", "NOW", "LOCALTIMESTAMP", "CURRENT_DATE", "CURRENT_TIMESTAMP"}


class GuardrailError(ValueError):
    """
    A query the guardrails refuse.

    :param code: such as ``CONVERSION_MIX``.
    :param message: what is wrong and how to fix it, for the model.
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class GuardrailPolicy:
    """
    Everything the guardrails know about one dataset.
    """

    # fmt: off
    schema_name: str = dataclasses.field()  #: The only schema queries may name.
    table_columns: dict[str, frozenset[str]] = dataclasses.field()  #: Every queryable table or view and its columns, lower case.
    sensitive_columns: dict[str, frozenset[str]] = dataclasses.field(default_factory=dict)  #: Columns never selected, by table.
    share_columns: frozenset[str] = dataclasses.field(default_factory=frozenset)  #: Columns AVG must not be taken of.
    conversion_columns: dict[str, frozenset[str] | None] = dataclasses.field(default_factory=dict)  #: Conversion-carrying columns by table; None = every column.
    conversion_source_of_table: dict[str, str] = dataclasses.field(default_factory=dict)  #: Which source a table's conversions belong to.
    conversion_source_labels: dict[str, str] = dataclasses.field(default_factory=dict)  #: What each source counts, for messages and answers.
    reference_date_sql: str = dataclasses.field(default="(SELECT reference_date FROM v_reference_date)")  #: What a clock function becomes.
    # fmt: on


def load_policy(path_toml: Path, schema_name: str, table_columns: dict[str, frozenset[str]]) -> GuardrailPolicy:
    """
    The policy of a dataset: its ``sql-policy.toml`` plus the reflected tables.

    :raises ValueError: the file names a table or column that does not exist,
        so a typo cannot silently switch a rule off.
    """
    data = tomllib.loads(path_toml.read_text(encoding="utf-8"))
    sensitive: dict[str, set[str]] = {}
    for qualified in data.get("sensitive", {}).get("columns", []):
        table, column = qualified.lower().split(".")
        if column not in table_columns.get(table, frozenset()):
            raise ValueError(f"{path_toml.name}: sensitive column {qualified!r} does not exist")
        sensitive.setdefault(table, set()).add(column)
    conversion_columns: dict[str, frozenset[str] | None] = {}
    source_of_table: dict[str, str] = {}
    labels: dict[str, str] = {}
    for source in data.get("conversion_source", []):
        labels[source["name"]] = source["label"]
        for table, columns in source["tables"].items():
            if table not in table_columns:
                raise ValueError(f"{path_toml.name}: conversion source table {table!r} does not exist")
            missing = set(columns) - table_columns[table]
            if missing:
                raise ValueError(f"{path_toml.name}: {table} has no columns {sorted(missing)}")
            conversion_columns[table] = frozenset(columns) if columns else None
            source_of_table[table] = source["name"]
    return GuardrailPolicy(
        schema_name=schema_name.lower(),
        table_columns=table_columns,
        sensitive_columns={t: frozenset(c) for t, c in sensitive.items()},
        share_columns=frozenset(data.get("ratios", {}).get("share_columns", [])),
        conversion_columns=conversion_columns,
        conversion_source_of_table=source_of_table,
        conversion_source_labels=labels,
    )


def reflect_table_columns(metadata: sa.MetaData) -> dict[str, frozenset[str]]:
    """
    Table and view names to their column names, lower case, from reflected
    ``metadata`` (``metadata.reflect(..., views=True)``).
    """
    return {table.name.lower(): frozenset(c.name.lower() for c in table.columns) for table in metadata.tables.values()}


@dataclasses.dataclass(frozen=True)
class ValidatedSql:
    """
    A query that passed every check, as it will run.
    """

    # fmt: off
    sql: str = dataclasses.field()  #: The rewritten SQL, Snowflake dialect.
    tables: list[str] = dataclasses.field()  #: Tables and views it reads, sorted.
    conversion_source: str | None = dataclasses.field()  #: The one conversion source it uses, if any.
    rewrites: list[str] = dataclasses.field()  #: What was rewritten, such as the reference date.
    # fmt: on


def _parse(sql: str) -> exp.Expression:
    try:
        trees = [tree for tree in sqlglot.parse(sql, read=SQL_DIALECT) if tree is not None]
    except sqlglot.errors.ParseError as e:
        raise GuardrailError("PARSE_ERROR", f"the SQL does not parse: {str(e).splitlines()[0]}") from e
    if len(trees) != 1:
        raise GuardrailError("MULTI_STATEMENT", f"send exactly one SELECT statement, not {len(trees)}")
    return trees[0]


def _check_read_only(tree: exp.Expression) -> None:
    if not isinstance(tree, exp.Query):
        raise GuardrailError("NOT_SELECT", f"only SELECT queries are allowed, not {type(tree).__name__.upper()}")
    for node in tree.walk():
        if isinstance(node, _WRITE_TYPES):
            raise GuardrailError("NOT_SELECT", f"{type(node).__name__.upper()} is not allowed inside a query")
        if isinstance(node, exp.Anonymous) and str(node.name).upper().startswith("SYSTEM$"):
            raise GuardrailError("NOT_SELECT", f"system function {node.name} is not allowed")


def _collect_tables(tree: exp.Expression, policy: GuardrailPolicy) -> tuple[dict[str, str], set[str]]:
    """
    ``(alias -> table, cte names)``; checks every table is in the dataset.
    """
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    aliases: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name in ctes and not table.db:
            aliases[table.alias_or_name.lower()] = name
            continue
        schema = (table.db or "").lower()
        if table.catalog or schema not in ("", policy.schema_name) or name not in policy.table_columns:
            full = ".".join(part for part in [table.catalog, table.db, table.name] if part)
            raise GuardrailError(
                "UNKNOWN_TABLE",
                f"table {full!r} is not queryable; use only these tables and views: {sorted(policy.table_columns)}",
            )
        aliases[table.alias_or_name.lower()] = name
    return aliases, ctes


def _output_aliases(tree: exp.Expression) -> set[str]:
    """
    Names a query defines itself: SELECT aliases, and the column lists of
    CTE or subquery aliases. An unqualified column may refer to one of them.
    """
    names = {alias.alias.lower() for alias in tree.find_all(exp.Alias) if alias.alias}
    for table_alias in tree.find_all(exp.TableAlias):
        names |= {column.name.lower() for column in table_alias.columns}
    return names


def _check_columns(tree: exp.Expression, aliases: dict[str, str], ctes: set[str], policy: GuardrailPolicy) -> dict[str, set[str]]:
    """
    Check every column reference; return the columns read per table.
    """
    base_tables = {table for table in aliases.values() if table not in ctes}
    output_aliases = _output_aliases(tree)
    used: dict[str, set[str]] = {table: set() for table in base_tables}
    for star in tree.find_all(exp.Star):
        parent = star.parent
        # only a projection (SELECT * or t.*) reads columns; COUNT(*) reads none
        if not isinstance(parent, (exp.Select, exp.Column)):
            continue
        qualifier = parent.table.lower() if isinstance(parent, exp.Column) and parent.table else None
        targets = {aliases[qualifier]} if qualifier in aliases else base_tables
        for table in targets:
            if table in policy.sensitive_columns:
                raise GuardrailError("SENSITIVE_COLUMN", f"SELECT * over {table!r} would expose {sorted(policy.sensitive_columns[table])}; list the columns you need")
            if table in policy.table_columns:
                used.setdefault(table, set()).update(policy.table_columns[table])
    for column in tree.find_all(exp.Column):
        name = column.name.lower()
        if not name or isinstance(column.this, exp.Star):
            continue
        qualifier = column.table.lower() if column.table else None
        if qualifier:
            if qualifier not in aliases:
                raise GuardrailError("UNKNOWN_COLUMN", f"{column.sql()!r}: {qualifier!r} is not a table or alias of the query")
            table = aliases[qualifier]
            if table in ctes:
                continue
            candidates = {table}
        else:
            candidates = {t for t in base_tables if name in policy.table_columns.get(t, frozenset())}
            if not candidates:
                if name in output_aliases:
                    continue
                raise GuardrailError("UNKNOWN_COLUMN", f"column {name!r} is in none of the tables of the query: {sorted(base_tables)}")
        for table in candidates:
            if name in policy.sensitive_columns.get(table, frozenset()):
                raise GuardrailError("SENSITIVE_COLUMN", f"{table}.{name} is sensitive contact data and cannot be selected")
            if name not in policy.table_columns[table] and name not in output_aliases:
                raise GuardrailError("UNKNOWN_COLUMN", f"{table} has no column {name!r}; its columns: {sorted(policy.table_columns[table])}")
            used[table].add(name)
    return used


def _conversion_source(used: dict[str, set[str]], policy: GuardrailPolicy) -> str | None:
    sources = set()
    for table, columns in used.items():
        if table not in policy.conversion_columns:
            continue
        carrying = policy.conversion_columns[table]
        if carrying is None or columns & carrying:
            sources.add(policy.conversion_source_of_table[table])
    if len(sources) > 1:
        labels = [policy.conversion_source_labels.get(s, s) for s in sorted(sources)]
        raise GuardrailError(
            "CONVERSION_MIX",
            f"the query combines conversions of {labels}; they count different things and cannot be "
            f"added or compared. Answer from one source, or show them side by side from separate queries",
        )
    return sources.pop() if sources else None


def _check_ratio_avg(tree: exp.Expression, policy: GuardrailPolicy) -> None:
    for avg in tree.find_all(exp.Avg):
        argument = avg.this
        if isinstance(argument, exp.Div) or argument.find(exp.Div):
            raise GuardrailError("RATIO_AVG", f"{avg.sql(dialect=SQL_DIALECT)!r} averages a ratio; use SUM(numerator) / SUM(denominator)")
        names = {c.name.lower() for c in argument.find_all(exp.Column)}
        if isinstance(argument, exp.Column):
            names.add(argument.name.lower())
        shares = names & policy.share_columns
        if shares:
            raise GuardrailError("RATIO_AVG", f"AVG of {sorted(shares)} is unweighted; weight by impressions: SUM(share * impressions) / SUM(impressions)")


def _rewrite(tree: exp.Expression, policy: GuardrailPolicy) -> tuple[exp.Expression, list[str]]:
    rewrites: list[str] = []

    def transform(node: exp.Expression) -> exp.Expression:
        clock = isinstance(node, (exp.CurrentDate, exp.CurrentTimestamp)) or (
            isinstance(node, exp.Anonymous) and str(node.name).upper() in _CLOCK_FUNCTIONS
        )
        if clock:
            rewrites.append(f"{node.sql(dialect=SQL_DIALECT)} -> the reference date")
            return sqlglot.parse_one(policy.reference_date_sql, read=SQL_DIALECT)
        return node

    tree = tree.transform(transform)
    if not tree.args.get("limit"):
        tree = tree.limit(DEFAULT_LIMIT)
        rewrites.append(f"LIMIT {DEFAULT_LIMIT} added")
    return tree, rewrites


def validate_sql(sql: str, policy: GuardrailPolicy) -> ValidatedSql:
    """
    Check ``sql`` against ``policy`` and rewrite it to run.

    :raises GuardrailError: the first check that fails.
    """
    tree = _parse(sql)
    _check_read_only(tree)
    aliases, ctes = _collect_tables(tree, policy)
    used = _check_columns(tree, aliases, ctes, policy)
    source = _conversion_source(used, policy)
    _check_ratio_avg(tree, policy)
    tree, rewrites = _rewrite(tree, policy)
    return ValidatedSql(
        sql=tree.sql(dialect=SQL_DIALECT),
        tables=sorted(table for table in set(aliases.values()) if table not in ctes),
        conversion_source=source,
        rewrites=rewrites,
    )
