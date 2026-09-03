"""Phase 2 unit tests: MCP tool implementations (no network)."""
from __future__ import annotations

import pytest

from app.core.github_client import PRContext, PRFile
from app.mcp import tools
from app.rag.retriever import SimilarPRStore


class FakeGitHubClient:
    def __init__(self, files: dict[str, str] | None = None):
        self._files = files or {}

    def get_pr_context(self, repo, number):
        return PRContext(
            repo=repo,
            number=number,
            title="Fix auth token check",
            body="Handle None token",
            author="octocat",
            base_sha="base",
            head_sha="head",
            state="open",
            merged=False,
            files=[
                PRFile("auth.py", "modified", 3, 1, "@@ -1 +1 @@\n-x\n+y")
            ],
        )

    def get_file_content(self, repo, path, ref=None):
        return self._files.get(path)


def test_parse_pr_id_ok():
    assert tools.parse_pr_id("pallets/flask#5432") == ("pallets/flask", 5432)


def test_parse_pr_id_bad():
    with pytest.raises(ValueError):
        tools.parse_pr_id("not-a-pr")


def test_get_pr_diff():
    out = tools.get_pr_diff("pallets/flask#1", client=FakeGitHubClient())
    assert out["title"] == "Fix auth token check"
    assert out["files"][0]["filename"] == "auth.py"
    assert "auth.py" in out["diff"]


def test_get_repo_files_found_and_missing():
    fc = FakeGitHubClient({"README.md": "# Hi"})
    assert tools.get_repo_files("o/r", "README.md", client=fc)["found"] is True
    assert tools.get_repo_files("o/r", "nope.md", client=fc)["found"] is False


def test_get_repo_coding_standards():
    fc = FakeGitHubClient({"CONTRIBUTING.md": "Run black.", ".editorconfig": "indent=4"})
    out = tools.get_repo_coding_standards("o/r", client=fc)
    assert out["found_count"] == 2
    paths = {s["path"] for s in out["sources"]}
    assert paths == {"CONTRIBUTING.md", ".editorconfig"}


def test_get_similar_prs(tmp_path):
    store = SimilarPRStore(persist_dir=str(tmp_path / "chroma"))
    store.add_many(
        [
            {
                "pr_id": "o/r#1", "repo": "o/r", "number": 1,
                "title": "Fix null pointer when auth token missing",
                "body": "", "diff": "if token is None: raise",
                "labels": {"had_bug": True, "clean_merge": False},
            },
            {
                "pr_id": "o/r#2", "repo": "o/r", "number": 2,
                "title": "Add dark mode toggle", "body": "", "diff": "css changes",
                "labels": {"had_bug": False, "clean_merge": True},
            },
        ]
    )
    out = tools.get_similar_prs("crash when auth token is None", n_results=1, store=store)
    assert out["count"] == 1
    assert out["results"][0]["pr_id"] == "o/r#1"
    assert out["results"][0]["labels"]["had_bug"] is True
