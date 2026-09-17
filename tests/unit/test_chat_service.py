"""Unit tests for ChatService (fake LLM/retrieval, caplog observability, no network)."""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.core.config import Settings
from app.domain.models.usage import LLMUsage
from app.providers.llm.base import LLMResult
from app.repositories.usage_repository import UsageRepository
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

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        self.messages = list(messages)
        self.requested_model = model
        return LLMResult(
            content="A grounded answer.",
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-llm",
            model="test-model",
        )


class MeteredFakeLLM:
    """Fake LLM reporting real token counts and a paid provider name."""

    name = "metered-fake"

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        return LLMResult(
            content="A metered answer.",
            prompt_tokens=100,
            completion_tokens=50,
            provider="payperq",
            model="test-model",
        )


class FakeRetrieval:
    """Returns pre-built hits and records the retrieval arguments."""

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits = hits if hits is not None else []
        self.calls: list[dict] = []

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_id: str | None = None,
        project_id: str | None = None,
    ) -> list[SearchHit]:
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "document_id": document_id,
                "project_id": project_id,
            }
        )
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

    assert retrieval.calls == [
        {"query": "what is the answer?", "top_k": 2, "document_id": None, "project_id": None}
    ]
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

    assert retrieval.calls == [
        {
            "query": "anything at all?",
            "top_k": 5,
            "document_id": "doc-x",
            "project_id": None,
        }
    ]
    assert llm.messages is not None
    assert len(llm.messages) == 2
    system, user = llm.messages
    assert system.content == _SYSTEM_PROMPT
    assert "KNOWLEDGE" not in user.content
    assert "USER REQUEST\nanything at all?" in user.content
    assert result.answer == "A grounded answer."
    assert result.sources == []


async def test_chat_passes_project_id_to_retrieval() -> None:
    service, _, retrieval = _service(hits=[])

    await service.chat("only my project", project_id="proj-7")

    assert retrieval.calls == [
        {
            "query": "only my project",
            "top_k": 5,
            "document_id": None,
            "project_id": "proj-7",
        }
    ]


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


async def test_chat_log_extras_include_tokens_and_cost(caplog) -> None:
    caplog.set_level(logging.INFO, logger="chat_service")
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    service = ChatService(MeteredFakeLLM(), FakeRetrieval([]), settings)  # type: ignore[arg-type]

    await service.chat("hello")

    records = [r for r in caplog.records if r.name == "chat_service"]
    assert len(records) == 1
    record = records[0]
    assert record.input_tokens == 100
    assert record.output_tokens == 50
    assert record.estimated_cost_usd == 0.0  # default rates are zero


async def test_chat_records_usage_row_when_repository_provided(db_session) -> None:
    settings = Settings(  # type: ignore[arg-type]
        _env_file=None,
        llm_model="test-model",
        payperq_usd_per_1k_in=10.0,
        payperq_usd_per_1k_out=20.0,
    )
    usage_repository = UsageRepository(db_session)
    service = ChatService(
        MeteredFakeLLM(), FakeRetrieval([]), settings, usage_repository  # type: ignore[arg-type]
    )

    await service.chat("hello")

    rows = await usage_repository.list_recent()
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, LLMUsage)
    assert len(row.request_id) == 32
    assert row.provider == "payperq"
    assert row.model == "test-model"
    assert row.prompt_tokens == 100
    assert row.completion_tokens == 50
    assert row.estimated_cost_usd == 2.0  # 100/1k*10 + 50/1k*20
    assert row.latency_ms >= 0


async def test_chat_records_no_usage_row_without_repository(db_session) -> None:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    service = ChatService(MeteredFakeLLM(), FakeRetrieval([]), settings)  # type: ignore[arg-type]

    await service.chat("hello")

    remaining = await db_session.scalar(select(func.count()).select_from(LLMUsage))
    assert remaining == 0