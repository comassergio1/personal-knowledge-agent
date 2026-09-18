"""Unit tests for MemoryService (fake store/extractor, tmp vault, offline)."""

from __future__ import annotations

import pytest

from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import ConversationTurn
from app.services.memory_extractor import MemoryExtractionError
from app.services.memory_service import (
    MemoryNotFoundError,
    MemoryService,
    MemoryStateError,
)
from app.services.vault_service import VaultService
from app.vector.collections import MEMORY_ID_FIELD, MEMORY_TYPE_FIELD
from app.vector.qdrant import SearchHit, VectorPoint


class FakeEmbeddings:
    """Records every embedded text and returns a fixed vector."""

    EMBEDDING_SIZE = 4

    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return [0.1, 0.2, 0.3, 0.4]


class FakeStore:
    """In-memory memory store: captures upserts/deletes, serves canned hits."""

    def __init__(self) -> None:
        self.upserted: list[VectorPoint] = []
        self.deleted: list[tuple[str, str]] = []
        self.hits: list[SearchHit] = []
        self.last_top_k: int | None = None

    async def upsert_chunks(self, points: list[VectorPoint]) -> None:
        self.upserted.extend(points)

    async def delete_by_field(self, field: str, value: str) -> None:
        self.deleted.append((field, value))

    async def search(
        self, embedding: list[float], *, top_k: int = 5, **kwargs
    ) -> list[SearchHit]:
        self.last_top_k = top_k
        return self.hits[:top_k]


class FakeExtractor:
    """Returns canned candidate dicts and records the conversation received."""

    def __init__(self, candidates: list[dict] | None = None) -> None:
        self.candidates = (
            candidates
            if candidates is not None
            else [
                {
                    "type": "semantic",
                    "content": "Prefers concise answers",
                    "confidence": 0.9,
                    "source": "conversation",
                }
            ]
        )
        self.conversations: list = []

    async def extract(self, conversation) -> list[dict]:
        self.conversations.append(conversation)
        return self.candidates


def _service(
    db_session, tmp_path, *, extractor=None
) -> tuple[MemoryService, MemoryRepository, FakeStore, FakeEmbeddings, VaultService]:
    repo = MemoryRepository(db_session)
    store = FakeStore()
    embeddings = FakeEmbeddings()
    vault = VaultService(tmp_path / "vault")
    service = MemoryService(
        repo, store, embeddings, vault=vault, extractor=extractor  # type: ignore[arg-type]
    )
    return service, repo, store, embeddings, vault


def _conversation() -> list[ConversationTurn]:
    return [ConversationTurn(role="user", content="hi")]


async def test_extract_persists_redacted_candidates(db_session, tmp_path) -> None:
    extractor = FakeExtractor(
        [
            {"type": "semantic", "content": "user password=hunter2 stored", "confidence": 0.9},
            {"type": "preference", "content": "Prefers tea", "confidence": 0.4},
        ]
    )
    service, repo, store, embeddings, _ = _service(db_session, tmp_path, extractor=extractor)
    conversation = _conversation()

    rows = await service.extract(conversation)

    assert len(rows) == 2
    assert all(row.status == "candidate" for row in rows)
    assert "[REDACTED]" in rows[0].content
    assert "hunter2" not in rows[0].content
    assert rows[0].confidence == 0.9
    assert rows[1].content == "Prefers tea"
    assert extractor.conversations == [conversation]
    # extraction persists only; no embedding or vector work happens yet
    assert store.upserted == []
    assert embeddings.embedded == []
    assert len(await repo.list()) == 2


async def test_extract_without_extractor_raises(db_session, tmp_path) -> None:
    service, _, _, _, _ = _service(db_session, tmp_path)

    with pytest.raises(MemoryExtractionError):
        await service.extract(_conversation())


async def test_approve_upserts_vector_and_writes_mirror(db_session, tmp_path) -> None:
    service, _, store, embeddings, vault = _service(
        db_session, tmp_path, extractor=FakeExtractor()
    )
    memory = (await service.extract(_conversation()))[0]

    approved = await service.approve(memory.id)

    assert approved.status == "approved"
    assert len(store.upserted) == 1
    point = store.upserted[0]
    assert point.id == memory.id
    assert point.vector == [0.1, 0.2, 0.3, 0.4]
    assert point.payload[MEMORY_ID_FIELD] == memory.id
    assert point.payload[MEMORY_TYPE_FIELD] == "semantic"
    assert point.payload["content"] == "Prefers concise answers"
    assert point.payload["status"] == "approved"
    assert embeddings.embedded == ["Prefers concise answers"]

    files = vault.scan()
    assert len(files) == 1
    text = vault.read_text(files[0].abs_path)
    assert "type: semantic" in text
    assert "status: approved" in text
    assert "confidence: 0.9" in text
    assert "source: conversation" in text
    assert "Prefers concise answers" in text


async def test_approve_missing_and_non_candidate_raise(db_session, tmp_path) -> None:
    service, _, _, _, _ = _service(db_session, tmp_path, extractor=FakeExtractor())
    memory = (await service.extract(_conversation()))[0]

    assert (await service.approve(memory.id)).status == "approved"

    with pytest.raises(MemoryStateError):
        await service.approve(memory.id)
    with pytest.raises(MemoryNotFoundError):
        await service.approve("no-such-id")


async def test_approve_without_vault_skips_mirror(db_session, tmp_path) -> None:
    repo = MemoryRepository(db_session)
    store = FakeStore()
    service = MemoryService(
        repo, store, FakeEmbeddings(), vault=None, extractor=FakeExtractor()  # type: ignore[arg-type]
    )
    memory = (await service.extract(_conversation()))[0]

    approved = await service.approve(memory.id)

    assert approved.status == "approved"
    assert len(store.upserted) == 1
    assert store.upserted[0].payload["status"] == "approved"


async def test_reject_removes_vector_and_mirror(db_session, tmp_path) -> None:
    service, repo, store, _, vault = _service(db_session, tmp_path, extractor=FakeExtractor())
    memory = (await service.extract(_conversation()))[0]
    await service.approve(memory.id)
    assert len(vault.scan()) == 1

    rejected = await service.reject(memory.id)

    assert rejected.status == "rejected"
    assert (MEMORY_ID_FIELD, memory.id) in store.deleted
    assert vault.scan() == []
    fetched = await repo.get(memory.id)
    assert fetched is not None
    assert fetched.status == "rejected"


async def test_reject_of_candidate_does_not_raise(db_session, tmp_path) -> None:
    service, _, store, _, vault = _service(db_session, tmp_path, extractor=FakeExtractor())
    memory = (await service.extract(_conversation()))[0]

    rejected = await service.reject(memory.id)

    assert rejected.status == "rejected"
    assert (MEMORY_ID_FIELD, memory.id) in store.deleted
    assert vault.scan() == []


async def test_delete_removes_row_vector_and_mirror(db_session, tmp_path) -> None:
    service, repo, store, _, vault = _service(db_session, tmp_path, extractor=FakeExtractor())
    memory = (await service.extract(_conversation()))[0]
    await service.approve(memory.id)
    assert len(vault.scan()) == 1

    assert await service.delete(memory.id) is True

    assert await repo.get(memory.id) is None
    assert (MEMORY_ID_FIELD, memory.id) in store.deleted
    assert vault.scan() == []
    assert await service.delete("no-such-id") is False


async def test_search_approved_maps_hits_to_contents(db_session, tmp_path) -> None:
    service, _, store, embeddings, _ = _service(db_session, tmp_path)
    store.hits = [
        SearchHit(
            chunk_id="mem-1", document_id="", title="",
            content="Prefers concise answers", score=0.9, metadata={},
        ),
        SearchHit(
            chunk_id="mem-2", document_id="", title="",
            content="Likes tea", score=0.7, metadata={},
        ),
    ]

    results = await service.search_approved("what does the user prefer?", top_k=3)

    assert results == ["Prefers concise answers", "Likes tea"]
    assert store.last_top_k == 3
    assert embeddings.embedded == ["what does the user prefer?"]