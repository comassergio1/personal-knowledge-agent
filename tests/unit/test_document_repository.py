"""Unit tests for DocumentRepository over in-memory SQLite."""

from __future__ import annotations

from sqlalchemy import func, select

from app.domain.models.document import Chunk
from app.repositories.document_repository import DocumentRepository


async def _create_doc(repo: DocumentRepository, title: str = "Note", n_chunks: int = 2):
    return await repo.create(
        title=title,
        content="body",
        mime_type="text/markdown",
        source_type="text",
        source_uri="obsidian://vault/note",
        project_id="proj-1",
        chunks=[
            Chunk(chunk_index=i, content=f"chunk {i}", metadata_={"i": i})
            for i in range(n_chunks)
        ],
    )


async def test_create_document_with_chunks(db_session) -> None:
    repo = DocumentRepository(db_session)
    doc = await _create_doc(repo)

    assert doc.id
    assert doc.created_at is not None
    assert doc.updated_at is not None
    assert doc.source_uri == "obsidian://vault/note"
    assert doc.project_id == "proj-1"
    assert doc.mime_type == "text/markdown"
    assert len(doc.chunks) == 2
    assert doc.chunks[0].chunk_index == 0
    assert doc.chunks[0].metadata_ == {"i": 0}


async def test_create_without_chunks(db_session) -> None:
    repo = DocumentRepository(db_session)
    doc = await repo.create(title="Empty", content="", mime_type="text/plain")

    assert doc.id
    assert len(doc.chunks) == 0
    assert doc.source_type == "text"  # model default


async def test_get_by_id(db_session) -> None:
    repo = DocumentRepository(db_session)
    doc = await _create_doc(repo, title="Retrievable")

    fetched = await repo.get(doc.id)
    assert fetched is not None
    assert fetched.title == "Retrievable"
    assert len(fetched.chunks) == 2

    assert await repo.get("missing-id") is None


async def test_list_returns_all_documents(db_session) -> None:
    repo = DocumentRepository(db_session)
    await _create_doc(repo, title="A")
    await _create_doc(repo, title="B")

    docs = await repo.list()

    assert {d.title for d in docs} == {"A", "B"}
    assert all(len(d.chunks) == 2 for d in docs)


async def test_list_filters_by_project(db_session) -> None:
    repo = DocumentRepository(db_session)
    await _create_doc(repo, title="In project")
    await repo.create(
        title="Other",
        content="body",
        mime_type="text/markdown",
        project_id="proj-2",
    )

    in_project = await repo.list(project_id="proj-1")
    other = await repo.list(project_id="proj-2")

    assert [d.title for d in in_project] == ["In project"]
    assert [d.title for d in other] == ["Other"]
    # An unknown project yields an empty list, never an error.
    assert await repo.list(project_id="missing") == []


async def test_delete_removes_document_and_its_chunks(db_session) -> None:
    repo = DocumentRepository(db_session)
    doc = await _create_doc(repo)

    deleted = await repo.delete(doc.id)
    assert deleted is True

    assert await repo.get(doc.id) is None
    remaining_chunks = await db_session.scalar(select(func.count()).select_from(Chunk))
    assert remaining_chunks == 0


async def test_delete_missing_document_returns_false(db_session) -> None:
    repo = DocumentRepository(db_session)
    assert await repo.delete("missing-id") is False