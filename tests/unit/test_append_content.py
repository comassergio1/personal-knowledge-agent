"""Unit tests for IngestionService.append_content (compose, write, re-index)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ingestion_service import IngestionService
from app.vector.collections import CONTENT_FIELD
from tests.unit.fakes import CapturingVectorStore, FakeEmbeddingProvider, build_stack

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


async def test_append_with_section_writes_composed_block(
    db_session, tmp_path
) -> None:
    ingestion, _, _, vault, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="Intro line.", source_type="file"
    )

    detail = await ingestion.append_content(
        document.id, text="Appended body.", section="Details"
    )

    assert detail is not None
    assert detail.content == "Intro line.\n## Details\n\nAppended body.\n"
    assert detail.stale is False
    assert detail.chunk_count == 1
    assert (
        vault.read_text(document.file_path) == "Intro line.\n## Details\n\nAppended body.\n"
    )


async def test_append_without_section_uses_blank_line_separator(
    db_session, tmp_path
) -> None:
    ingestion, _, _, vault, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="First line.", source_type="file"
    )

    detail = await ingestion.append_content(document.id, text="More text.")

    assert detail is not None
    assert detail.content == "First line.\n\nMore text.\n"
    assert vault.read_text(document.file_path) == "First line.\n\nMore text.\n"


async def test_append_reindexes_replacing_rows_and_vectors(
    db_session, tmp_path
) -> None:
    ingestion, _, store, _, documents, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="Old content.", source_type="file"
    )
    old_chunks = [chunk.id for chunk in (await documents.get(document.id)).chunks]
    store.upserted.clear()

    detail = await ingestion.append_content(
        document.id, text="New sentence.", section="Update"
    )

    assert store.deleted == [document.id]
    assert len(store.upserted) == 1
    assert "New sentence." in store.upserted[0].payload[CONTENT_FIELD]
    assert detail is not None
    assert detail.stale is False

    persisted = await documents.get(document.id)
    assert persisted is not None
    assert [chunk.id for chunk in persisted.chunks] != old_chunks
    assert "New sentence." in persisted.content


async def test_append_missing_document_returns_none(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)

    assert await ingestion.append_content("missing", text="more") is None


async def test_append_file_less_document_raises(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(title="Pasted", content="body", source_type="text")

    with pytest.raises(ValueError, match="text/markdown"):
        await ingestion.append_content(document.id, text="more")


async def test_append_pdf_document_raises(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest_pdf(
        title="Paper", pdf_bytes=(FIXTURES / "sample.pdf").read_bytes()
    )

    with pytest.raises(ValueError, match="text/markdown"):
        await ingestion.append_content(document.id, text="more")


async def test_append_missing_file_on_disk_raises(db_session, tmp_path) -> None:
    ingestion, _, _, vault, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="body", source_type="file"
    )
    vault.delete(document.file_path)

    with pytest.raises(ValueError, match="missing"):
        await ingestion.append_content(document.id, text="more")


async def test_append_without_vault_raises(db_session, tmp_path) -> None:
    ingestion, _, _, _, documents, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="body", source_type="file"
    )
    no_vault = IngestionService(
        documents,
        CapturingVectorStore(),  # type: ignore[arg-type]
        FakeEmbeddingProvider(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="VaultService"):
        await no_vault.append_content(document.id, text="more")