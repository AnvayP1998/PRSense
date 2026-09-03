"""Send a correctly-signed fake GitHub PR webhook to a running PRSense server.

  python scripts/send_test_webhook.py                       # defaults
  python scripts/send_test_webhook.py --repo pallets/flask --number 6145 --action synchronize
  python scripts/send_test_webhook.py --url http://localhost:8000/webhook/github

The secret is read from GITHUB_WEBHOOK_SECRET (env or .env); if unset the
server skips verification and any signature is accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path

import httpx

sys_path = str(Path(__file__).resolve().parent.parent)


def _load_secret() -> str:
    if os.getenv("GITHUB_WEBHOOK_SECRET"):
        return os.environ["GITHUB_WEBHOOK_SECRET"]
    env = Path(sys_path) / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GITHUB_WEBHOOK_SECRET="):
                return line.split("=", 1)[1].strip()
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/webhook/github")
    ap.add_argument("--repo", default="pallets/flask")
    ap.add_argument("--number", type=int, default=6145)
    ap.add_argument("--action", default="opened",
                    choices=["opened", "synchronize", "reopened", "closed"])
    ap.add_argument("--title", default="Test PR from send_test_webhook.py")
    args = ap.parse_args()

    payload = {
        "action": args.action,
        "pull_request": {
            "number": args.number,
            "title": args.title,
            "head": {"sha": "deadbeef"},
        },
        "repository": {"full_name": args.repo},
    }
    body = json.dumps(payload).encode()

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "local-test",
    }
    secret = _load_secret()
    if secret:
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()

    resp = httpx.post(args.url, content=body, headers=headers, timeout=15)
    print(resp.status_code, resp.text)


if __name__ == "__main__":
    main()
