"""EvalDB: SQLite-backed eval run storage."""
from __future__ import annotations

from app.db.client import EvalDB


def test_insert_and_read_history(tmp_path):
    db = EvalDB(path=tmp_path / "evals.db")
    run = {
        "run_ts": "2026-01-01T00:00:00Z", "git_commit": "abc123", "config_name": "baseline",
        "config_json": "{}", "dataset_path": "data/dataset.jsonl", "n_samples": 2,
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "false_positive_rate": 0.0, "accuracy": 1.0,
        "latency_p50": 500.0, "latency_p95": 600.0, "latency_p99": 650.0, "notes": "",
    }
    results = [
        {"pr_id": "o/r#1", "y_true": 1, "y_pred": 1, "n_findings": 1,
         "latency_ms": 500.0, "model_used": "gemini:x", "error": None},
        {"pr_id": "o/r#2", "y_true": 0, "y_pred": 0, "n_findings": 0,
         "latency_ms": 400.0, "model_used": "gemini:x", "error": None},
    ]
    run_id = db.insert_run(run, results)

    history = db.history()
    assert len(history) == 1
    assert history[0]["config_name"] == "baseline"
    assert history[0]["precision"] == 1.0

    stored_results = db.results_for_run(run_id)
    assert len(stored_results) == 2
    assert {r["pr_id"] for r in stored_results} == {"o/r#1", "o/r#2"}


def test_history_filters_by_config(tmp_path):
    db = EvalDB(path=tmp_path / "evals.db")
    base = {
        "run_ts": "t", "git_commit": "c", "config_json": "{}", "dataset_path": "d",
        "n_samples": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5,
        "false_positive_rate": 0.1, "accuracy": 0.5,
        "latency_p50": 1, "latency_p95": 2, "latency_p99": 3, "notes": "",
    }
    db.insert_run({**base, "config_name": "a"}, [])
    db.insert_run({**base, "config_name": "b"}, [])

    assert len(db.history()) == 2
    assert len(db.history(config_name="a")) == 1
