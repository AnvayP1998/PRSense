"""SQLite storage for eval run history (Phase 4) — before/after tracking.

Plain stdlib sqlite3, zero new dependencies. Swappable for Supabase later:
every write goes through this one class, so the storage backend is an
implementation detail behind `EvalDB`.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ts TEXT NOT NULL,
    git_commit TEXT,
    config_name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    dataset_path TEXT,
    n_samples INTEGER,
    precision REAL, recall REAL, f1 REAL,
    false_positive_rate REAL, accuracy REAL,
    latency_p50 REAL, latency_p95 REAL, latency_p99 REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES eval_runs(id),
    pr_id TEXT NOT NULL,
    y_true INTEGER NOT NULL,
    y_pred INTEGER NOT NULL,
    n_findings INTEGER,
    latency_ms REAL,
    model_used TEXT,
    error TEXT
);
"""


def _db_path() -> Path:
    settings = get_settings()
    # DATABASE_URL, if set to sqlite:///path, wins; else fall back to sqlite_path.
    if settings.database_url.startswith("sqlite:///"):
        return Path(settings.database_url.removeprefix("sqlite:///"))
    return Path(settings.sqlite_path)


class EvalDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def insert_run(self, run: dict, results: list[dict]) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO eval_runs
                   (run_ts, git_commit, config_name, config_json, dataset_path, n_samples,
                    precision, recall, f1, false_positive_rate, accuracy,
                    latency_p50, latency_p95, latency_p99, notes)
                   VALUES (:run_ts, :git_commit, :config_name, :config_json, :dataset_path,
                           :n_samples, :precision, :recall, :f1, :false_positive_rate, :accuracy,
                           :latency_p50, :latency_p95, :latency_p99, :notes)""",
                run,
            )
            run_id = cur.lastrowid
            conn.executemany(
                """INSERT INTO eval_results
                   (run_id, pr_id, y_true, y_pred, n_findings, latency_ms, model_used, error)
                   VALUES (:run_id, :pr_id, :y_true, :y_pred, :n_findings, :latency_ms, :model_used, :error)""",
                [{**r, "run_id": run_id} for r in results],
            )
            return run_id

    def history(self, config_name: str | None = None, limit: int = 50) -> list[dict]:
        q = "SELECT * FROM eval_runs"
        params: tuple = ()
        if config_name:
            q += " WHERE config_name = ?"
            params = (config_name,)
        q += " ORDER BY id DESC LIMIT ?"
        params = params + (limit,)
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(q, params).fetchall()]

    def results_for_run(self, run_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_results WHERE run_id = ?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]


def get_eval_db() -> EvalDB:
    return EvalDB()
