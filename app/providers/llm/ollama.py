"""Ollama LLM adapter: chat completions against a local server.

Talks to ``POST /api/chat`` with ``"stream": false`` and returns the assistant
``message.content``. The httpx base URL is the only constructor value that is
not read straight from ``Settings``; the factory passes
``settings.ollama_base_url``.
"""

from __future__ import annotations

import httpx

from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError


class OllamaProvider(LLMProvider):
    """Chat completions from a local Ollama server."""

    def __init__(self, base_url: str, model: str, *, timeout: float = 300) -> None:
        self._base_url = base_url
        self._model = model
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    @property
    def name(self) -> str:
        return "ollama"

    async def generate(
        self, messages: list[ChatMessage], *, model: str | None = None, **kwargs
    ) -> str:
        payload = {
            "model": model or self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
        }
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Ollama request failed: {exc}") from exc
        except ValueError as exc:
            raise LLMProviderError(f"Ollama returned an invalid response: {exc}") from exc

        message = data.get("message") if isinstance(data, dict) else None
        if not message or not message.get("content"):
            raise LLMProviderError("Ollama response missing message.content")
        return message["content"]

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()