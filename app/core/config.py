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

    # OpenCode Go (OpenAI-compatible endpoint; flat $10/mo subscription)
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"
    opencode_go_api_key: str = ""
    opencode_go_model: str = "glm-5.3"

    # Cost rates in USD per 1k tokens (input/output) for §30 token accounting.
    # Ollama is local/free and OpenCode Go is a flat $10/mo subscription, so
    # their rates stay 0; PayPerQ rates are set by the user to real billing.
    ollama_usd_per_1k_in: float = 0.0
    ollama_usd_per_1k_out: float = 0.0
    payperq_usd_per_1k_in: float = 0.0
    payperq_usd_per_1k_out: float = 0.0
    opencode_go_usd_per_1k_in: float = 0.0
    opencode_go_usd_per_1k_out: float = 0.0

    # Embedding provider and model
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    # Bootstrap dimensionality for the Qdrant collection (nomic-embed-text).
    embedding_dimensions: int = 768

    # HTTP timeout for LLM calls (seconds): local models need generous timeouts.
    llm_timeout_seconds: int = 300

    # Document chunking defaults for ingestion (see app.services.chunking).
    chunk_size: int = 1000
    chunk_overlap: int = 120


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings singleton."""
    return Settings()