"""Unit tests for the LLM provider factory (no network)."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.providers.llm.base import LLMProviderError
from app.providers.llm.factory import LLMProviderFactory
from app.providers.llm.ollama import OllamaProvider
from app.providers.llm.opencode_go import OpenCodeGoProvider
from app.providers.llm.payperq import PayPerQProvider


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_create_ollama() -> None:
    provider = LLMProviderFactory.create("ollama", _settings())
    assert isinstance(provider, OllamaProvider)


def test_create_payperq() -> None:
    provider = LLMProviderFactory.create("payperq", _settings(payperq_api_key="k"))
    assert isinstance(provider, PayPerQProvider)


def test_create_opencode_go() -> None:
    provider = LLMProviderFactory.create(
        "opencode_go", _settings(opencode_go_api_key="k")
    )
    assert isinstance(provider, OpenCodeGoProvider)
    assert provider._base_url == "https://opencode.ai/zen/go/v1"
    assert provider._model == "glm-5.3"


def test_create_normalizes_case_and_whitespace() -> None:
    provider = LLMProviderFactory.create("  OLLAMA ", _settings())
    assert isinstance(provider, OllamaProvider)


def test_create_unknown_provider_lists_valid_choices() -> None:
    with pytest.raises(LLMProviderError, match="ollama, payperq, opencode_go"):
        LLMProviderFactory.create("bogus", _settings())


def test_create_opencode_go_without_api_key_raises_clear_error() -> None:
    with pytest.raises(LLMProviderError, match="OPENCODE_GO_API_KEY"):
        LLMProviderFactory.create("opencode_go", _settings())