"""OpenCode Go LLM adapter: OpenAI-compatible chat completions.

OpenCode Go exposes an OpenAI-compatible endpoint at
``https://opencode.ai/zen/go/v1`` (``/chat/completions``; the default model
``glm-5.3`` is documented there, while gpt-5.6-luna/grok-4.6 use the Responses
API and are out of scope). Per the provider's docs the adapter sends a stable
per-instance ``x-opencode-session`` header plus a distinctive User-Agent. The
API key comes from the environment (spec §27: keys are never stored in the
knowledge database) and its absence raises a clear error up front.
"""

from __future__ import annotations

import uuid

from openai import AsyncOpenAI, OpenAIError

from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError, LLMResult

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "glm-5.3"
USER_AGENT = "personal-knowledge-agent/0.1.0"


class OpenCodeGoProvider(LLMProvider):
    """Chat completions against OpenCode Go's OpenAI-compatible endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        timeout: float = 300,
        session_id: str | None = None,
    ) -> None:
        if not api_key:
            raise LLMProviderError(
                "OpenCode Go requires an API key: set OPENCODE_GO_API_KEY in the "
                "environment (spec §27: keys are never stored in the database)."
            )
        self._api_key = api_key
        self._base_url = base_url or DEFAULT_BASE_URL
        self._model = model or DEFAULT_MODEL
        self._timeout = timeout
        self._session_id = session_id or uuid.uuid4().hex
        self._client: AsyncOpenAI | None = None

    @property
    def name(self) -> str:
        return "opencode_go"

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            try:
                self._client = AsyncOpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    timeout=self._timeout,
                    default_headers={
                        "x-opencode-session": self._session_id,
                        "User-Agent": USER_AGENT,
                    },
                )
            except OpenAIError as exc:
                raise LLMProviderError(
                    f"OpenCode Go client initialization failed: {exc}"
                ) from exc
        return self._client

    async def generate(
        self, messages: list[ChatMessage], *, model: str | None = None, **kwargs
    ) -> LLMResult:
        effective_model = model or self._model
        try:
            completion = await self._get_client().chat.completions.create(
                model=effective_model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except OpenAIError as exc:
            raise LLMProviderError(f"OpenCode Go request failed: {exc}") from exc

        content = completion.choices[0].message.content
        if content is None:
            raise LLMProviderError("OpenCode Go returned an empty completion")

        usage = completion.usage
        return LLMResult(
            content=content,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
            provider="opencode_go",
            model=effective_model,
        )

    async def close(self) -> None:
        """Close the OpenAI client when it was created (lazy init)."""
        if self._client is not None:
            await self._client.close()