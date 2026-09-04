"""Central configuration, loaded from environment / .env once at import time."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "local"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # GitHub
    github_token: str = ""
    github_webhook_secret: str = ""

    # LLMs
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Storage
    database_url: str = ""
    sqlite_path: str = "./data/prsense.db"
    supabase_url: str = ""
    supabase_key: str = ""

    # Vector store
    chroma_persist_dir: str = "./data/chroma"

    # Tracing
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "prsense"

    # Agent
    auto_post_comments: bool = False  # safety default: never write to real PRs unasked

    @property
    def effective_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.sqlite_path}"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
