"""Unit tests for ChatService (fake LLM/retrieval, caplog observability, no network)."""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.schemas.chat import ChatResult, SourceRef
from app.services.chat_service import _SYSTEM_PROMPT, ChatService
from app.vector.collections import CHUNK_INDEX_FIELD
from app.vector.qdrant import SearchHit


class FakeLLM:
    """Records the messages passed to ``generate`` and returns a canned answer."""

    name = "fake-llm"

    def __init__(self) -> None:
        self.messages: list | None = None
        self.requested_model: str | None = "sentinel"

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> str:
        self.messages = list(messages)
        self.requested_model = model
        return "A grounded answer."


class FakeRetrieval:
    """Returns pre-built hits and records the retrieval arguments."""

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits = hits if hits is not None else []
        self.calls: list[dict] = []

    async def retrieve(
        self, query: str, *, top_k: int = 5, document_id: str | None = None
    ) -> list[SearchHit]:
        self.calls.append({"query": query, "top_k": top_k, "document_id": document_id})
        return self.hits


def _hit(chunk_id: str, document_id: str, title: str, content: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=document_id,
        title=title,
        content=content,
        score=score,
        metadata={CHUNK_INDEX_FIELD: int(chunk_id.removeprefix("chunk-"))},
    )


def _service(
    hits: list[SearchHit] | None = None,
) -> tuple[ChatService, FakeLLM, FakeRetrieval]:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    llm = FakeLLM()
    retrieval = FakeRetrieval(hits)
    return ChatService(llm, retrieval, settings), llm, retrieval  # type: ignore[arg-type]


async def test_chat_builds_grounded_prompt_and_returns_answer_with_sources() -> None:
    long_content = "beta " * 70  # 350 chars, forces excerpt truncation
    hits = [
        _hit("chunk-0", "doc-a", "Note A", "alpha content", 0.91),
        _hit("chunk-3", "doc-b", "Note B", long_content, 0.77),
    ]
    service, llm, retrieval = _service(hits)

    result: ChatResult = await service.chat("what is the answer?", top_k=2)

    assert retrieval.calls == [{"query": "what is the answer?", "top_k": 2, "document_id": None}]
    assert llm.requested_model is None
    assert llm.messages is not None
    assert len(llm.messages) == 2
    system, user = llm.messages
    assert system.role == "system"
    assert system.content == _SYSTEM_PROMPT
    assert user.role == "user"
    assert "KNOWLEDGE" in user.content
    assert "[1] (Note A) alpha content" in user.content
    assert "[2] (Note B) " in user.content and "beta beta" in user.content
    assert "USER REQUEST\nwhat is the answer?" in user.content

    assert result.answer == "A grounded answer."
    assert result.sources == [
        SourceRef(
            document_id="doc-a", title="Note A", chunk_index=0, score=0.91, excerpt="alpha content"
        ),
        SourceRef(
            document_id="doc-b",
            title="Note B",
            chunk_index=3,
            score=0.77,
            excerpt=long_content[:200],
        ),
    ]


async def test_chat_without_hits_omits_knowledge_and_returns_empty_sources() -> None:
    service, llm, retrieval = _service(hits=[])

    result: ChatResult = await service.chat(
        "anything at all?", top_k=5, document_id="doc-x"
    )

    assert retrieval.calls == [{"query": "anything at all?", "top_k": 5, "document_id": "doc-x"}]
    assert llm.messages is not None
    assert len(llm.messages) == 2
    system, user = llm.messages
    assert system.content == _SYSTEM_PROMPT
    assert "KNOWLEDGE" not in user.content
    assert "USER REQUEST\nanything at all?" in user.content
    assert result.answer == "A grounded answer."
    assert result.sources == []


async def test_chat_emits_structured_observability_log_line(caplog) -> None:
    caplog.set_level(logging.INFO, logger="chat_service")
    hits = [_hit("chunk-0", "doc-a", "Note A", "alpha content", 0.91)]
    service, _, _ = _service(hits)

    await service.chat("hello")

    records = [r for r in caplog.records if r.name == "chat_service"]
    assert len(records) == 1
    record = records[0]
    assert len(record.request_id) == 32
    int(record.request_id, 16)  # a valid uuid4 hex
    assert record.provider == "fake-llm"
    assert record.model == "test-model"
    assert record.retrieved_chunks == 1
    assert isinstance(record.latency_ms, int) and record.latency_ms >= 0
    assert record.answer_length == len("A grounded answer.")