"""Build the historical-PR eval dataset.

  python -m app.evals.dataset_builder build --per-repo 50
  python -m app.evals.dataset_builder stats
  python -m app.evals.dataset_builder audit --n 30

`build` is resumable: it skips PR ids already present in the output file, so
a run interrupted by a rate limit or a Ctrl+C can just be re-run.

Requires GITHUB_TOKEN in .env (unauthenticated 60 req/hr will not get
through a run of any real size).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from github import Github

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.evals.labeling import MIN_AGE_DAYS, build_repo_label_index
from app.mcp import tools

setup_logging()
log = get_logger(__name__)

DEFAULT_REPOS = ["pallets/flask", "psf/requests", "fastapi/fastapi"]  # tiangolo/fastapi moved orgs
DEFAULT_OUT = Path("data/dataset.jsonl")
_MAX_DIFF_CHARS = 20000


def _load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        rows[row["pr_id"]] = row
    return rows


def _append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


_POOL_CAP = 1500  # cheap list-only calls; no diff fetched for the pool


def _retry(fn, *, attempts: int = 3, base_delay: float = 3.0):
    """Retry on transient network errors (DNS blips, connection resets) —
    seen in practice during the long pagination this module does."""
    import requests

    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            delay = base_delay * (2 ** i)
            log.warning("transient network error (%s), retrying in %.0fs [%d/%d]", e, delay, i + 1, attempts)
            time.sleep(delay)
    raise last_exc


def _eligible_merged_pool(repo_obj, min_age_days: int, pool_cap: int) -> list:
    """Cheaply list up to pool_cap merged PRs older than min_age_days,
    spanning the repo's whole history (oldest-first) rather than clustering
    right at the age cutoff. No diff is fetched here — that only happens for
    the PRs actually sampled from this pool, in `build()`."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    pool = []
    for pr in repo_obj.get_pulls(state="closed", sort="created", direction="desc"):
        if len(pool) >= pool_cap:
            break
        # merged_at (present directly in the list payload) implies merged;
        # checking pr.merged separately would silently trigger a full
        # per-PR completion request in PyGithub — avoid it.
        if pr.merged_at is None:
            continue
        merged_at = pr.merged_at
        if merged_at.tzinfo is None:
            merged_at = merged_at.replace(tzinfo=timezone.utc)
        if merged_at > cutoff:
            continue  # too recent — give a regression time to surface
        pool.append(pr)
    pool.reverse()  # oldest eligible first
    return pool


def _stride_sample(pool: list, n: int) -> list:
    """Evenly-spaced sample across the whole pool (oldest to newest), so the
    dataset spans the repo's full history instead of a narrow recent window
    that (as observed) rarely overlaps with where GitHub Search's
    relevance-ranked bug/regression reports actually land."""
    if len(pool) <= n:
        return pool
    step = len(pool) / n
    return [pool[int(i * step)] for i in range(n)]


def build(repos: list[str], per_repo: int, min_age_days: int, out: Path) -> None:
    settings = get_settings()
    if not settings.github_token:
        raise SystemExit(
            "GITHUB_TOKEN is required to build the dataset (unauthenticated "
            "rate limits make a run of any real size impractical). Add it to .env."
        )

    from github import Auth

    gh = Github(auth=Auth.Token(settings.github_token), per_page=100)
    existing = _load_existing(out)
    log.info("resuming with %d rows already in %s", len(existing), out)

    for repo in repos:
        log.info("=== %s ===", repo)
        repo_obj = gh.get_repo(repo)
        label_index = build_repo_label_index(gh, repo)

        new_for_repo = 0
        target = per_repo
        already = sum(1 for pid in existing if pid.startswith(repo + "#"))
        if already >= target:
            log.info("%s already has %d/%d rows, skipping", repo, already, target)
            continue

        pool = _retry(lambda: _eligible_merged_pool(repo_obj, min_age_days, _POOL_CAP))
        log.info("%s: eligible pool = %d merged PRs (aged >= %dd), sampling %d",
                  repo, len(pool), min_age_days, target)

        # Stratified sampling: a plain stride sample only touches ~3% of a
        # 1500-PR pool, so it rarely lands on the (rare) labeled-buggy PRs —
        # observed in practice as literal 0 positives for 2 of 3 repos.
        # Instead, take every PR the label index already flagged (capped at
        # half the target so the set doesn't skew all-positive), then fill
        # the rest with a stride sample across the remaining pool for
        # historical diversity among the "clean" examples.
        flagged, unflagged = [], []
        for pr in pool:
            lbl = label_index.label_for(pr.number, pr.title or "")
            (flagged if (lbl["had_bug"] or lbl["had_security_issue"]) else unflagged).append(pr)
        log.info("%s: %d/%d pool PRs pre-flagged as buggy/security", repo, len(flagged), len(pool))

        flagged_cap = max(int(target * 0.7), 1)  # leave room for clean diversity even if flagged is large
        take_flagged = flagged[:flagged_cap]
        remaining = max(target - len(take_flagged), 0)
        # oversample 2x on the fill so a few diff-fetch failures don't leave
        # us short of `target`
        candidates = take_flagged + _stride_sample(unflagged, min(remaining * 2, len(unflagged)))

        for pr in candidates:
            if new_for_repo + already >= target:
                break
            pr_id = f"{repo}#{pr.number}"
            if pr_id in existing:
                continue

            try:
                diff_info = _retry(lambda: tools.get_pr_diff(pr_id, client=None), attempts=2)
            except Exception as e:  # noqa: BLE001
                log.warning("skip %s: diff fetch failed: %s", pr_id, e)
                continue

            labels = label_index.label_for(pr.number, pr.title or "")
            labels["clean_merge"] = not labels["had_bug"] and not labels["had_security_issue"]

            row = {
                "pr_id": pr_id,
                "repo": repo,
                "number": pr.number,
                "title": pr.title or "",
                "body": (pr.body or "")[:4000],
                "author": pr.user.login if pr.user else "",
                "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
                "diff": diff_info["diff"][:_MAX_DIFF_CHARS],
                "labels": labels,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            _append_row(out, row)
            existing[pr_id] = row
            new_for_repo += 1
            if new_for_repo % 10 == 0:
                log.info("%s: %d/%d new rows written", repo, new_for_repo, target - already)

        log.info("%s done: %d new rows (total for repo: %d)", repo, new_for_repo, already + new_for_repo)

    log.info("dataset build complete: %d total rows in %s", len(existing), out)


def stats(path: Path) -> None:
    rows = list(_load_existing(path).values())
    if not rows:
        print(f"{path} is empty or missing.")
        return
    by_repo: dict[str, list[dict]] = {}
    for r in rows:
        by_repo.setdefault(r["repo"], []).append(r)

    print(f"Total rows: {len(rows)}\n")
    header = f"{'repo':<22}{'n':>5}{'had_bug':>10}{'security':>10}{'clean':>8}{'reverted':>10}"
    print(header)
    print("-" * len(header))
    for repo, rs in sorted(by_repo.items()):
        n = len(rs)
        had_bug = sum(r["labels"]["had_bug"] for r in rs)
        sec = sum(r["labels"]["had_security_issue"] for r in rs)
        clean = sum(r["labels"]["clean_merge"] for r in rs)
        rev = sum(r["labels"]["reverted"] for r in rs)
        print(f"{repo:<22}{n:>5}{had_bug:>10}{sec:>10}{clean:>8}{rev:>10}")
    total_had_bug = sum(r["labels"]["had_bug"] for r in rows)
    print(f"\nOverall positive rate (had_bug or security): "
          f"{total_had_bug}/{len(rows)} = {total_had_bug / len(rows):.1%}")


def audit(path: Path, n: int, seed: int = 42) -> None:
    """Sample n rows for manual label verification -> data/label_audit.csv.

    Fill in the `human_label` column (bug / security / clean / unsure) and
    run `python -m app.evals.metrics audit-report` (see metrics.py) to get
    the measured precision of the automatic labeling.
    """
    rows = list(_load_existing(path).values())
    if not rows:
        print(f"{path} is empty or missing.")
        return
    random.Random(seed).shuffle(rows)
    sample = rows[:n]

    out_csv = Path("data/label_audit.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pr_id", "title", "auto_label", "reasons", "human_label (bug/security/clean/unsure)"])
        for r in sample:
            lbl = r["labels"]
            auto = "bug" if lbl["had_bug"] else ("security" if lbl["had_security_issue"] else "clean")
            reasons = "; ".join(
                url for group in lbl["reasons"].values() for url in group
            ) or "(none — aged out clean)"
            w.writerow([r["pr_id"], r["title"], auto, reasons, ""])
    print(f"wrote {len(sample)} rows to {out_csv} — fill in the last column by hand, "
          f"then run: python -m app.evals.dataset_builder audit-report")


def audit_report() -> None:
    path = Path("data/label_audit.csv")
    if not path.exists():
        print(f"{path} not found — run `audit` first, then fill in the human_label column.")
        return
    total = correct = filled = 0
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            human = row["human_label (bug/security/clean/unsure)"].strip().lower()
            if not human or human == "unsure":
                continue
            filled += 1
            auto = row["auto_label"].strip().lower()
            total += 1
            if human == auto or (human in ("bug", "security") and auto in ("bug", "security")):
                correct += 1
    if total == 0:
        print("No filled-in rows yet.")
        return
    print(f"Audited {total} labeled rows -> auto-labeling precision: {correct}/{total} = {correct/total:.1%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--repos", nargs="+", default=DEFAULT_REPOS)
    b.add_argument("--per-repo", type=int, default=50)
    b.add_argument("--min-age-days", type=int, default=MIN_AGE_DAYS)
    b.add_argument("--out", type=Path, default=DEFAULT_OUT)

    s = sub.add_parser("stats")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT)

    a = sub.add_parser("audit")
    a.add_argument("--n", type=int, default=30)
    a.add_argument("--out", type=Path, default=DEFAULT_OUT)

    sub.add_parser("audit-report")

    args = ap.parse_args()
    if args.cmd == "build":
        t0 = time.time()
        build(args.repos, args.per_repo, args.min_age_days, args.out)
        print(f"done in {time.time() - t0:.0f}s")
    elif args.cmd == "stats":
        stats(args.out)
    elif args.cmd == "audit":
        audit(args.out, args.n)
    elif args.cmd == "audit-report":
        audit_report()


if __name__ == "__main__":
    main()
