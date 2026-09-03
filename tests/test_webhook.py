"""Phase 1 tests: webhook signature verification + event routing."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "github_webhook_secret", "testsecret")
    yield


def _post(payload: dict, event: str, secret: str = "testsecret"):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": "test-1",
            "X-Hub-Signature-256": _sign(body, secret),
        },
    )


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_rejects_bad_signature():
    body = json.dumps({"zen": "hi"}).encode()
    r = client.post(
        "/webhook/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 401


def test_ping():
    r = _post({"zen": "keep it simple"}, "ping")
    assert r.status_code == 200
    assert r.json()["pong"] is True


def test_pull_request_opened_accepted():
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "Add feature",
            "head": {"sha": "abc123"},
        },
        "repository": {"full_name": "octo/repo"},
    }
    r = _post(payload, "pull_request")
    assert r.status_code == 200
    data = r.json()["accepted"]
    assert data["repo"] == "octo/repo"
    assert data["number"] == 42
    assert data["action"] == "opened"


def test_pull_request_closed_ignored():
    payload = {
        "action": "closed",
        "pull_request": {"number": 1, "head": {"sha": "x"}},
        "repository": {"full_name": "octo/repo"},
    }
    r = _post(payload, "pull_request")
    assert r.status_code == 200
    assert "ignored" in r.json()
