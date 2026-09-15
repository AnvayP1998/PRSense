"""Core tool implementations exposed to the LLM via MCP.

These are plain functions returning JSON-serializable dicts so they can be:
  - unit-tested directly (see tests/test_mcp_tools.py),
  - called from the LangGraph agent,
  - wrapped by the MCP server in server.py.

A PR is addressed as "owner/repo#number" (the `pr_id`).
"""
from __future__ import annotations

import re

from app.core.github_client import GitHubClient, get_github_client
from app.core.logging import get_logger
from app.rag.retriever import SimilarPRStore, get_similar_pr_store

log = get_logger(__name__)

_PR_ID_RE = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)#(?P<number>\d+)$")

# Files we treat as "coding standards" signal, in priority order.
STANDARDS_FILES = [
    "CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "STYLEGUIDE.md",
    ".editorconfig",
    "pyproject.toml",
    "setup.cfg",
    ".flake8",
    ".ruff.toml",
    "ruff.toml",
    ".pre-commit-config.yaml",
    ".pylintrc",
]
_STANDARDS_MAX_CHARS = 4000


def parse_pr_id(pr_id: str) -> tuple[str, int]:
    m = _PR_ID_RE.match(pr_id.strip())
    if not m:
        raise ValueError(f"invalid pr_id {pr_id!r}; expected 'owner/repo#123'")
    return m.group("repo"), int(m.group("number"))


def get_pr_diff(pr_id: str, *, client: GitHubClient | None = None) -> dict:
    """Return the unified diff for a PR plus a per-file summary."""
    repo, number = parse_pr_id(pr_id)
    gh = client or get_github_client()
    ctx = gh.get_pr_context(repo, number)
    return {
        "pr_id": pr_id,
        "title": ctx.title,
        "author": ctx.author,
        "state": ctx.state,
        "merged": ctx.merged,
        "base_sha": ctx.base_sha,
        "head_sha": ctx.head_sha,
        "files": [
            {
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
            }
            for f in ctx.files
        ],
        "diff": ctx.unified_diff,
    }


def get_repo_files(
    repo: str, path: str, ref: str | None = None, *, client: GitHubClient | None = None
) -> dict:
    """Return the content of a file in the repo for additional context."""
    gh = client or get_github_client()
    content = gh.get_file_content(repo, path, ref=ref)
    return {
        "repo": repo,
        "path": path,
        "ref": ref,
        "found": content is not None,
        "content": content or "",
    }


def get_similar_prs(
    diff_text: str,
    n_results: int = 5,
    *,
    store: SimilarPRStore | None = None,
    exclude_pr_id: str | None = None,
) -> dict:
    """RAG lookup: historical PRs most similar to this diff (ChromaDB).

    exclude_pr_id: internal use by the eval harness (leave-one-out so a PR
    in the indexed dataset never retrieves itself). Not exposed as an MCP
    tool parameter — the LLM-facing tool never needs it.
    """
    st = store or get_similar_pr_store()
    hits = st.query(diff_text, n_results=n_results, exclude_id=exclude_pr_id)
    return {
        "count": len(hits),
        "indexed_total": st.count(),
        "results": [
            {
                "pr_id": h.pr_id,
                "repo": h.repo,
                "number": h.number,
                "title": h.title,
                "distance": round(h.distance, 4),
                "labels": {
                    k: h.metadata[k]
                    for k in ("had_bug", "had_security_issue", "clean_merge", "reverted")
                    if k in h.metadata
                },
                "summary": h.summary,
            }
            for h in hits
        ],
    }


def get_repo_coding_standards(
    repo: str, ref: str | None = None, *, client: GitHubClient | None = None
) -> dict:
    """Read whatever style/contribution guides the repo publishes."""
    gh = client or get_github_client()
    found: list[dict] = []
    for candidate in STANDARDS_FILES:
        content = gh.get_file_content(repo, candidate, ref=ref)
        if content:
            found.append(
                {"path": candidate, "content": content[:_STANDARDS_MAX_CHARS]}
            )
    return {
        "repo": repo,
        "found_count": len(found),
        "sources": found,
        "note": "No explicit standards found." if not found else "",
    }
