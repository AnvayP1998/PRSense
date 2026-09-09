"""Phase 3 hands-on demo: run the full review agent against a REAL public PR.

  python scripts/phase3_demo.py                                # default PR
  python scripts/phase3_demo.py --pr pallets/flask#6145
  python scripts/phase3_demo.py --pr pallets/flask#6145 --post  # DANGER: posts a real comment

Requires GEMINI_API_KEY (and/or GROQ_API_KEY) in .env. Without one, this
prints the setup link and exits — the automated test suite (tests/test_agent_graph.py)
covers the graph's logic without any key.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows consoles default to cp1252; the review comment contains emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from app.agents.graph import run_review
from app.agents.llm import NoLLMAvailable
from app.core.config import get_settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", default="pallets/flask#6145", help="owner/repo#number")
    ap.add_argument("--post", action="store_true", help="actually post the comment to GitHub")
    args = ap.parse_args()

    settings = get_settings()
    if not settings.gemini_api_key and not settings.groq_api_key:
        print(
            "No LLM key configured.\n"
            "  Gemini (recommended, free): https://aistudio.google.com/apikey\n"
            "  Groq   (fallback, free):    https://console.groq.com/keys\n"
            "Add GEMINI_API_KEY and/or GROQ_API_KEY to .env and re-run."
        )
        raise SystemExit(1)

    print(f"Reviewing {args.pr}  (dry_run={not args.post}) ...")
    try:
        state = run_review(args.pr, dry_run=not args.post)
    except NoLLMAvailable as e:
        print(f"LLM call failed: {e}")
        raise SystemExit(1)

    print(f"\nmodel used: {state['model_used']}")
    print(f"findings:   {len(state['review']['findings'])}")
    print(f"risk:       {state['review']['overall_risk']}")
    print("\n" + "=" * 70)
    print(state["comment_body"])
    print("=" * 70)

    if args.post:
        print(f"\nPosted comment id={state['comment_id']} to {args.pr}")
    else:
        print("\n(dry run — nothing posted; re-run with --post to actually comment)")

    print("\nfull state (JSON):")
    print(json.dumps({k: v for k, v in state.items() if k != "pr"}, indent=2, default=str))


if __name__ == "__main__":
    main()
