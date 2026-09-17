"""Application settings loaded from environment variables and `.env`.

Each field maps 1:1 to a name documented in `env.template` (spec §27; the name is distinct from the gitignored `.env` to avoid the sensitive `.env*` pattern).
API keys are never stored in the knowledge database; they exist only in the
runtime environment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Runtime environment: development | test | production
    app_env: str = "development"

    # SQLAlchemy async database URL; all user knowledge lives under data/.
    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # Qdrant vector store (see docker-compose.yml)
    qdrant_url: str = "http://localhost:6333"

    # LLM provider and model. Swapping LLM_PROVIDER must not change domain code.
    llm_provider: str = "ollama"
    llm_model: str = "gemma4:26b"
    ollama_base_url: str = "http://localhost:11434"

    # PayPerQ (OpenAI-compatible provider)
    payperq_base_url: str = "https://api.ppq.ai/v1"
    payperq_api_key: str = ""

    # Opencode Go (configurable OpenAI-compatible adapter)
    opencode_go_base_url: str = ""
    opencode_go_api_key: str = ""
    opencode_go_model: str = ""

    # Embedding provider and model
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings singleton."""
    return Settings()