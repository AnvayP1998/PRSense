"""PRSense dashboard — Phase 5.

  streamlit run dashboard/streamlit_app.py

Reads directly from the local SQLite db (data/prsense.db) that Phases 4-5
already write to: `eval_runs`/`eval_results` (the eval harness's before/
after history) and `reviews` (every real agent run via webhook or the demo
script). No new backend, no paid service — it's a read-only view over data
PRSense was already producing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

import app.db.client as db_client

st.set_page_config(page_title="PRSense Dashboard", page_icon="🤖", layout="wide")


@st.cache_data(ttl=30)
def load_eval_history() -> pd.DataFrame:
    db = db_client.get_eval_db()
    rows = db.history(limit=500)
    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def load_reviews() -> pd.DataFrame:
    db = db_client.get_eval_db()
    rows = db.recent_reviews(limit=200)
    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def load_review_stats() -> dict:
    return db_client.get_eval_db().review_stats()


def _empty_state(msg: str) -> None:
    st.info(msg)


st.title("🤖 PRSense Dashboard")
st.caption(
    "Live view over the eval harness's before/after history and the agent's "
    "real review feed. Data only — nothing here is simulated."
)

eval_df = load_eval_history()
reviews_df = load_reviews()
review_stats = load_review_stats()

# ---- KPI row ---------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("PRs reviewed", review_stats.get("n_reviews") or 0)
c2.metric("Reviews with findings", review_stats.get("n_with_findings") or 0)
c3.metric("Total findings surfaced", review_stats.get("total_findings") or 0)
c4.metric("Comments posted", review_stats.get("n_posted") or 0)

if not eval_df.empty:
    latest_by_config = eval_df.sort_values("id").groupby("config_name").tail(1)
    st.subheader("Latest eval score per config")
    st.dataframe(
        latest_by_config[
            ["config_name", "n_samples", "precision", "recall", "f1",
             "false_positive_rate", "latency_p50", "git_commit", "run_ts"]
        ].rename(columns={
            "config_name": "config", "n_samples": "n", "false_positive_rate": "fpr",
            "latency_p50": "p50 (ms)", "git_commit": "commit", "run_ts": "when",
        }).sort_values("f1", ascending=False),
        hide_index=True, width="stretch",
    )
else:
    _empty_state(
        "No eval runs yet. Run `python -m app.evals.framework run --config groq_only "
        "--sample 50` (see README Phase 4) to populate this."
    )

st.divider()

# ---- Precision/Recall/F1 trends --------------------------------------------
st.subheader("Precision / Recall / F1 over time")
if not eval_df.empty:
    configs = sorted(eval_df["config_name"].unique())
    picked = st.multiselect("Configs to show", configs, default=configs)
    plot_df = eval_df[eval_df["config_name"].isin(picked)].copy()
    plot_df["run_ts"] = pd.to_datetime(plot_df["run_ts"])
    plot_df = plot_df.sort_values("run_ts")

    metric = st.radio("Metric", ["f1", "precision", "recall", "false_positive_rate"],
                       horizontal=True)
    chart_df = plot_df.pivot_table(index="run_ts", columns="config_name", values=metric)
    st.line_chart(chart_df)
else:
    _empty_state("Nothing to chart yet.")

st.divider()

# ---- Latency ----------------------------------------------------------------
st.subheader("Latency (p50 / p95 / p99) by config")
if not eval_df.empty:
    lat_df = eval_df.sort_values("id").groupby("config_name").tail(1)[
        ["config_name", "latency_p50", "latency_p95", "latency_p99"]
    ].set_index("config_name")
    st.bar_chart(lat_df)
else:
    _empty_state("Nothing to chart yet.")

st.divider()

# ---- Recent reviews feed ----------------------------------------------------
st.subheader("Recent reviews")
if not reviews_df.empty:
    show = reviews_df[
        ["reviewed_at", "pr_id", "overall_risk", "n_findings", "model_used",
         "dry_run", "comment_id", "source", "latency_ms"]
    ].rename(columns={
        "reviewed_at": "when", "overall_risk": "risk", "n_findings": "findings",
        "model_used": "model", "dry_run": "dry run", "comment_id": "comment posted?",
        "latency_ms": "latency (ms)",
    })
    show["dry run"] = show["dry run"].map({1: "yes", 0: "no"})
    show["comment posted?"] = show["comment posted?"].notna().map({True: "yes", False: "no"})
    st.dataframe(show, hide_index=True, width="stretch")
else:
    _empty_state(
        "No reviews logged yet. Trigger one via the webhook (Phase 1) or "
        "`python scripts/phase3_demo.py --pr owner/repo#123` (Phase 3) — "
        "every real run through the agent graph logs here automatically."
    )

st.divider()
st.caption(
    "Source: `data/prsense.db` (SQLite, local, free). Refreshes every 30s — "
    "rerun this page or wait for the cache to expire to see new data."
)
