"""Unit tests for the Ollama LLM adapter (monkeypatched httpx, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.providers.llm.base import ChatMessage, LLMProviderError
from app.providers.llm.ollama import OllamaProvider


class FakeResponse:
    """Minimal httpx.Response stand-in exposing what the provider uses."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _provider() -> OllamaProvider:
    return OllamaProvider(base_url="http://ollama.test", model="gemma4:26b")


async def test_generate_returns_assistant_content(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(self, url: str, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse({"message": {"role": "assistant", "content": "hola"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    result = await provider.generate(
        [ChatMessage(role="user", content="hi")], model="llama3.1:latest"
    )

    assert result.content == "hola"
    assert result.provider == "ollama"
    assert result.model == "llama3.1:latest"
    assert captured["url"] == "/api/chat"
    assert captured["json"] == {
        "model": "llama3.1:latest",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }


async def test_generate_uses_default_model(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(self, url: str, **kwargs):
        captured["model"] = kwargs["json"]["model"]
        return FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    result = await provider.generate([ChatMessage(role="user", content="hi")])

    assert captured["model"] == "gemma4:26b"
    assert result.model == "gemma4:26b"


async def test_generate_parses_token_counts(monkeypatch) -> None:
    async def fake_post(self, url: str, **kwargs):
        return FakeResponse(
            {
                "message": {"role": "assistant", "content": "four words"},
                "prompt_eval_count": 42,
                "eval_count": 7,
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    result = await provider.generate([ChatMessage(role="user", content="hi")])

    assert result.prompt_tokens == 42
    assert result.completion_tokens == 7


async def test_generate_missing_counts_yield_none(monkeypatch) -> None:
    async def fake_post(self, url: str, **kwargs):
        return FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    result = await provider.generate([ChatMessage(role="user", content="hi")])

    assert result.prompt_tokens is None
    assert result.completion_tokens is None


async def test_generate_wraps_transport_errors(monkeypatch) -> None:
    async def fake_post(self, url: str, **kwargs):
        raise httpx.TransportError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    with pytest.raises(LLMProviderError, match="connection refused"):
        await provider.generate([ChatMessage(role="user", content="hi")])


async def test_generate_wraps_http_status_errors(monkeypatch) -> None:
    async def fake_post(self, url: str, **kwargs):
        response = FakeResponse({"error": "model not found"})
        response.status_code = 404

        def raise_for_status():
            raise httpx.HTTPStatusError(
                "Not Found", request=httpx.Request("POST", url), response=response
            )

        response.raise_for_status = raise_for_status
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    with pytest.raises(LLMProviderError, match="Not Found"):
        await provider.generate([ChatMessage(role="user", content="hi")])


async def test_generate_rejects_response_without_content(monkeypatch) -> None:
    async def fake_post(self, url: str, **kwargs):
        return FakeResponse({"message": {"role": "assistant"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _provider()
    with pytest.raises(LLMProviderError, match="message.content"):
        await provider.generate([ChatMessage(role="user", content="hi")])