# -*- coding: utf-8 -*-

"""
The ``AnalyticsMcp`` runtime: the agent's data tools, as a stateless MCP server.

- ``get_database_schema``: the schema of ``SCHEMA_NAME``, in the compact
  encoding the agent reads.
- ``execute_sql_query``: the SQL guardrails, then the read-only, always
  rolled-back query (see :meth:`~agent_app.one.one_02_db.DbMixin.execute_sql_query`).

This is the only process that holds a warehouse connection, so it is the only
one whose execution role can read the warehouse credentials. The agent sees the
data through these two tools and nothing else.

A thin layer on purpose: each tool calls the same ``one`` method the in-process
agent used, so the guardrails and their tests did not move.

Run it with ``python -m agent_app.runtimes.analytics_mcp``.
"""

from ..one.api import one
from .common import MCP_RUNTIME_NAME
from .common import MCP_TRANSPORT
from .common import new_mcp_server

#: The MCP server, named after the runtime.
mcp = new_mcp_server(MCP_RUNTIME_NAME)


@mcp.tool()
def get_database_schema() -> str:
    """
    Retrieve the complete database schema information in LLM-optimized compact format.

    This tool returns the structure of every table and view in the business
    database, including:
    - Table names and column definitions
    - Data types (simplified to STR, INT, DEC, TS, DT, etc.)
    - Constraints: Primary Key (*PK), Unique (*UQ), Not Null (*NN), Index (*IDX)
    - Foreign key relationships (*FK->Table.Column)

    Use this tool FIRST to understand the database structure before writing SQL queries.

    Returns:
        A string containing the encoded database schema in compact format.
    """
    return one.database_schema_str


@mcp.tool()
def execute_sql_query(sql: str) -> str:
    """
    Execute a read-only SQL SELECT query and return the results as a Markdown table.

    Write the query in the Snowflake dialect. Before it runs, the query passes
    the SQL guardrails; a rejected query comes back as
    "Error: rejected by the SQL guardrails. <CODE>: <what to change>", so read
    the code and fix the SQL rather than retrying it unchanged.

    Args:
        sql: A valid SQL SELECT query string to execute.

    Returns:
        - On success: A Markdown-formatted table with query results, followed by
          a note when the guardrails rewrote the query or when the result
          counts conversions from one source
        - If no rows match: "No result"
        - On error: An error message describing what went wrong
    """
    return one.execute_sql_query(sql=sql)


def main():  # pragma: no cover - blocks until stopped
    """
    Reflect and encode the schema, then serve, blocking until stopped.

    Encoding the schema at startup does two things: the first question does not
    pay for reflection, and a runtime that cannot reach its warehouse fails
    here, with the reason in its log, instead of on a user's first question.
    """
    schema = one.database_schema_str
    print(
        f"{MCP_RUNTIME_NAME}: {len(one.reflected_metadata.tables)} tables and views "
        f"of {one.config.schema_name!r} on {one.config.warehouse_engine} "
        f"({len(schema):,} schema characters), serving on "
        f"{mcp.settings.host}:{mcp.settings.port}{mcp.settings.streamable_http_path}",
        flush=True,
    )
    mcp.run(transport=MCP_TRANSPORT)


if __name__ == "__main__":  # pragma: no cover
    main()
