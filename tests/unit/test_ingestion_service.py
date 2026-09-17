"""Unit tests for IngestionService (fake providers/stores, in-memory DB, offline)."""

from __future__ import annotations

import pytest

from app.domain.models.document import Chunk
from app.providers.embeddings.base import EmbeddingProviderError
from app.repositories.document_repository import DocumentRepository
from app.services.ingestion_service import IngestionError, IngestionService
from app.vector.collections import (
    CHUNK_ID_FIELD,
    CHUNK_INDEX_FIELD,
    CONTENT_FIELD,
    DOCUMENT_ID_FIELD,
    METADATA_FIELD,
    PROJECT_ID_FIELD,
    TITLE_FIELD,
)
from app.vector.qdrant import VectorPoint


class FakeEmbeddingProvider:
    """Returns a fixed-size vector and records every embedded text."""

    EMBEDDING_SIZE = 4

    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return [0.1, 0.2, 0.3, 0.4]


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        raise EmbeddingProviderError("embedding server down")


class FakeVectorStore:
    """Disposable in-memory store capturing every upsert."""

    def __init__(self) -> None:
        self.upserted: list[VectorPoint] = []

    async def upsert_chunks(self, points: list[VectorPoint]) -> None:
        self.upserted.extend(points)


class FailingVectorStore(FakeVectorStore):
    async def upsert_chunks(self, points: list[VectorPoint]) -> None:
        raise RuntimeError("qdrant connection refused")


def _service(
    db_session, embedding=None, store=None
) -> tuple[IngestionService, FakeVectorStore, FakeEmbeddingProvider]:
    embedding = FakeEmbeddingProvider() if embedding is None else embedding
    store = FakeVectorStore() if store is None else store
    repo = DocumentRepository(db_session)
    return IngestionService(repo, store, embedding), store, embedding  # type: ignore[arg-type]


async def test_ingest_chunks_persists_and_upserts(db_session) -> None:
    service, store, embedding = _service(db_session)

    document = await service.ingest(
        title="Note",
        content="First paragraph.\n\nSecond paragraph.\n\nThird paragraph.",
        chunk_size=20,
        chunk_overlap=0,
    )

    persisted = await DocumentRepository(db_session).get(document.id)
    assert persisted is not None
    assert persisted.title == "Note"
    assert [c.chunk_index for c in persisted.chunks] == [0, 1, 2]
    assert [c.content for c in persisted.chunks] == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
    ]
    # embedding_id is filled from the vector point id after embedding.
    assert all(c.embedding_id == c.id for c in persisted.chunks)

    assert embedding.embedded == ["First paragraph.", "Second paragraph.", "Third paragraph."]
    assert len(store.upserted) == 3
    point = store.upserted[0]
    assert point.id == persisted.chunks[0].id
    assert point.vector == [0.1, 0.2, 0.3, 0.4]
    assert point.payload[DOCUMENT_ID_FIELD] == document.id
    assert point.payload[CHUNK_ID_FIELD] == point.id
    assert point.payload[CHUNK_INDEX_FIELD] == 0
    assert point.payload[TITLE_FIELD] == "Note"
    assert point.payload[CONTENT_FIELD] == "First paragraph."
    assert point.payload[METADATA_FIELD][CHUNK_INDEX_FIELD] == 0


async def test_ingest_persists_document_metadata(db_session) -> None:
    service, _, _ = _service(db_session)

    document = await service.ingest(
        title="File note",
        content="Hello, world.",
        mime_type="text/plain",
        source_type="file",
        source_uri="file:///tmp/note.txt",
        project_id="proj-9",
    )

    assert document.mime_type == "text/plain"
    assert document.source_type == "file"
    assert document.source_uri == "file:///tmp/note.txt"
    assert document.project_id == "proj-9"


async def test_ingest_mirrors_project_id_in_vector_payload(db_session) -> None:
    service, store, _ = _service(db_session)

    await service.ingest(
        title="Note", content="Project-scoped content.", project_id="proj-42"
    )

    point = store.upserted[0]
    assert point.payload[PROJECT_ID_FIELD] == "proj-42"
    assert point.payload[METADATA_FIELD][PROJECT_ID_FIELD] == "proj-42"


async def test_ingest_payload_project_id_is_none_without_project(db_session) -> None:
    service, store, _ = _service(db_session)

    await service.ingest(title="Note", content="Ungrouped content.")

    point = store.upserted[0]
    assert point.payload[PROJECT_ID_FIELD] is None
    assert point.payload[METADATA_FIELD][PROJECT_ID_FIELD] is None


async def test_ingest_defaults_chunking_from_settings(db_session) -> None:
    service, _, _ = _service(db_session)

    document = await service.ingest(title="Short", content="Short note.")
    # Settings.chunk_size=1000: a short document stays a single chunk.
    assert len(document.chunks) == 1
    assert isinstance(document.chunks[0], Chunk)


async def test_ingest_forwards_explicit_chunk_parameters(db_session) -> None:
    service, store, _ = _service(db_session)

    document = await service.ingest(
        title="Explicit",
        content="Segment one.\n\nSegment two.\n\nSegment three.",
        chunk_size=16,
        chunk_overlap=3,
    )

    assert len(document.chunks) == 3
    # The second chunk is prefixed with the previous chunk's 3-character tail.
    assert document.chunks[1].content.startswith(document.chunks[0].content[-3:])
    assert len(store.upserted) == 3


async def test_ingest_wraps_embedding_errors(db_session) -> None:
    service, _, _ = _service(db_session, embedding=FailingEmbeddingProvider())

    with pytest.raises(IngestionError, match="embed"):
        await service.ingest(title="Broken", content="Some content here.")


async def test_ingest_wraps_vector_store_errors(db_session) -> None:
    service, _, _ = _service(db_session, store=FailingVectorStore())

    with pytest.raises(IngestionError, match="upsert"):
        await service.ingest(title="Broken", content="Some content here.")


async def test_ingest_rejects_empty_content(db_session) -> None:
    service, _, _ = _service(db_session)

    with pytest.raises(ValueError, match="empty"):
        await service.ingest(title="Empty", content="   \n")