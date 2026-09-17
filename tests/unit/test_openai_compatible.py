"""Unit tests for the OpenAI-compatible LLM adapters (PayPerQ, OpenCode Go).

``AsyncOpenAI`` is monkeypatched in the adapter modules, so no network is ever
touched.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from openai import APIError, OpenAIError

from app.providers.llm import opencode_go as opencode_go_module
from app.providers.llm import payperq as payperq_module
from app.providers.llm.base import ChatMessage, LLMProviderError
from app.providers.llm.opencode_go import USER_AGENT, OpenCodeGoProvider
from app.providers.llm.payperq import PayPerQProvider

_last_call: dict = {}

_USAGE = {"prompt_tokens": 12, "completion_tokens": 7}


class _FakeCompletions:
    def __init__(self, content: str, usage: dict | None = None) -> None:
        self._content = content
        self._usage = usage

    async def create(self, **kwargs):
        _last_call.update(kwargs)
        message = SimpleNamespace(content=self._content)
        usage = SimpleNamespace(**self._usage) if self._usage is not None else None
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)], usage=usage
        )


class _FakeOpenAI:
    def __init__(self, **kwargs) -> None:
        _last_call.update(client_kwargs=kwargs)
        self.chat = SimpleNamespace(completions=_FakeCompletions("assistant-answer"))


class _UsageOpenAI:
    def __init__(self, **kwargs) -> None:
        _last_call.update(client_kwargs=kwargs)
        self.chat = SimpleNamespace(
            completions=_FakeCompletions("assistant-answer", usage=_USAGE)
        )


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

    result = await provider.generate([ChatMessage(role="user", content="hi")])
    messages = [{"role": "user", "content": "hi"}]

    assert result.content == "assistant-answer"
    assert result.provider == "payperq"
    assert result.model == "ppq-model"
    assert _last_call["model"] == "ppq-model"
    assert _last_call["messages"] == messages


async def test_payperq_generate_model_override(monkeypatch) -> None:
    monkeypatch.setattr(payperq_module, "AsyncOpenAI", _FakeOpenAI)
    provider = PayPerQProvider(
        api_key="k", base_url="https://api.ppq.ai/v1", model="default-model"
    )

    result = await provider.generate(
        [ChatMessage(role="user", content="hi")], model="override-model"
    )

    assert _last_call["model"] == "override-model"
    assert result.model == "override-model"


async def test_payperq_generate_parses_usage_tokens(monkeypatch) -> None:
    monkeypatch.setattr(payperq_module, "AsyncOpenAI", _UsageOpenAI)
    provider = PayPerQProvider(
        api_key="k", base_url="https://api.ppq.ai/v1", model="ppq-model"
    )

    result = await provider.generate([ChatMessage(role="user", content="hi")])

    assert result.prompt_tokens == 12
    assert result.completion_tokens == 7


async def test_payperq_generate_usage_missing_yields_none(monkeypatch) -> None:
    monkeypatch.setattr(payperq_module, "AsyncOpenAI", _FakeOpenAI)
    provider = PayPerQProvider(
        api_key="k", base_url="https://api.ppq.ai/v1", model="ppq-model"
    )

    result = await provider.generate([ChatMessage(role="user", content="hi")])

    assert result.prompt_tokens is None
    assert result.completion_tokens is None


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

    result = await provider.generate(
        [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="hi")]
    )

    assert result.content == "assistant-answer"
    assert result.provider == "opencode_go"
    assert result.model == "go-model"
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


async def test_opencode_go_parses_usage_tokens(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _UsageOpenAI)
    provider = OpenCodeGoProvider(
        api_key="k", base_url="http://localhost:9999", model="go-model"
    )

    result = await provider.generate([ChatMessage(role="user", content="hi")])

    assert result.prompt_tokens == 12
    assert result.completion_tokens == 7


async def test_opencode_go_usage_missing_yields_none(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _FakeOpenAI)
    provider = OpenCodeGoProvider(
        api_key="k", base_url="http://localhost:9999", model="go-model"
    )

    result = await provider.generate([ChatMessage(role="user", content="hi")])

    assert result.prompt_tokens is None
    assert result.completion_tokens is None


async def test_opencode_go_empty_config_resolves_documented_defaults(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _FakeOpenAI)
    provider = OpenCodeGoProvider(api_key="k", base_url="", model="")

    await provider.generate([ChatMessage(role="user", content="hi")])

    assert _last_call["client_kwargs"]["base_url"] == "https://opencode.ai/zen/go/v1"
    assert _last_call["model"] == "glm-5.3"


async def test_opencode_go_sends_session_and_user_agent_headers(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _FakeOpenAI)
    provider = OpenCodeGoProvider(
        api_key="k", base_url="http://localhost:9999", model="go-model"
    )

    await provider.generate([ChatMessage(role="user", content="hi")])

    headers = _last_call["client_kwargs"]["default_headers"]
    session = headers["x-opencode-session"]
    assert isinstance(session, str) and len(session) == 32
    int(session, 16)  # a valid uuid4 hex
    assert headers["User-Agent"] == USER_AGENT


async def test_opencode_go_session_id_override(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _FakeOpenAI)
    provider = OpenCodeGoProvider(
        api_key="k",
        base_url="http://localhost:9999",
        model="go-model",
        session_id="fixed-session",
    )

    await provider.generate([ChatMessage(role="user", content="hi")])

    headers = _last_call["client_kwargs"]["default_headers"]
    assert headers["x-opencode-session"] == "fixed-session"


async def test_opencode_go_session_is_stable_across_calls(monkeypatch) -> None:
    monkeypatch.setattr(opencode_go_module, "AsyncOpenAI", _FakeOpenAI)
    provider = OpenCodeGoProvider(
        api_key="k", base_url="http://localhost:9999", model="go-model"
    )

    await provider.generate([ChatMessage(role="user", content="hi")])
    first_session = _last_call["client_kwargs"]["default_headers"]["x-opencode-session"]
    first_client = _last_call["client_kwargs"]

    await provider.generate([ChatMessage(role="user", content="again")])
    second_session = _last_call["client_kwargs"]["default_headers"]["x-opencode-session"]
    second_client = _last_call["client_kwargs"]

    assert first_client is second_client  # lazy client is reused
    assert first_session == second_session


def test_opencode_go_without_api_key_raises_clear_error() -> None:
    with pytest.raises(LLMProviderError, match=re.escape("OPENCODE_GO_API_KEY")):
        OpenCodeGoProvider(api_key="", base_url="", model="")