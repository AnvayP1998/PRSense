"""LangSmith tracing setup (free tier: https://smith.langchain.com).

LangChain/LangGraph/`@traceable` all read tracing config from process env
vars, not from our Settings object directly — this bridges the two, once,
at process start. No-op (and no network calls) if LANGSMITH_TRACING=false
or no API key is set, so the app runs fully offline by default.
"""
from __future__ import annotations

import os

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_CONFIGURED = False


def setup_tracing() -> bool:
    global _CONFIGURED
    if _CONFIGURED:
        return os.environ.get("LANGSMITH_TRACING") == "true"

    settings = get_settings()
    enabled = settings.langsmith_tracing and bool(settings.langsmith_api_key)

    os.environ["LANGSMITH_TRACING"] = "true" if enabled else "false"
    if enabled:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        log.info("LangSmith tracing ON (project=%s)", settings.langsmith_project)
    else:
        log.info("LangSmith tracing OFF (set LANGSMITH_TRACING=true + LANGSMITH_API_KEY to enable)")

    _CONFIGURED = True
    return enabled
