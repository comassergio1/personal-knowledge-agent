"""PayPerQ LLM adapter: OpenAI-compatible chat completions (spec §3).

The OpenAI client is created lazily on the first ``generate`` call so that
constructing the provider (for example during an ``LLM_PROVIDER`` swap) never
fails because the API key is not set yet; missing credentials surface as a
clear ``LLMProviderError`` at call time.
"""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAIError

from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError


class PayPerQProvider(LLMProvider):
    """Chat completions against PayPerQ's OpenAI-compatible endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str, *, timeout: float = 300) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        self._client: AsyncOpenAI | None = None

    @property
    def name(self) -> str:
        return "payperq"

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            try:
                self._client = AsyncOpenAI(
                    api_key=self._api_key, base_url=self._base_url, timeout=self._timeout
                )
            except OpenAIError as exc:
                raise LLMProviderError(
                    f"PayPerQ client initialization failed: {exc}"
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
            raise LLMProviderError(f"PayPerQ request failed: {exc}") from exc

        content = completion.choices[0].message.content
        if content is None:
            raise LLMProviderError("PayPerQ returned an empty completion")
        return content