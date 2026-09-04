"""Phase 3 tests: the LangGraph review pipeline, with the LLM and GitHub
writes mocked out so this runs with zero API keys and no network."""
from __future__ import annotations

import pytest

from app.agents import graph as graph_mod
from app.agents.schema import Finding, ReviewResult

FAKE_PR = {
    "pr_id": "o/r#1",
    "title": "Fix null check",
    "author": "octocat",
    "state": "open",
    "merged": False,
    "base_sha": "b", "head_sha": "h",
    "files": [{"filename": "auth.py", "status": "modified", "additions": 2, "deletions": 1}],
    "diff": "--- a/auth.py\n+++ b/auth.py\n@@ -1,1 +1,2 @@\n-x\n+if token is None: raise",
}
FAKE_STANDARDS = {"repo": "o/r", "found_count": 0, "sources": [], "note": "none"}
FAKE_SIMILAR = {"count": 0, "indexed_total": 0, "results": []}


@pytest.fixture(autouse=True)
def _mock_tools(monkeypatch):
    monkeypatch.setattr(graph_mod.tools, "get_pr_diff", lambda pr_id: FAKE_PR)
    monkeypatch.setattr(graph_mod.tools, "get_repo_coding_standards", lambda repo: FAKE_STANDARDS)
    monkeypatch.setattr(graph_mod.tools, "get_similar_prs", lambda diff, n_results=5: FAKE_SIMILAR)


class FakeGitHubClient:
    def __init__(self):
        self.posted = None

    def post_pr_comment(self, repo, number, body):
        self.posted = (repo, number, body)
        return 999


def _mock_llm(monkeypatch, result: ReviewResult, model_name: str = "gemini:fake"):
    monkeypatch.setattr(graph_mod, "review_with_fallback", lambda messages: (result, model_name))


def test_full_graph_dry_run_finds_bug(monkeypatch):
    result = ReviewResult(
        summary="Adds a None check but swallows the error silently.",
        findings=[Finding(
            issue_type="bug", severity="medium", file="auth.py", line=2,
            explanation="Raising without a message loses debugging context.",
            suggestion="Include the offending value in the exception.",
        )],
        overall_risk="medium",
    )
    _mock_llm(monkeypatch, result)

    out = graph_mod.run_review("o/r#1", dry_run=True)

    assert out["model_used"] == "gemini:fake"
    assert len(out["review"]["findings"]) == 1
    assert out["comment_id"] is None
    assert out["skipped_post_reason"] == "dry_run"
    assert "PRSense Review" in out["comment_body"]
    assert "auth.py:2" in out["comment_body"]
    assert "🟡" in out["comment_body"]  # medium severity marker


def test_full_graph_clean_pr_no_findings(monkeypatch):
    result = ReviewResult(summary="Looks fine.", findings=[], overall_risk="low")
    _mock_llm(monkeypatch, result)

    out = graph_mod.run_review("o/r#1", dry_run=True)

    assert out["review"]["findings"] == []
    assert "No issues found" in out["comment_body"]


def test_post_comment_writes_when_not_dry_run(monkeypatch):
    result = ReviewResult(summary="ok", findings=[], overall_risk="low")
    _mock_llm(monkeypatch, result)
    fake_client = FakeGitHubClient()

    state = {
        "pr_id": "o/r#1", "repo": "o/r", "number": 1, "dry_run": False,
        "pr": FAKE_PR, "coding_standards": FAKE_STANDARDS, "similar_prs": FAKE_SIMILAR,
        "review": result.model_dump(), "model_used": "gemini:fake",
        "comment_body": "hello",
    }
    out = graph_mod.post_comment(state, client=fake_client)

    assert out["comment_id"] == 999
    assert fake_client.posted == ("o/r", 1, "hello")
