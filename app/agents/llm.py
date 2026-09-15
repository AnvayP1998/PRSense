"""LLM access: Gemini primary, Groq fallback. Both free-tier, no paid APIs.

`review_with_fallback` tries Gemini first (quota errors, timeouts, or an
unset key all trigger fallback), then Groq. Raises only if neither is usable.
"""
from __future__ import annotations

from app.agents.schema import ReviewResult
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class NoLLMAvailable(RuntimeError):
    pass


def _gemini_structured():
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.1,
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

    if provider in ("auto", "gemini"):
        gemini = _gemini_structured()
        if gemini is not None:
            try:
                return gemini.invoke(messages), f"gemini:{settings.gemini_model}"
            except Exception as e:  # noqa: BLE001 - deliberately broad: any failure -> fallback
                log.warning("Gemini call failed (%s)", e)
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
