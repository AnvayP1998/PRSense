"""Bridge: expose the PRSense MCP server's tools to LangChain / LangGraph.

The LangGraph review agent (Phase 3) calls `load_mcp_tools()` to get a list of
LangChain `BaseTool`s backed by the MCP server, so the LLM invokes tools over
MCP rather than receiving all context in one prompt.
"""
from __future__ import annotations

import sys
from functools import lru_cache

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.logging import get_logger

log = get_logger(__name__)

SERVER_NAME = "prsense"


@lru_cache
def _server_config() -> dict:
    return {
        SERVER_NAME: {
            "command": sys.executable,
            "args": ["-m", "app.mcp.server"],
            "transport": "stdio",
        }
    }


def get_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(_server_config())


async def load_mcp_tools() -> list:
    """Return LangChain tools backed by the PRSense MCP server."""
    client = get_mcp_client()
    tools = await client.get_tools()
    log.info("loaded %d MCP tools: %s", len(tools), [t.name for t in tools])
    return tools
