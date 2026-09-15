"""Regression suite: a fixed set of known-bug / known-clean PRs that must
always be caught / never be flagged. Runs against the REAL LLM (not mocked)
because it's guarding against real-world model drift, not code logic — so
it's automatically skipped if no LLM key is configured or the case file
hasn't been generated yet (see app/evals/regression_suite.py).
"""
from __future__ import annotations

import pytest

from app.agents.llm import review_with_fallback
from app.agents.prompts import REVIEW_HUMAN_TEMPLATE, REVIEW_SYSTEM_PROMPT, format_similar_prs
from app.core.config import get_settings
from app.evals.regression_suite import load_cases
from langchain_core.messages import HumanMessage, SystemMessage

pytestmark = pytest.mark.regression

CASES = load_cases()
settings = get_settings()
HAS_LLM = bool(settings.gemini_api_key or settings.groq_api_key)

if not CASES:
    pytest.skip(
        "no data/regression_cases.json — run "
        "`python -m app.evals.regression_suite select` after building the dataset",
        allow_module_level=True,
    )
if not HAS_LLM:
    pytest.skip("no GEMINI_API_KEY/GROQ_API_KEY configured", allow_module_level=True)


def _predict(case: dict) -> bool:
    messages = [
        SystemMessage(content=REVIEW_SYSTEM_PROMPT),
        HumanMessage(content=REVIEW_HUMAN_TEMPLATE.format(
            repo=case["repo"], title=case["title"], author="",
            diff=case["diff"][:12000],
            coding_standards="(omitted for regression test)",
            similar_prs=format_similar_prs([]),
        )),
    ]
    result, _ = review_with_fallback(messages)
    return any(f.issue_type in ("bug", "security") for f in result.findings)


@pytest.mark.parametrize("case", [c for c in CASES if c["expected"] == "bug"],
                         ids=lambda c: c["pr_id"])
def test_known_bug_is_caught(case):
    assert _predict(case), f"{case['pr_id']} ({case['title']}) has a known bug but was not flagged"


@pytest.mark.parametrize("case", [c for c in CASES if c["expected"] == "clean"],
                         ids=lambda c: c["pr_id"])
def test_known_clean_is_not_flagged(case):
    assert not _predict(case), f"{case['pr_id']} ({case['title']}) is clean but was flagged"
