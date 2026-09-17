"""Unit tests for the OpenAI-compatible LLM adapters (PayPerQ, OpenCode Go).

``AsyncOpenAI`` is monkeypatched in the adapter modules, so no network is ever
touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from openai import APIError, OpenAIError

from app.providers.llm import opencode_go as opencode_go_module
from app.providers.llm import payperq as payperq_module
from app.providers.llm.base import ChatMessage, LLMProviderError
from app.providers.llm.opencode_go import OpenCodeGoProvider
from app.providers.llm.payperq import PayPerQProvider

_last_call: dict = {}


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    async def create(self, **kwargs):
        _last_call.update(kwargs)
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeOpenAI:
    def __init__(self, **kwargs) -> None:
        _last_call.update(client_kwargs=kwargs)
        self.chat = SimpleNamespace(completions=_FakeCompletions("assistant-answer"))


class _RaisingCompletions:
    async def create(self, **kwargs):
        raise APIError("boom", request=None, body=None)


class _RaisingOpenAI:
    def __init__(self, **kwargs) -> None:
        self.chat = SimpleNamespace(completions=_RaisingCompletions())


class _MissingCredentialsOpenAI:
    def __init__(self, **kwargs) -> None:
        raise OpenAIError("Missing credentials. Please pass an api_key.")


async def test_payperq_generate_maps_messages(monkeypatch) -> None:
    monkeypatch.setattr(payperq_module, "AsyncOpenAI", _FakeOpenAI)
    provider = PayPerQProvider(
        api_key="k", base_url="https://api.ppq.ai/v1", model="ppq-model"
    )

    content = await provider.generate([ChatMessage(role="user", content="hi")])
    messages = [{"role": "user", "content": "hi"}]

    assert content == "assistant-answer"
    assert _last_call["model"] == "ppq-model"
    assert _last_call["messages"] == messages


async def test_payperq_generate_model_override(monkeypatch) -> None:
    monkeypatch.setattr(payperq_module, "AsyncOpenAI", _FakeOpenAI)
    provider = PayPerQProvider(
        api_key="k", base_url="https://api.ppq.ai/v1", model="default-model"
    )

    await provider.generate(
        [ChatMessage(role="user", content="hi")], model="override-model"
    )

    assert _last_call["model"] == "override-model"


async def test_payperq_generate_wraps_api_errors(monkeypatch) -> None:
    monkeypatch.setattr(payperq_module, "AsyncOpenAI", _RaisingOpenAI)
    provider = PayPerQProvider(
        api_key="k", base_url="https://api.ppq.ai/v1", model="ppq-model"
    )

    with pytest.raises(LLMProviderError, match="boom"):
        await provider.generate([ChatMessage(role="user", content="hi")])


async def test_payperq_generate_wraps_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr(payperq_module, "AsyncOpenAI", _MissingCredentialsOpenAI)
    provider = PayPerQProvider(
        api_key="", base_url="https://api.ppq.ai/v1", model="ppq-model"
    )

    with pytest.raises(LLMProviderError, match="Missing credentials"):
        await provider.generate([ChatMessage(role="user", content="hi")])


async def test_opencode_go_generate_maps_messages(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _FakeOpenAI)
    provider = OpenCodeGoProvider(
        api_key="k", base_url="http://localhost:9999", model="go-model"
    )

    content = await provider.generate(
        [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="hi")]
    )

    assert content == "assistant-answer"
    assert _last_call["model"] == "go-model"
    assert _last_call["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]


async def test_opencode_go_generate_wraps_api_errors(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _RaisingOpenAI)
    provider = OpenCodeGoProvider(
        api_key="k", base_url="http://localhost:9999", model="go-model"
    )

    with pytest.raises(LLMProviderError, match="boom"):
        await provider.generate([ChatMessage(role="user", content="hi")])


def test_opencode_go_without_base_url_raises_clear_error() -> None:
    with pytest.raises(LLMProviderError, match="config-only"):
        OpenCodeGoProvider(api_key="k", base_url="", model="go-model")