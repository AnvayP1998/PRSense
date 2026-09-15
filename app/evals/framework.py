"""Eval harness: run the review agent against the historical PR dataset and
compute precision/recall/F1/latency — with response caching and A/B
comparison across prompt/retrieval/model configs.

  python -m app.evals.framework index                                  # seed ChromaDB from the dataset
  python -m app.evals.framework run --config v1_baseline --sample 50
  python -m app.evals.framework compare --configs v1_baseline v2_precision --sample 50
  python -m app.evals.framework compare --configs v1_baseline no_retrieval --sample 50
  python -m app.evals.framework history

Every LLM call is cached to disk keyed by (config, pr_id, diff) — re-running
the same config is free and instant; only genuinely new (config, PR) pairs
spend quota. Delete `data/eval_cache/` to force a fresh run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import NoLLMAvailable, review_with_fallback
from app.agents.prompts import (
    PROMPT_VERSIONS,
    REVIEW_HUMAN_TEMPLATE,
    format_coding_standards,
    format_similar_prs,
)
from app.agents.schema import ReviewResult
from app.core.logging import get_logger, setup_logging
from app.db.client import get_eval_db
from app.evals.metrics import classification_metrics, latency_summary
from app.mcp import tools
from app.rag.retriever import get_similar_pr_store

setup_logging()
log = get_logger(__name__)

DATASET_PATH = Path("data/dataset.jsonl")
CACHE_DIR = Path("data/eval_cache")
POSITIVE_ISSUE_TYPES = ("bug", "security")


@dataclass
class EvalConfig:
    name: str
    prompt_version: str = "v1_baseline"
    provider: str = "auto"            # "auto" | "gemini" | "groq"
    use_retrieval: bool = True
    retrieval_k: int = 5

    def key(self) -> str:
        return f"{self.prompt_version}|{self.provider}|{self.use_retrieval}|{self.retrieval_k}"


# Named configs available to `run`/`compare` by --config name.
CONFIGS: dict[str, EvalConfig] = {
    "v1_baseline": EvalConfig("v1_baseline"),
    "v2_precision": EvalConfig("v2_precision", prompt_version="v2_precision"),
    "no_retrieval": EvalConfig("no_retrieval", use_retrieval=False),
    "groq_only": EvalConfig("groq_only", provider="groq"),
}


def load_dataset(path: Path = DATASET_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found — run `python -m app.evals.dataset_builder build` first.")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def index_dataset(path: Path = DATASET_PATH) -> int:
    """Seed ChromaDB with the dataset so retrieve_similar_prs has real
    historical PRs (not just the Phase 2 demo rows) to draw on."""
    rows = load_dataset(path)
    store = get_similar_pr_store()
    payload = [
        {
            "pr_id": r["pr_id"], "repo": r["repo"], "number": r["number"], "title": r["title"],
            "body": r.get("body", ""), "diff": r.get("diff", ""),
            "labels": {
                "had_bug": r["labels"]["had_bug"],
                "had_security_issue": r["labels"]["had_security_issue"],
                "clean_merge": r["labels"]["clean_merge"],
                "reverted": r["labels"]["reverted"],
            },
        }
        for r in rows
    ]
    return store.add_many(payload)


def _cache_path(config: EvalConfig, row: dict) -> Path:
    h = hashlib.sha256(f"{config.key()}|{row['pr_id']}|{row['diff']}".encode()).hexdigest()[:24]
    return CACHE_DIR / f"{h}.json"


def _build_messages(row: dict, config: EvalConfig, similar: dict) -> list:
    system_prompt = PROMPT_VERSIONS[config.prompt_version]
    human = REVIEW_HUMAN_TEMPLATE.format(
        repo=row["repo"], title=row["title"], author=row.get("author", ""),
        diff=row["diff"][:12000],
        coding_standards="(not fetched during eval — standards are ~stable per repo)",
        similar_prs=format_similar_prs(similar["results"]),
    )
    return [SystemMessage(content=system_prompt), HumanMessage(content=human)]


def run_one(row: dict, config: EvalConfig) -> dict:
    y_true = bool(row["labels"]["had_bug"] or row["labels"]["had_security_issue"])
    cache_file = _cache_path(config, row)

    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        review, model_used, latency_ms, error = cached["review"], cached["model_used"], cached["latency_ms"], cached.get("error")
    else:
        similar = (
            tools.get_similar_prs(row["diff"], n_results=config.retrieval_k, exclude_pr_id=row["pr_id"])
            if config.use_retrieval
            else {"count": 0, "indexed_total": 0, "results": []}
        )
        messages = _build_messages(row, config, similar)
        t0 = time.perf_counter()
        error = None
        try:
            result, model_used = review_with_fallback(messages, provider=config.provider)
            review = result.model_dump()
        except NoLLMAvailable as e:
            review, model_used, error = {"findings": []}, "none", str(e)
        latency_ms = (time.perf_counter() - t0) * 1000

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"review": review, "model_used": model_used, "latency_ms": latency_ms, "error": error}),
            encoding="utf-8",
        )

    findings = review.get("findings", [])
    y_pred = any(f["issue_type"] in POSITIVE_ISSUE_TYPES for f in findings)
    return {
        "pr_id": row["pr_id"], "y_true": int(y_true), "y_pred": int(y_pred),
        "n_findings": len(findings), "latency_ms": latency_ms, "model_used": model_used,
        "error": error,
    }


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run_eval(
    config: EvalConfig, dataset_path: Path = DATASET_PATH, sample_n: int | None = None, seed: int = 42
) -> tuple[dict, list[dict]]:
    rows = load_dataset(dataset_path)
    if sample_n and sample_n < len(rows):
        rows = random.Random(seed).sample(rows, sample_n)

    results = []
    for i, row in enumerate(rows, 1):
        results.append(run_one(row, config))
        if i % 25 == 0:
            log.info("%s: %d/%d", config.name, i, len(rows))

    y_true = [bool(r["y_true"]) for r in results]
    y_pred = [bool(r["y_pred"]) for r in results]
    cm = classification_metrics(y_true, y_pred)
    lat = latency_summary([r["latency_ms"] for r in results if r["latency_ms"]])
    metrics = {**cm.as_dict(), "latency": lat}
    return metrics, results


def store_run(config: EvalConfig, metrics: dict, results: list[dict], dataset_path: Path, notes: str = "") -> int:
    db = get_eval_db()
    run = {
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "config_name": config.name,
        "config_json": json.dumps(asdict(config)),
        "dataset_path": str(dataset_path),
        "n_samples": len(results),
        "precision": metrics["precision"], "recall": metrics["recall"], "f1": metrics["f1"],
        "false_positive_rate": metrics["false_positive_rate"], "accuracy": metrics["accuracy"],
        "latency_p50": metrics["latency"]["p50"], "latency_p95": metrics["latency"]["p95"],
        "latency_p99": metrics["latency"]["p99"], "notes": notes,
    }
    result_rows = [
        {"pr_id": r["pr_id"], "y_true": r["y_true"], "y_pred": r["y_pred"],
         "n_findings": r["n_findings"], "latency_ms": r["latency_ms"],
         "model_used": r["model_used"], "error": r["error"]}
        for r in results
    ]
    return db.insert_run(run, result_rows)


def print_comparison_table(rows: list[dict]) -> str:
    headers = ["config", "n", "precision", "recall", "f1", "fpr", "p50ms", "p95ms"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        lines.append(
            "| " + " | ".join([
                r["config"], str(r["n"]),
                f"{r['precision']:.2f}", f"{r['recall']:.2f}", f"{r['f1']:.2f}",
                f"{r['false_positive_rate']:.2f}",
                f"{r['latency']['p50']:.0f}", f"{r['latency']['p95']:.0f}",
            ]) + " |"
        )
    table = "\n".join(lines)
    print(table)
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("index")

    r = sub.add_parser("run")
    r.add_argument("--config", required=True, choices=list(CONFIGS))
    r.add_argument("--sample", type=int, default=None)
    r.add_argument("--dataset", type=Path, default=DATASET_PATH)

    c = sub.add_parser("compare")
    c.add_argument("--configs", nargs="+", required=True, choices=list(CONFIGS))
    c.add_argument("--sample", type=int, default=None)
    c.add_argument("--dataset", type=Path, default=DATASET_PATH)

    h = sub.add_parser("history")
    h.add_argument("--config", default=None)
    h.add_argument("--limit", type=int, default=20)

    args = ap.parse_args()

    if args.cmd == "index":
        n = index_dataset()
        print(f"indexed {n} PRs into ChromaDB")

    elif args.cmd == "run":
        config = CONFIGS[args.config]
        metrics, results = run_eval(config, args.dataset, args.sample)
        run_id = store_run(config, metrics, results, args.dataset)
        print(json.dumps({k: v for k, v in metrics.items() if k != "latency"}, indent=2))
        print(json.dumps(metrics["latency"], indent=2))
        print(f"stored as eval_runs.id={run_id}")

    elif args.cmd == "compare":
        table_rows = []
        for name in args.configs:
            config = CONFIGS[name]
            metrics, results = run_eval(config, args.dataset, args.sample)
            store_run(config, metrics, results, args.dataset, notes="compare run")
            table_rows.append({"config": name, "n": len(results), **metrics})
        table = print_comparison_table(table_rows)
        out = Path("data/eval_runs") / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_comparison.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(table, encoding="utf-8")
        print(f"\nsaved to {out}")

    elif args.cmd == "history":
        db = get_eval_db()
        for run in db.history(args.config, args.limit):
            print(
                f"#{run['id']:<4} {run['run_ts'][:19]}  {run['config_name']:<14} "
                f"commit={run['git_commit']:<9} n={run['n_samples']:<4} "
                f"P={run['precision']:.2f} R={run['recall']:.2f} F1={run['f1']:.2f} "
                f"FPR={run['false_positive_rate']:.2f} p50={run['latency_p50']:.0f}ms"
            )


if __name__ == "__main__":
    main()
