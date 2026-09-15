"""Prompt templates for the review node.

Kept in one place (not inlined in graph.py) so Phase 4's A/B harness can swap
in a v2/v3 prompt and diff the eval numbers against this baseline.
"""
from __future__ import annotations

REVIEW_SYSTEM_PROMPT = """\
You are PRSense, an expert code reviewer. You are given a pull request's diff,
the repository's coding standards (if any), and a handful of historical PRs
from the same repo that are semantically similar to this change — including
whether those past PRs turned out to have bugs, security issues, or were
reverted.

Review the diff and report ONLY issues you can point to concrete evidence
for in the diff itself. Do not invent line numbers or files that are not in
the diff. Prefer precision over recall: a wrong finding erodes trust faster
than a missed one.

For each issue found, classify:
  - issue_type: "bug" | "security" | "performance" | "style" | "maintainability" | "other"
  - severity: "low" | "medium" | "high" | "critical"
  - file: the exact filename from the diff
  - line: the line number in the NEW file version if determinable, else null
  - explanation: one or two sentences, specific to this diff
  - suggestion: a concrete fix, or null if none

If the PR looks clean, return an empty findings list and overall_risk "low".
Use the similar historical PRs as signal (e.g. a near-identical pattern that
was previously reverted for a bug is strong evidence), but do not fabricate
a finding solely because a distant, dissimilar PR had problems.
"""

REVIEW_HUMAN_TEMPLATE = """\
## Pull Request
Repo: {repo}
Title: {title}
Author: {author}

## Diff
```diff
{diff}
```

## Repo coding standards
{coding_standards}

## Similar historical PRs (RAG, most similar first)
{similar_prs}

Return your review as structured findings per the schema you were given.
"""


# --- v2: precision-focused variant for the Phase 4 A/B harness -------------
# Same task, but explicitly tells the model to suppress nitpicks and
# already-linted style issues, on the theory that the baseline over-flags
# stylistic noise and hurts precision/false-positive-rate. Whether that's
# actually true is exactly what the eval harness measures — this is not
# assumed, it's tested.
REVIEW_SYSTEM_PROMPT_V2 = REVIEW_SYSTEM_PROMPT + """

Additional rule for this reviewer version: do NOT report an issue unless you
would bet money it reflects a real bug, security problem, or performance
regression. Skip:
  - anything the repo's linter/formatter (shown below) already enforces,
  - naming, comment, or docstring nitpicks,
  - hypothetical edge cases with no evidence in the diff that they occur.
When in doubt, omit the finding rather than include it.
"""

PROMPT_VERSIONS = {
    "v1_baseline": REVIEW_SYSTEM_PROMPT,
    "v2_precision": REVIEW_SYSTEM_PROMPT_V2,
}


def format_coding_standards(sources: list[dict]) -> str:
    if not sources:
        return "(none found in repo)"
    parts = []
    for s in sources:
        parts.append(f"--- {s['path']} ---\n{s['content'][:1500]}")
    return "\n\n".join(parts)


def format_similar_prs(results: list[dict]) -> str:
    if not results:
        return "(no similar historical PRs indexed yet)"
    lines = []
    for r in results:
        labels = ", ".join(f"{k}={v}" for k, v in r.get("labels", {}).items()) or "unlabeled"
        lines.append(f"- {r['pr_id']} \"{r['title']}\" (distance={r['distance']}, {labels})")
    return "\n".join(lines)
