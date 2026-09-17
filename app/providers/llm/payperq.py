"""PayPerQ LLM adapter: OpenAI-compatible chat completions (spec §3).

The OpenAI client is created lazily on the first ``generate`` call so that
constructing the provider (for example during an ``LLM_PROVIDER`` swap) never
fails because the API key is not set yet; missing credentials surface as a
clear ``LLMProviderError`` at call time. Token usage is parsed from
``completion.usage`` when the endpoint reports it (spec §30).
"""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAIError

from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError, LLMResult


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
    ) -> LLMResult:
        effective_model = model or self._model
        try:
            completion = await self._get_client().chat.completions.create(
                model=effective_model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except OpenAIError as exc:
            raise LLMProviderError(f"PayPerQ request failed: {exc}") from exc

        content = completion.choices[0].message.content
        if content is None:
            raise LLMProviderError("PayPerQ returned an empty completion")

        usage = completion.usage
        return LLMResult(
            content=content,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
            provider="payperq",
            model=effective_model,
        )

    async def close(self) -> None:
        """Close the OpenAI client when it was created (lazy init)."""
        if self._client is not None:
            await self._client.close()