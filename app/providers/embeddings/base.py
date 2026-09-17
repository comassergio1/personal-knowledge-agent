"""Embedding provider contracts (spec §6)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProviderError(Exception):
    """Raised when an embedding provider cannot serve a request."""


class EmbeddingProvider(ABC):
    """Abstract contract every embedding adapter implements."""

    #: Vector width produced by this provider's model (nomic-embed-text: 768).
    EMBEDDING_SIZE = 0

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed ``text`` into a fixed-size vector."""