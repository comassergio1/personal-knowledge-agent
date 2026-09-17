"""Ollama embedding adapter: embeddings against a local server.

Talks to ``POST /api/embed`` with ``{"model": ..., "input": text}`` and returns
``embeddings[0]`` (a single input yields a single vector).
"""

from __future__ import annotations

import httpx

from app.providers.embeddings.base import EmbeddingProvider, EmbeddingProviderError


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embeddings from a local Ollama server (nomic-embed-text)."""

    EMBEDDING_SIZE = 768

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url
        self._model = model
        self._client = httpx.AsyncClient(base_url=base_url)

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._client.post(
                "/api/embed", json={"model": self._model, "input": text}
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise EmbeddingProviderError(
                f"Ollama embedding request failed: {exc}"
            ) from exc
        except ValueError as exc:
            raise EmbeddingProviderError(
                f"Ollama returned an invalid response: {exc}"
            ) from exc

        embeddings = data.get("embeddings") if isinstance(data, dict) else None
        if not embeddings:
            raise EmbeddingProviderError(
                "Ollama embedding response missing embeddings"
            )
        return embeddings[0]

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()