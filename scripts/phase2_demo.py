"""Phase 2 hands-on demo.

  python scripts/phase2_demo.py seed     # index a handful of fake PRs into ChromaDB
  python scripts/phase2_demo.py query "crash when the auth token is None"
  python scripts/phase2_demo.py mcp      # list + call tools THROUGH the MCP server

No API keys required.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.mcp import tools
from app.rag.retriever import get_similar_pr_store

DEMO_PRS = [
    dict(pr_id="demo/app#1", repo="demo/app", number=1,
         title="Guard against missing auth token",
         body="raise 401 instead of crashing when Authorization header absent",
         diff="if token is None:\n    raise Unauthorized()",
         labels={"had_bug": True, "clean_merge": False, "reverted": False}),
    dict(pr_id="demo/app#2", repo="demo/app", number=2,
         title="Add dark mode toggle to settings",
         body="pure CSS + a preference flag", diff=".theme-dark { background: #111 }",
         labels={"had_bug": False, "clean_merge": True, "reverted": False}),
    dict(pr_id="demo/app#3", repo="demo/app", number=3,
         title="Use f-string instead of % formatting in logger",
         body="style only", diff='log.info(f"user {uid} logged in")',
         labels={"had_bug": False, "clean_merge": True, "reverted": False}),
    dict(pr_id="demo/app#4", repo="demo/app", number=4,
         title="Cache DB connection at module level",
         body="later reverted: broke tests due to shared state across event loops",
         diff="_conn = connect()  # module global",
         labels={"had_bug": True, "clean_merge": False, "reverted": True}),
]


def seed() -> None:
    n = get_similar_pr_store().add_many(DEMO_PRS)
    print(f"indexed {n} PRs; collection total = {get_similar_pr_store().count()}")


def query(text: str) -> None:
    out = tools.get_similar_prs(text, n_results=3)
    print(f"indexed_total={out['indexed_total']}  hits={out['count']}")
    for r in out["results"]:
        print(f"  [{r['distance']:.3f}] {r['pr_id']}  {r['title']}  labels={r['labels']}")


async def mcp_demo() -> None:
    from app.agents.mcp_bridge import load_mcp_tools

    lc_tools = await load_mcp_tools()
    print("tools exposed over MCP:", [t.name for t in lc_tools])
    by_name = {t.name: t for t in lc_tools}
    res = await by_name["get_similar_prs"].ainvoke(
        {"diff_text": "null check on auth token", "n_results": 2}
    )
    print("get_similar_prs ->", res)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if cmd == "seed":
        seed()
    elif cmd == "query":
        query(sys.argv[2])
    elif cmd == "mcp":
        asyncio.run(mcp_demo())
    else:
        print(__doc__)
