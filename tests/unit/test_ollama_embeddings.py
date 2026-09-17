"""Unit tests for the Ollama embedding adapter (monkeypatched httpx, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.providers.embeddings.base import EmbeddingProviderError
from app.providers.embeddings.ollama import OllamaEmbeddingProvider


class FakeResponse:
    """Minimal httpx.Response stand-in exposing what the provider uses."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _provider() -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider(
        base_url="http://ollama.test", model="nomic-embed-text"
    )


async def test_embed_returns_first_vector(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(self, url: str, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse({"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    vector = await provider.embed("hello world")

    assert vector == [0.1, 0.2, 0.3]
    assert provider.EMBEDDING_SIZE == 768
    assert captured["url"] == "/api/embed"
    assert captured["json"] == {"model": "nomic-embed-text", "input": "hello world"}


async def test_embed_wraps_transport_errors(monkeypatch) -> None:
    async def fake_post(self, url: str, **kwargs):
        raise httpx.TransportError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    with pytest.raises(EmbeddingProviderError, match="connection refused"):
        await provider.embed("hello")


async def test_embed_rejects_missing_embeddings(monkeypatch) -> None:
    async def fake_post(self, url: str, **kwargs):
        return FakeResponse({"embeddings": []})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    with pytest.raises(EmbeddingProviderError, match="missing embeddings"):
        await provider.embed("hello")