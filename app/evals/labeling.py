"""Weak-label collection for the historical PR dataset.

There is no ground-truth "this PR had a bug" database, so labels are derived
from auditable public signals rather than a model's opinion:

  reverted      — a later merged PR whose title is GitHub's auto-generated
                   `Revert "<original title>"` and whose title matches this
                   PR's title. Reliable (GitHub's own UI produces this
                   format), but only catches PRs reverted through the UI.
  bug_followup  — a later issue/PR whose title or body uses regression
                   language ("regression", "broke", "broken by", "introduced
                   in/by") AND references this PR's number (#123).
  security      — same idea, for security language (CVE, GHSA, vulnerability,
                   "security fix") referencing this PR's number.

had_bug      = reverted OR bug_followup
clean_merge  = merged, not had_bug, not security, and old enough
               (>= MIN_AGE_DAYS) that a regression would likely have
               surfaced by now.

This is a HIGH-PRECISION / LOW-RECALL scheme by design: every positive label
comes with a `reasons` list of the exact GitHub items that triggered it, so
it's auditable, and it deliberately never guesses. It will under-count real
bugs that were fixed silently without referencing the PR number — that's a
known, documented limitation (see dataset_builder.py's `audit` command,
which samples labels for manual spot-checking).

Search calls are batched PER REPO (a handful of queries total), not per PR,
to stay well under GitHub Search API's 30 req/min limit.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from github import Github

from app.core.logging import get_logger

log = get_logger(__name__)

MIN_AGE_DAYS = 60
_SEARCH_SLEEP_SECONDS = 2.2  # keeps us under the 30 req/min search rate limit
_MAX_PAGES_PER_QUERY = 3      # 3 * 100 = 300 results per query, plenty

_REVERT_TITLE_RE = re.compile(r'^Revert\s+"(.+)"\s*$', re.IGNORECASE)
_PR_REF_RE = re.compile(r"#(\d+)")
_MAX_REFS_PER_ITEM = 8  # a real regression/security report cites a couple of
                        # PRs, not dozens — anything above this is almost
                        # always a bot-generated changelog/dependency-bump
                        # body whose #N mentions are noise, not references

BUG_QUERY_TERMS = '"regression" OR "broke" OR "broken by" OR "introduced in" OR "introduced by"'
SECURITY_QUERY_TERMS = 'CVE OR GHSA OR vulnerability OR "security fix" OR "security issue"'


def _normalize_title(title: str) -> str:
    t = title.strip().lower()
    t = re.sub(r"[\"'`]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _extract_pr_refs(item) -> set[int]:
    """PR numbers referenced by an item's title/body, with noise filters:
    skip bot-authored items (dependabot etc. — their changelog bodies are
    full of coincidental #N-looking text) and skip any item that references
    an implausibly large number of PRs (a real bug report cites one or two,
    not dozens — that pattern means we hit a changelog/release-notes page)."""
    author = getattr(getattr(item, "user", None), "login", "") or ""
    if author.endswith("[bot]"):
        return set()
    text = f"{item.title or ''} {item.body or ''}"
    refs = set(int(n) for n in _PR_REF_RE.findall(text))
    refs.discard(item.number)
    if len(refs) > _MAX_REFS_PER_ITEM:
        return set()
    return refs


def _throttled_search(gh: Github, query: str):
    """Yield items from a search query, sleeping between pages to respect
    the search API's separate (much lower) rate limit."""
    results = gh.search_issues(query=query)
    count = 0
    page = 0
    try:
        total = results.totalCount
    except Exception:  # noqa: BLE001
        total = "?"
    log.info("search %r -> ~%s results", query, total)
    for item in results:
        yield item
        count += 1
        if count % 100 == 0:
            page += 1
            if page >= _MAX_PAGES_PER_QUERY:
                break
            time.sleep(_SEARCH_SLEEP_SECONDS)
    time.sleep(_SEARCH_SLEEP_SECONDS)


@dataclass
class RepoLabelIndex:
    """Per-repo indexes built once, then consulted for every candidate PR."""

    revert_titles: set[str] = field(default_factory=set)
    revert_reasons: dict[str, str] = field(default_factory=dict)   # normalized title -> reason url
    bug_refs: dict[int, list[str]] = field(default_factory=lambda: defaultdict(list))
    security_refs: dict[int, list[str]] = field(default_factory=lambda: defaultdict(list))

    def label_for(self, number: int, title: str) -> dict:
        norm = _normalize_title(title)
        reasons: dict[str, list[str]] = {"reverted": [], "bug_followup": [], "security": []}

        if norm in self.revert_titles:
            reasons["reverted"].append(self.revert_reasons.get(norm, "matched revert title"))
        if number in self.bug_refs:
            reasons["bug_followup"] = list(self.bug_refs[number])
        if number in self.security_refs:
            reasons["security"] = list(self.security_refs[number])

        had_bug = bool(reasons["reverted"] or reasons["bug_followup"])
        had_security = bool(reasons["security"])
        return {
            "reverted": bool(reasons["reverted"]),
            "had_bug": had_bug,
            "had_security_issue": had_security,
            "reasons": reasons,
        }


def build_repo_label_index(gh: Github, repo: str) -> RepoLabelIndex:
    idx = RepoLabelIndex()

    # 1) Reverts: PRs whose title GitHub auto-generated as Revert "<title>"
    for item in _throttled_search(gh, f'repo:{repo} is:pr in:title "Revert \\""'):
        m = _REVERT_TITLE_RE.match(item.title or "")
        if m:
            norm = _normalize_title(m.group(1))
            idx.revert_titles.add(norm)
            idx.revert_reasons[norm] = item.html_url

    # 2) Bug/regression follow-ups referencing a PR number. GitHub's search
    # API requires an explicit is:issue or is:pull-request qualifier (no OR
    # between qualifiers), so run both and merge.
    for kind in ("is:issue", "is:pull-request"):
        for item in _throttled_search(gh, f"repo:{repo} {kind} {BUG_QUERY_TERMS}"):
            for num in _extract_pr_refs(item):
                idx.bug_refs[num].append(item.html_url)

    # 3) Security follow-ups referencing a PR number
    for kind in ("is:issue", "is:pull-request"):
        for item in _throttled_search(gh, f"repo:{repo} {kind} {SECURITY_QUERY_TERMS}"):
            for num in _extract_pr_refs(item):
                idx.security_refs[num].append(item.html_url)

    log.info(
        "%s: %d revert titles, %d bug-referenced PRs, %d security-referenced PRs",
        repo, len(idx.revert_titles), len(idx.bug_refs), len(idx.security_refs),
    )
    return idx
