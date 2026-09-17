"""Embedding provider factory: maps ``EMBEDDING_PROVIDER`` names to adapters."""

from __future__ import annotations

from app.core.config import Settings
from app.providers.embeddings.base import EmbeddingProvider, EmbeddingProviderError
from app.providers.embeddings.ollama import OllamaEmbeddingProvider


class EmbeddingProviderFactory:
    """Builds an ``EmbeddingProvider`` instance for a configured provider name."""

    @staticmethod
    def create(provider: str, settings: Settings) -> EmbeddingProvider:
        name = provider.strip().lower()
        if name == "ollama":
            return OllamaEmbeddingProvider(
                base_url=settings.ollama_base_url, model=settings.embedding_model
            )
        raise EmbeddingProviderError(
            f"Unknown embedding provider {provider!r}; valid choices: ollama"
        )