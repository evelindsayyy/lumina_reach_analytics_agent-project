# -*- coding: utf-8 -*-

"""
The MCP runtime's data tools, called two ways: directly, and through a real MCP
client session (in memory, so no port and no network).

These read the local DuckDB warehouse file (``mise run gen-data``).
"""

import asyncio

from mcp.shared.memory import create_connected_server_and_client_session

from agent_app.runtimes import analytics_mcp
from agent_app.runtimes.analytics_mcp import execute_sql_query
from agent_app.runtimes.analytics_mcp import get_database_schema
from agent_app.runtimes.common import MCP_PATH
from agent_app.runtimes.common import MCP_RUNTIME_NAME


class TestTools:
    def test_get_database_schema(self):
        result = get_database_schema()
        assert "daily_stats" in result
        assert "v_reference_date" in result  # views are part of the schema

    def test_execute_sql_query(self):
        result = execute_sql_query(sql="SELECT COUNT(*) AS n FROM campaign")
        assert "|" in result
        assert "n" in result

    def test_no_rows(self):
        assert execute_sql_query(sql="SELECT 1 WHERE 1 = 0") == "No result"

    def test_a_cte_is_allowed(self):
        result = execute_sql_query(
            sql="WITH d AS (SELECT campaign_id FROM campaign) SELECT COUNT(*) AS n FROM d"
        )
        assert "|" in result

    def test_a_write_is_rejected_by_the_guardrails(self):
        result = execute_sql_query(sql="DROP TABLE campaign")
        assert result.startswith("Error: rejected by the SQL guardrails.")
        assert "NOT_SELECT" in result

    def test_a_write_behind_a_cte_does_not_land(self):
        before = execute_sql_query(sql="SELECT COUNT(*) AS n FROM campaign")
        execute_sql_query(
            sql="WITH d AS (SELECT campaign_id FROM campaign) DELETE FROM campaign"
        )
        assert execute_sql_query(sql="SELECT COUNT(*) AS n FROM campaign") == before

    def test_an_unknown_table_is_reported_not_raised(self):
        assert execute_sql_query(sql="SELECT * FROM no_such_table").startswith("Error")


def _over_mcp(coro_factory):
    """Run ``coro_factory(session)`` against the server over an MCP session."""

    async def run():
        async with create_connected_server_and_client_session(
            analytics_mcp.mcp._mcp_server
        ) as session:
            return await coro_factory(session)

    return asyncio.run(run())


class TestOverMcp:
    def test_the_server_offers_exactly_the_two_data_tools(self):
        result = _over_mcp(lambda s: s.list_tools())
        names = sorted(t.name for t in result.tools)
        assert names == ["execute_sql_query", "get_database_schema"]

    def test_the_tool_description_is_the_docstring(self):
        """The docstring is what the model reads to decide how to call the tool."""
        result = _over_mcp(lambda s: s.list_tools())
        sql_tool = next(t for t in result.tools if t.name == "execute_sql_query")
        assert "guardrails" in sql_tool.description
        assert sql_tool.inputSchema["required"] == ["sql"]

    def test_call_tool_returns_the_table_as_text(self):
        result = _over_mcp(
            lambda s: s.call_tool(
                "execute_sql_query", {"sql": "SELECT COUNT(*) AS n FROM advertiser"}
            )
        )
        assert not result.isError
        assert "|" in result.content[0].text

    def test_a_guardrail_rejection_is_an_answer_not_an_mcp_error(self):
        """The model has to read the code to fix its SQL, so it is content."""
        result = _over_mcp(
            lambda s: s.call_tool("execute_sql_query", {"sql": "DELETE FROM campaign"})
        )
        assert not result.isError
        assert "NOT_SELECT" in result.content[0].text


def test_the_server_follows_the_agentcore_contract():
    settings = analytics_mcp.mcp.settings
    assert analytics_mcp.mcp.name == MCP_RUNTIME_NAME
    assert settings.streamable_http_path == MCP_PATH
    assert settings.stateless_http is True


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.runtimes.analytics_mcp",
        preview=False,
    )
