# -*- coding: utf-8 -*-

"""
The SQL dialect of the warehouse, and its translation for local runs.

Every query is written and validated in the Snowflake dialect, the deployed
engine's, so the system prompt has one dialect in every environment. Locally
the warehouse is a DuckDB file, and :func:`transpile_to_duckdb` rewrites the
query for it with sqlglot just before it runs.
"""

import sqlglot

#: The dialect every query is written and validated in.
SQL_DIALECT = "snowflake"


def transpile_to_duckdb(sql: str) -> str:
    """
    ``sql`` in the Snowflake dialect, rewritten for DuckDB.
    """
    return sqlglot.transpile(sql, read=SQL_DIALECT, write="duckdb")[0]
