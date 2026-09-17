"""LLM provider factory: maps ``LLM_PROVIDER`` names to adapters.

The factory is the only code that reads provider values from ``Settings``;
adapters receive plain values. Swapping providers never touches domain code
(spec §5).
"""

from __future__ import annotations

from app.core.config import Settings
from app.providers.llm.base import LLMProvider, LLMProviderError
from app.providers.llm.ollama import OllamaProvider
from app.providers.llm.opencode_go import OpenCodeGoProvider
from app.providers.llm.payperq import PayPerQProvider


class LLMProviderFactory:
    """Builds an ``LLMProvider`` instance for a configured provider name."""

    @staticmethod
    def create(provider: str, settings: Settings) -> LLMProvider:
        name = provider.strip().lower()
        if name == "ollama":
            return OllamaProvider(
                base_url=settings.ollama_base_url,
                model=settings.llm_model,
                timeout=settings.llm_timeout_seconds,
            )
        if name == "payperq":
            return PayPerQProvider(
                api_key=settings.payperq_api_key,
                base_url=settings.payperq_base_url,
                model=settings.llm_model,
                timeout=settings.llm_timeout_seconds,
            )
        if name == "opencode_go":
            return OpenCodeGoProvider(
                api_key=settings.opencode_go_api_key,
                base_url=settings.opencode_go_base_url,
                model=settings.opencode_go_model,
                timeout=settings.llm_timeout_seconds,
            )
        raise LLMProviderError(
            f"Unknown LLM provider {provider!r}; valid choices: ollama, payperq, opencode_go"
        )