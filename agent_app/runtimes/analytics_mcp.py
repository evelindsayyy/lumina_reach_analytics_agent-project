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

import logging
import threading
import time

from ..one.api import one
from .common import MCP_RUNTIME_NAME
from .common import MCP_TRANSPORT
from .common import new_mcp_server

logger = logging.getLogger(__name__)

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


def warm_schema() -> bool:
    """
    Reflect and encode the schema now, so the first question does not pay for
    it, and log the outcome. A warehouse that cannot be reached is logged with
    the reason and returns False: the tool call will try again, and fail with
    the same reason in front of the agent.
    """
    started = time.monotonic()
    try:
        schema = one.database_schema_str
    except Exception:
        logger.exception(f"{MCP_RUNTIME_NAME}: schema warm-up failed")
        return False
    print(
        f"{MCP_RUNTIME_NAME}: {len(one.reflected_metadata.tables)} tables and views "
        f"of {one.config.schema_name!r} on {one.config.warehouse_engine} "
        f"({len(schema):,} schema characters) in {time.monotonic() - started:.1f} s",
        flush=True,
    )
    return True


def main():  # pragma: no cover - blocks until stopped
    """
    Serve, blocking until stopped, with the schema warming on a side thread.

    Not warmed before serving: on Snowflake, reflection takes about half a
    minute when the warehouse has to resume, and a runtime that does not answer
    while it starts looks dead to its host. A call that arrives first waits for
    the same reflection, which the agent's MCP client timeout allows for.
    """
    threading.Thread(target=warm_schema, name="warm-schema", daemon=True).start()
    print(
        f"{MCP_RUNTIME_NAME}: serving on "
        f"{mcp.settings.host}:{mcp.settings.port}{mcp.settings.streamable_http_path}",
        flush=True,
    )
    mcp.run(transport=MCP_TRANSPORT)


if __name__ == "__main__":  # pragma: no cover
    main()
