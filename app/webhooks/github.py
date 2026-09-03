"""GitHub webhook receiver for pull_request events."""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])

# "opened" = new PR, "synchronize" = new commits pushed to the PR branch.
HANDLED_ACTIONS = {"opened", "synchronize", "reopened"}


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    secret = get_settings().github_webhook_secret
    if not secret:
        log.warning("GITHUB_WEBHOOK_SECRET unset - skipping signature check")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str = Header(default=""),
) -> dict:
    body = await request.body()

    if not _verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")

    log.info("event=%s delivery=%s", x_github_event, x_github_delivery)

    if x_github_event == "ping":
        return {"ok": True, "pong": True}

    if x_github_event != "pull_request":
        return {"ok": True, "ignored": f"event {x_github_event!r}"}

    action = payload.get("action", "")
    if action not in HANDLED_ACTIONS:
        return {"ok": True, "ignored": f"action {action!r}"}

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {}).get("full_name", "")
    number = pr.get("number")

    event = {
        "repo": repo,
        "number": number,
        "action": action,
        "head_sha": pr.get("head", {}).get("sha"),
        "title": pr.get("title"),
    }
    log.info("queued review: %s#%s (%s)", repo, number, action)

    # Phase 3 wires this into the LangGraph agent (background task / queue).
    # For Phase 1 we just acknowledge receipt.
    return {"ok": True, "accepted": event}
