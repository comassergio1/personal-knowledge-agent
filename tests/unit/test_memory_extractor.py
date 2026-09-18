"""Unit tests for MemoryExtractor (fake LLM, lenient parsing, offline)."""

from __future__ import annotations

import json

import pytest

from app.providers.llm.base import LLMProviderError, LLMResult
from app.schemas.memory import ConversationTurn
from app.services.memory_extractor import MemoryExtractionError, MemoryExtractor


class FakeLLM:
    """Returns a canned reply and records the messages/model it received."""

    name = "fake-extractor-llm"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list | None = None
        self.requested_model: str | None = None

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        self.messages = list(messages)
        self.requested_model = model
        return LLMResult(
            content=self.content,
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-extractor-llm",
            model="test-model",
        )


class FailingLLM(FakeLLM):
    """Raises the provider error contract so wrapping can be exercised."""

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        raise LLMProviderError("provider unreachable")


def _conversation() -> list[ConversationTurn]:
    return [
        ConversationTurn(role="user", content="my password is hunter2"),
        ConversationTurn(role="assistant", content="got it, storing that."),
    ]


def _extractor(llm: FakeLLM) -> MemoryExtractor:
    return MemoryExtractor(llm)  # type: ignore[arg-type]


async def test_extract_parses_fenced_json() -> None:
    llm = FakeLLM(
        "```json\n"
        '[{"type": "semantic", "content": "The user prefers concise answers", '
        '"confidence": 0.9, "source": "conversation"}]\n'
        "```"
    )

    candidates = await _extractor(llm).extract(_conversation())

    assert candidates == [
        {
            "type": "semantic",
            "content": "The user prefers concise answers",
            "confidence": 0.9,
            "source": "conversation",
        }
    ]


async def test_extract_parses_plain_json_array() -> None:
    llm = FakeLLM(
        json.dumps([{"type": "preference", "content": "Prefers tea", "confidence": 0.5}])
    )

    candidates = await _extractor(llm).extract(_conversation())

    assert candidates == [
        {"type": "preference", "content": "Prefers tea", "confidence": 0.5}
    ]


async def test_extract_falls_back_to_single_object_when_no_array() -> None:
    llm = FakeLLM(
        "Here are the memories: "
        '{"type": "episodic", "content": "Went hiking on Sunday", "confidence": 0.7}'
    )

    candidates = await _extractor(llm).extract(_conversation())

    assert candidates == [
        {"type": "episodic", "content": "Went hiking on Sunday", "confidence": 0.7}
    ]


async def test_extract_filters_invalid_types_and_blank_content() -> None:
    raw = [
        {"type": "semantic", "content": "kept", "confidence": 0.6},
        {"type": "bogus", "content": "dropped type", "confidence": 0.9},
        {"type": "preference", "content": "", "confidence": 0.9},
        {"type": "procedural", "content": 42, "confidence": 0.9},
        "not a dict",
    ]
    llm = FakeLLM(json.dumps(raw))

    candidates = await _extractor(llm).extract(_conversation())

    assert candidates == [{"type": "semantic", "content": "kept", "confidence": 0.6}]


async def test_extract_clamps_and_defaults_confidence() -> None:
    raw = [
        {"type": "semantic", "content": "too high", "confidence": 2.5},
        {"type": "semantic", "content": "too low", "confidence": -1.0},
        {"type": "semantic", "content": "missing"},
        {"type": "semantic", "content": "garbage", "confidence": "certainly"},
    ]
    llm = FakeLLM(json.dumps(raw))

    candidates = await _extractor(llm).extract(_conversation())

    assert [c["confidence"] for c in candidates] == [1.0, 0.0, 0.5, 0.5]


async def test_extract_nothing_usable_warns_and_returns_empty(caplog) -> None:
    llm = FakeLLM("I found no memories here.")

    assert await _extractor(llm).extract(_conversation()) == []

    records = [r for r in caplog.records if r.name == "memory_extractor"]
    assert len(records) == 1
    assert "no usable memory candidates" in records[0].getMessage()


async def test_extract_unparseable_reply_returns_empty_without_raising() -> None:
    llm = FakeLLM('[{"type": "semantic"')

    assert await _extractor(llm).extract(_conversation()) == []


async def test_extract_sends_system_and_user_messages_with_model_none() -> None:
    llm = FakeLLM("[]")
    await _extractor(llm).extract(_conversation())

    assert llm.requested_model is None
    assert llm.messages is not None
    assert len(llm.messages) == 2
    system, user = llm.messages
    assert system.role == "system"
    assert "memory" in system.content.lower()
    assert "Output ONLY a JSON array" in system.content
    assert user.role == "user"
    assert "user: my password is hunter2" in user.content
    assert "assistant: got it, storing that." in user.content


async def test_extract_wraps_llm_errors() -> None:
    with pytest.raises(MemoryExtractionError):
        await _extractor(FailingLLM("")).extract(_conversation())