"""Phase 5: the dashboard script must at least run without raising, against
both an empty db and one with real eval/review rows."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = str(Path(__file__).resolve().parent.parent / "dashboard" / "streamlit_app.py")


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    import streamlit as st
    from app.db.client import EvalDB
    import app.db.client as db_mod

    db = EvalDB(path=tmp_path / "dashboard_test.db")
    monkeypatch.setattr(db_mod, "get_eval_db", lambda: db)
    # st.cache_data is process-wide and keyed only on function args (there
    # are none here), so a cached result from a previous test/db would
    # otherwise leak into this one.
    st.cache_data.clear()
    return db


def test_dashboard_renders_with_empty_db():
    at = AppTest.from_file(DASHBOARD)
    at.run()
    assert not at.exception
    assert at.title[0].value == "🤖 PRSense Dashboard"


def test_dashboard_renders_with_real_data(_isolated_db):
    db = _isolated_db
    db.insert_run(
        {
            "run_ts": "2026-01-01T00:00:00+00:00", "git_commit": "abc123",
            "config_name": "v1_baseline", "config_json": "{}", "dataset_path": "d.jsonl",
            "n_samples": 10, "precision": 0.5, "recall": 0.5, "f1": 0.5,
            "false_positive_rate": 0.1, "accuracy": 0.8,
            "latency_p50": 1000.0, "latency_p95": 2000.0, "latency_p99": 3000.0,
            "notes": "",
        },
        [{"pr_id": "o/r#1", "y_true": 1, "y_pred": 1, "n_findings": 1,
          "latency_ms": 900.0, "model_used": "groq:x", "error": None}],
    )
    db.log_review({
        "reviewed_at": "2026-01-01T00:00:00+00:00", "pr_id": "o/r#1", "repo": "o/r",
        "title": "Fix bug", "model_used": "groq:x", "overall_risk": "medium",
        "n_findings": 1, "dry_run": 1, "comment_id": None, "latency_ms": 900.0,
        "source": "webhook",
    })

    at = AppTest.from_file(DASHBOARD)
    at.run()
    assert not at.exception
    assert at.metric[0].value == "1"  # PRs reviewed
