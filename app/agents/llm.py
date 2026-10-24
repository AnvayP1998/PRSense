"""LLM access: Gemini primary, Groq fallback. Both free-tier, no paid APIs.

`review_with_fallback` tries Gemini first (quota errors, timeouts, or an
unset key all trigger fallback), then Groq. Raises only if neither is usable.

A short-lived in-process circuit breaker skips Gemini once it's seen to be
quota-exhausted for the day, rather than re-attempting (and retrying with
backoff, ~20-30s wasted) on every single subsequent call in "auto" mode --
found by watching exactly that happen during a live Phase 4 eval run.
"""
from __future__ import annotations

import re
import time

from app.agents.schema import ReviewResult
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)")
_DEFAULT_COOLDOWN_SECONDS = 3600  # fallback if a quota error doesn't carry a parseable retryDelay

_gemini_blocked_until: float = 0.0  # epoch seconds; 0 = not blocked


class NoLLMAvailable(RuntimeError):
    pass


def _looks_like_quota_exhaustion(exc: Exception) -> bool:
    msg = str(exc)
    return "RESOURCE_EXHAUSTED" in msg or "429" in msg


def _block_gemini_for(exc: Exception) -> None:
    global _gemini_blocked_until
    m = _RETRY_DELAY_RE.search(str(exc))
    cooldown = float(m.group(1)) if m else _DEFAULT_COOLDOWN_SECONDS
    _gemini_blocked_until = time.time() + cooldown
    log.warning("Gemini looks quota-exhausted; skipping it for the next %.0fs", cooldown)


def _gemini_structured():
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.1,
        max_retries=1,  # don't burn 20-30s of backoff on a quota error we can't out-wait
    )
    return llm.with_structured_output(ReviewResult)


def _groq_structured():
    settings = get_settings()
    if not settings.groq_api_key:
        return None
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0.1,
    )
    return llm.with_structured_output(ReviewResult)


def review_with_fallback(messages: list, *, provider: str = "auto") -> tuple[ReviewResult, str]:
    """Returns (result, model_name_used).

    provider: "auto" (Gemini then Groq fallback, the production default),
    "gemini", or "groq" (force one — used by the eval harness's A/B runs to
    measure each model in isolation, without a silent fallback muddying the
    comparison).
    """
    settings = get_settings()

    gemini_skipped_by_breaker = (
        provider == "auto" and time.time() < _gemini_blocked_until
    )
    if provider in ("auto", "gemini") and not gemini_skipped_by_breaker:
        gemini = _gemini_structured()
        if gemini is not None:
            try:
                return gemini.invoke(messages), f"gemini:{settings.gemini_model}"
            except Exception as e:  # noqa: BLE001 - deliberately broad: any failure -> fallback
                log.warning("Gemini call failed (%s)", e)
                if _looks_like_quota_exhaustion(e):
                    _block_gemini_for(e)
                if provider == "gemini":
                    raise NoLLMAvailable(f"Gemini failed: {e}") from e
        elif provider == "gemini":
            raise NoLLMAvailable("GEMINI_API_KEY not set.")

    if provider in ("auto", "groq"):
        groq = _groq_structured()
        if groq is not None:
            try:
                return groq.invoke(messages), f"groq:{settings.groq_model}"
            except Exception as e:  # noqa: BLE001
                log.error("Groq call failed: %s", e)
                raise NoLLMAvailable(f"Groq failed: {e}") from e
        elif provider == "groq":
            raise NoLLMAvailable("GROQ_API_KEY not set.")

    raise NoLLMAvailable(
        "No LLM configured. Set GEMINI_API_KEY (https://aistudio.google.com/apikey) "
        "and/or GROQ_API_KEY (https://console.groq.com/keys) in .env."
    )
