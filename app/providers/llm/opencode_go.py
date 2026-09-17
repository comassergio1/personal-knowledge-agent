"""OpenCode Go LLM adapter: configurable OpenAI-compatible endpoint.

OpenCode Go's provider has no published HTTP endpoint yet (recorded in the
vertical-slice feature doc), so this adapter is config-only: constructing it
without ``OPENCODE_GO_BASE_URL`` raises a clear ``LLMProviderError`` instead of
failing silently at call time.
"""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAIError

from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError


class OpenCodeGoProvider(LLMProvider):
    """Chat completions against a configurable OpenAI-compatible endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str, *, timeout: float = 300) -> None:
        if not base_url:
            raise LLMProviderError(
                "OpenCode Go adapter is config-only: OPENCODE_GO_BASE_URL is not set "
                "(the endpoint is not yet published). Configure it to use this provider."
            )
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        self._client: AsyncOpenAI | None = None

    @property
    def name(self) -> str:
        return "opencode_go"

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            try:
                self._client = AsyncOpenAI(
                    api_key=self._api_key, base_url=self._base_url, timeout=self._timeout
                )
            except OpenAIError as exc:
                raise LLMProviderError(
                    f"OpenCode Go client initialization failed: {exc}"
                ) from exc
        return self._client

    async def generate(
        self, messages: list[ChatMessage], *, model: str | None = None, **kwargs
    ) -> str:
        try:
            completion = await self._get_client().chat.completions.create(
                model=model or self._model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except OpenAIError as exc:
            raise LLMProviderError(f"OpenCode Go request failed: {exc}") from exc

        content = completion.choices[0].message.content
        if content is None:
            raise LLMProviderError("OpenCode Go returned an empty completion")
        return content

    async def close(self) -> None:
        """Close the OpenAI client when it was created (lazy init)."""
        if self._client is not None:
            await self._client.close()