"""Idempotent ingestion: identical content in the same project scope is a no-op.

Evals surfaced duplicated mikrotik documents (repeated smoke-upload runs)
degrading retrieval recall; this locks the dedupe behavior in.
"""

from __future__ import annotations

import pytest

from tests.unit.fakes import build_stack


@pytest.mark.asyncio
async def test_same_content_same_project_returns_existing_document(db_session, tmp_path) -> None:
    ingestion, _, _, _, documents, _ = build_stack(db_session, tmp_path)
    content = "# Repetido\n\nContenido identico para dedupe."
    first = await ingestion.ingest(
        title="dup", content=content, mime_type="text/markdown", source_type="file"
    )
    second = await ingestion.ingest(
        title="dup-2", content=content, mime_type="text/markdown", source_type="file"
    )
    assert second.id == first.id
    assert len(await documents.list()) == 1


@pytest.mark.asyncio
async def test_same_content_different_project_creates_separate_document(
    db_session, tmp_path
) -> None:
    ingestion, _, _, _, documents, projects = build_stack(db_session, tmp_path)
    p1 = await projects.create(name="Proyecto A")
    p2 = await projects.create(name="Proyecto B")
    content = "# Compartido\n\nMismo contenido, proyectos distintos."
    doc_a = await ingestion.ingest(
        title="a", content=content, mime_type="text/markdown", source_type="file",
        project_id=p1.id,
    )
    doc_b = await ingestion.ingest(
        title="b", content=content, mime_type="text/markdown", source_type="file",
        project_id=p2.id,
    )
    assert doc_a.id != doc_b.id
    assert len(await documents.list()) == 2


@pytest.mark.asyncio
async def test_different_content_always_ingests(db_session, tmp_path) -> None:
    ingestion, _, _, _, documents, _ = build_stack(db_session, tmp_path)
    await ingestion.ingest(
        title="one", content="Contenido uno.", mime_type="text/markdown", source_type="file"
    )
    await ingestion.ingest(
        title="two", content="Contenido dos.", mime_type="text/markdown", source_type="file"
    )
    assert len(await documents.list()) == 2