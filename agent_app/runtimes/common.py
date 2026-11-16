# -*- coding: utf-8 -*-

"""
What both runtimes share: their names, and the settings AgentCore Runtime
requires of an MCP server.
"""

import os

from mcp.server.fastmcp import FastMCP

AGENT_RUNTIME_NAME = "AnalyticsAgent"
"""
The agent runtime's name, as AgentCore knows it. Generic on purpose: a dataset
swap must not rename a deployed runtime.
"""

MCP_RUNTIME_NAME = "AnalyticsMcp"
"""
The MCP runtime's name, as AgentCore knows it. The agent finds the server by it
(see :mod:`.mcp_connection`).
"""

AGENT_PORT = 8080
"""
The port AgentCore Runtime sends HTTP requests to: ``POST /invocations`` and
``GET /ping``. Locally the agent listens on the same port.
"""

MCP_PORT_VAR = "FASTMCP_PORT"
"""
Overrides the MCP server's port. Unset on AgentCore Runtime.
"""

MCP_DEFAULT_PORT = 8000
"""
The port AgentCore Runtime sends MCP requests to.
"""

MCP_HOST_VAR = "MCP_HOST"
"""
Overrides the interface the MCP server listens on. ``mise run dev`` sets it to
``127.0.0.1``, so a laptop does not serve the warehouse to its whole network.
"""

MCP_DEFAULT_HOST = "0.0.0.0"
"""
Every interface: what AgentCore Runtime requires.
"""

MCP_PATH = "/mcp"
"""
The path AgentCore Runtime sends MCP requests to; the FastMCP default.
"""

MCP_TRANSPORT = "streamable-http"
"""
The MCP transport AgentCore Runtime speaks.
"""


def get_mcp_port() -> int:
    """
    The port of :data:`MCP_PORT_VAR`, else :data:`MCP_DEFAULT_PORT`.
    """
    return int(os.environ.get(MCP_PORT_VAR, str(MCP_DEFAULT_PORT)))


def get_mcp_host() -> str:
    """
    The interface of :data:`MCP_HOST_VAR`, else :data:`MCP_DEFAULT_HOST`.
    """
    return os.environ.get(MCP_HOST_VAR, MCP_DEFAULT_HOST)


def new_mcp_server(name: str) -> FastMCP:
    """
    A FastMCP server with the settings of the AgentCore MCP protocol contract:
    the port of :func:`get_mcp_port`, the path :data:`MCP_PATH`, and
    ``stateless_http=True`` (no server-side MCP session, so any microVM can
    answer any request). The same settings work locally.

    Args:
        name: the server name, the runtime's name.
    """
    return FastMCP(
        name,
        host=get_mcp_host(),
        port=get_mcp_port(),
        streamable_http_path=MCP_PATH,
        stateless_http=True,
    )


#: How long the agent's MCP client waits for one HTTP exchange, in seconds.
#: The default (30 s) is shorter than a cold Snowflake schema reflection
#: (about 35 s when the warehouse resumes), which the first tool call of a
#: fresh MCP runtime may have to wait for.
MCP_CLIENT_TIMEOUT_SECONDS = 120
