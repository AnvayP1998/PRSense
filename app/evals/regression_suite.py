"""Curate a small, fixed regression suite from the dataset.

  python -m app.evals.regression_suite select --n-bugs 6 --n-clean 6

Picks the *highest-confidence* examples — bugs caught by a revert (the
strongest signal we have) and clean merges that are old + small (least
likely to be a missed regression) — and writes them to
data/regression_cases.json. tests/test_regression.py runs the live agent
against exactly this fixed set on every CI run: these are the cases that
must never regress, run against a real Gemini/Groq call (skipped
automatically if no key is configured).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evals.framework import DATASET_PATH, load_dataset

OUT_PATH = Path("data/regression_cases.json")


def select(dataset_path: Path = DATASET_PATH, n_bugs: int = 6, n_clean: int = 6, out: Path = OUT_PATH) -> None:
    rows = load_dataset(dataset_path)

    reverted = [r for r in rows if r["labels"]["reverted"]]
    bug_followup = [r for r in rows if r["labels"]["had_bug"] and not r["labels"]["reverted"]]
    bugs = (reverted + bug_followup)[:n_bugs]

    clean = [r for r in rows if r["labels"]["clean_merge"]]
    clean.sort(key=lambda r: (r.get("changed_files", 999), r.get("merged_at") or ""))
    clean = clean[:n_clean]

    cases = [
        {
            "pr_id": r["pr_id"], "repo": r["repo"], "title": r["title"],
            "diff": r["diff"], "body": r.get("body", ""),
            "expected": "bug", "reasons": r["labels"]["reasons"],
        }
        for r in bugs
    ] + [
        {
            "pr_id": r["pr_id"], "repo": r["repo"], "title": r["title"],
            "diff": r["diff"], "body": r.get("body", ""),
            "expected": "clean", "reasons": {},
        }
        for r in clean
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"wrote {len(bugs)} bug cases + {len(clean)} clean cases to {out}")
    if len(bugs) < n_bugs:
        print(f"WARNING: only found {len(bugs)}/{n_bugs} high-confidence bug cases "
              f"(reverted={len(reverted)}, bug_followup={len(bug_followup)}) — "
              f"build a larger dataset or lower --n-bugs.")


def load_cases(path: Path = OUT_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--n-bugs", type=int, default=6)
    s.add_argument("--n-clean", type=int, default=6)
    s.add_argument("--dataset", type=Path, default=DATASET_PATH)
    s.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()
    if args.cmd == "select":
        select(args.dataset, args.n_bugs, args.n_clean, args.out)


if __name__ == "__main__":
    main()
