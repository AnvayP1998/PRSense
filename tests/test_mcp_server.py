"""Phase 2 integration test: the MCP server is reachable and advertises its tools
through the LangChain adapter (this is the wiring the LangGraph agent uses)."""
from __future__ import annotations

import pytest

from app.agents.mcp_bridge import load_mcp_tools

EXPECTED = {
    "get_pr_diff",
    "get_repo_files",
    "get_similar_prs",
    "get_repo_coding_standards",
}


@pytest.mark.asyncio
async def test_mcp_tools_exposed_to_langchain():
    tools = await load_mcp_tools()
    names = {t.name for t in tools}
    assert EXPECTED.issubset(names), names


@pytest.mark.asyncio
async def test_similar_prs_callable_over_mcp():
    tools = {t.name: t for t in await load_mcp_tools()}
    result = await tools["get_similar_prs"].ainvoke(
        {"diff_text": "some change", "n_results": 3}
    )
    # Empty index in a fresh checkout is fine; the call must still round-trip.
    assert "count" in str(result)
