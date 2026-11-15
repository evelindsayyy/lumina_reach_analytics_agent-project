# -*- coding: utf-8 -*-

"""
The two processes the agent runs as, each one an AgentCore Runtime:

- :mod:`.analytics_mcp`: the data tools, as a stateless MCP server. The only
  process that can reach the warehouse.
- :mod:`.analytics_agent`: the agent, as an HTTP runtime that answers the chat
  UI in the AI SDK stream format. It reaches the warehouse only through the MCP
  server.

The same modules run locally (``mise run dev``) and on AgentCore Runtime.
"""
