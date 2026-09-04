"""GitHub webhook receiver for pull_request events."""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

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


def _run_review_background(pr_id: str, dry_run: bool) -> None:
    from app.agents.graph import run_review  # deferred: keep webhook import light

    try:
        state = run_review(pr_id, dry_run=dry_run)
        log.info(
            "review complete pr=%s model=%s findings=%d posted=%s",
            pr_id, state.get("model_used"),
            len(state.get("review", {}).get("findings", [])),
            state.get("comment_id"),
        )
    except Exception:  # noqa: BLE001 - background task; must not raise into the loop
        log.exception("background review failed for %s", pr_id)


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
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

    dry_run = not get_settings().auto_post_comments
    background_tasks.add_task(_run_review_background, f"{repo}#{number}", dry_run)

    return {"ok": True, "accepted": event, "review_dry_run": dry_run}
