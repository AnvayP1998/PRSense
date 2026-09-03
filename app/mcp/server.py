"""PRSense MCP server.

Exposes repo/PR context to the LLM as MCP tools instead of stuffing everything
into one giant prompt. Runs over stdio (the transport LangGraph's MCP adapter
speaks by default).

Run standalone:  python -m app.mcp.server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.logging import get_logger, setup_logging
from app.mcp import tools

setup_logging()
log = get_logger(__name__)

mcp = FastMCP("prsense")


@mcp.tool()
def get_pr_diff(pr_id: str) -> dict:
    """Return the unified diff and per-file change summary for a pull request.

    Args:
        pr_id: Pull request identifier as "owner/repo#number", e.g. "pallets/flask#5432".
    """
    return tools.get_pr_diff(pr_id)


@mcp.tool()
def get_repo_files(repo: str, path: str, ref: str | None = None) -> dict:
    """Return the content of a single file in a repository for extra context.

    Args:
        repo: "owner/repo".
        path: File path within the repo, e.g. "src/flask/app.py".
        ref: Optional git ref (branch/sha); defaults to the default branch.
    """
    return tools.get_repo_files(repo, path, ref)


@mcp.tool()
def get_similar_prs(diff_text: str, n_results: int = 5) -> dict:
    """Find historical PRs most similar to the given diff (RAG over ChromaDB).

    Use this to see how comparable past changes played out (bugs, reverts,
    security issues) before judging the current PR.
    """
    return tools.get_similar_prs(diff_text, n_results)


@mcp.tool()
def get_repo_coding_standards(repo: str, ref: str | None = None) -> dict:
    """Return the repo's contribution/style guides (CONTRIBUTING.md, linters, .editorconfig).

    Args:
        repo: "owner/repo".
        ref: Optional git ref; defaults to the default branch.
    """
    return tools.get_repo_coding_standards(repo, ref)


def main() -> None:
    log.info("starting PRSense MCP server (stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
