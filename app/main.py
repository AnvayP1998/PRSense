"""PRSense FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.webhooks.github import router as github_webhook_router

settings = get_settings()
setup_logging(settings.log_level)
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("PRSense starting (env=%s)", settings.app_env)
    yield
    log.info("PRSense shutting down")


app = FastAPI(title="PRSense", version="0.1.0", lifespan=lifespan)
app.include_router(github_webhook_router)


@app.get("/")
async def root() -> dict:
    return {"service": "prsense", "version": "0.1.0"}


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "env": settings.app_env,
        "github_token_configured": bool(settings.github_token),
        "webhook_secret_configured": bool(settings.github_webhook_secret),
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=not settings.is_production,
    )


if __name__ == "__main__":
    run()
