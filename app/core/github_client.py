"""Thin wrapper over PyGithub for the PR context PRSense needs.

Kept small and dependency-light so it can be called from the webhook handler,
the MCP tools layer (Phase 2), and the dataset builder (Phase 4) alike.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import httpx
from github import Auth, Github, GithubException

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class PRFile:
    filename: str
    status: str            # added | modified | removed | renamed
    additions: int
    deletions: int
    patch: str | None      # unified diff hunk for this file (None for binary)


@dataclass
class PRContext:
    repo: str              # "owner/name"
    number: int
    title: str
    body: str
    author: str
    base_sha: str
    head_sha: str
    state: str
    merged: bool
    files: list[PRFile] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    @property
    def unified_diff(self) -> str:
        parts = []
        for f in self.files:
            if f.patch:
                parts.append(f"--- a/{f.filename}\n+++ b/{f.filename}\n{f.patch}")
        return "\n".join(parts)


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        settings = get_settings()
        self._token = token or settings.github_token
        auth = Auth.Token(self._token) if self._token else None
        self._gh = Github(auth=auth, per_page=100)

    # -- reads -----------------------------------------------------------
    def get_pr_context(self, repo: str, number: int) -> PRContext:
        gh_repo = self._gh.get_repo(repo)
        pr = gh_repo.get_pull(number)
        files = [
            PRFile(
                filename=f.filename,
                status=f.status,
                additions=f.additions,
                deletions=f.deletions,
                patch=getattr(f, "patch", None),
            )
            for f in pr.get_files()
        ]
        return PRContext(
            repo=repo,
            number=number,
            title=pr.title or "",
            body=pr.body or "",
            author=pr.user.login if pr.user else "",
            base_sha=pr.base.sha,
            head_sha=pr.head.sha,
            state=pr.state,
            merged=bool(pr.merged),
            files=files,
            labels=[lbl.name for lbl in pr.labels],
        )

    def get_pr_diff(self, repo: str, number: int) -> str:
        """Raw unified diff via the diff media type (one request)."""
        url = f"https://api.github.com/repos/{repo}/pulls/{number}"
        headers = {
            "Accept": "application/vnd.github.v3.diff",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def get_file_content(
        self, repo: str, path: str, ref: str | None = None
    ) -> str | None:
        try:
            gh_repo = self._gh.get_repo(repo)
            content = (
                gh_repo.get_contents(path, ref=ref)
                if ref
                else gh_repo.get_contents(path)
            )
            if isinstance(content, list):
                return None  # it's a directory
            return content.decoded_content.decode("utf-8", errors="replace")
        except GithubException as e:
            if e.status == 404:
                return None
            raise

    def get_repo_metadata(self, repo: str) -> dict:
        gh_repo = self._gh.get_repo(repo)
        return {
            "full_name": gh_repo.full_name,
            "description": gh_repo.description,
            "language": gh_repo.language,
            "default_branch": gh_repo.default_branch,
            "license": gh_repo.license.spdx_id if gh_repo.license else None,
            "stars": gh_repo.stargazers_count,
        }

    # -- writes ----------------------------------------------------------
    def post_pr_comment(self, repo: str, number: int, body: str) -> int:
        gh_repo = self._gh.get_repo(repo)
        issue = gh_repo.get_issue(number)
        comment = issue.create_comment(body)
        log.info("posted comment %s on %s#%s", comment.id, repo, number)
        return comment.id

    def rate_limit_remaining(self) -> int:
        return self._gh.get_rate_limit().core.remaining


@lru_cache
def get_github_client() -> GitHubClient:
    return GitHubClient()
