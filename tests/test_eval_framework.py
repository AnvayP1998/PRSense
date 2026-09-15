"""Phase 4 tests: the eval harness itself, with the LLM mocked out (no keys,
no network) and a tiny in-memory dataset."""
from __future__ import annotations

import json

import pytest

from app.agents.schema import Finding, ReviewResult
from app.evals import framework as fw

ROWS = [
    {"pr_id": "o/r#1", "repo": "o/r", "number": 1, "title": "Fix crash", "author": "a",
     "diff": "if x is None: raise", "labels": {"had_bug": True, "had_security_issue": False,
                                                "clean_merge": False, "reverted": True, "reasons": {}}},
    {"pr_id": "o/r#2", "repo": "o/r", "number": 2, "title": "Add feature", "author": "a",
     "diff": "def new(): pass", "labels": {"had_bug": False, "had_security_issue": False,
                                            "clean_merge": True, "reverted": False, "reasons": {}}},
]


@pytest.fixture
def dataset_file(tmp_path):
    p = tmp_path / "dataset.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in ROWS), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fw, "CACHE_DIR", tmp_path / "cache")


_PR_TITLES = {r["pr_id"]: r["title"] for r in ROWS}


def _fake_llm_flags_by_pr_id(monkeypatch, flagged_ids: set[str]):
    calls = []
    flagged_titles = {_PR_TITLES[pid] for pid in flagged_ids}

    def fake(messages, provider="auto"):
        calls.append(messages)
        text = messages[1].content
        is_flagged = any(title in text for title in flagged_titles)
        findings = [Finding(issue_type="bug", severity="medium", file="x.py",
                             explanation="e")] if is_flagged else []
        return ReviewResult(summary="s", findings=findings, overall_risk="low"), "gemini:fake"

    monkeypatch.setattr(fw, "review_with_fallback", fake)
    return calls


def test_run_eval_computes_correct_metrics(monkeypatch, dataset_file):
    # Model correctly flags PR#1 (real bug) and correctly leaves PR#2 clean.
    calls = _fake_llm_flags_by_pr_id(monkeypatch, {"o/r#1"})
    config = fw.EvalConfig("test", use_retrieval=False)

    metrics, results = fw.run_eval(config, dataset_file)

    assert metrics["tp"] == 1 and metrics["fp"] == 0 and metrics["fn"] == 0 and metrics["tn"] == 1
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert len(calls) == 2  # one LLM call per row


def test_run_eval_uses_cache_on_second_run(monkeypatch, dataset_file):
    calls = _fake_llm_flags_by_pr_id(monkeypatch, {"o/r#1"})
    config = fw.EvalConfig("test", use_retrieval=False)

    fw.run_eval(config, dataset_file)
    assert len(calls) == 2

    fw.run_eval(config, dataset_file)  # should hit cache, no new LLM calls
    assert len(calls) == 2


def test_different_config_key_bypasses_cache(monkeypatch, dataset_file):
    calls = _fake_llm_flags_by_pr_id(monkeypatch, {"o/r#1"})
    fw.run_eval(fw.EvalConfig("a", prompt_version="v1_baseline", use_retrieval=False), dataset_file)
    assert len(calls) == 2
    fw.run_eval(fw.EvalConfig("b", prompt_version="v2_precision", use_retrieval=False), dataset_file)
    assert len(calls) == 4  # different config -> different cache key -> re-run


def test_sample_n_limits_rows(monkeypatch, dataset_file):
    calls = _fake_llm_flags_by_pr_id(monkeypatch, set())
    config = fw.EvalConfig("test", use_retrieval=False)
    metrics, results = fw.run_eval(config, dataset_file, sample_n=1)
    assert len(results) == 1
