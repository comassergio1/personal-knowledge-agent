"""Unit tests for file-first ingestion, PDFs, detail/stale, and resync."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.services.ingestion_service import INBOX, ResyncError, as_naive_utc
from app.vector.collections import CONTENT_FIELD, FILE_PATH_FIELD, METADATA_FIELD
from tests.unit.fakes import build_stack

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _bump_mtime(path: Path) -> None:
    """Force a strictly newer mtime than any prior write (same-second safe)."""
    now = time.time()
    os.utime(path, (now + 5.0, now + 5.0))


def _blank_pdf() -> bytes:
    """A valid PDF with a blank page (extracts to no text)."""
    from io import BytesIO

    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    return buffer.getvalue()


# -- file-first markdown/txt ingestion -------------------------------------


async def test_ingest_writes_markdown_into_vault_before_persisting(
    db_session, tmp_path
) -> None:
    ingestion, _, _, vault, documents, _ = build_stack(db_session, tmp_path)

    document = await ingestion.ingest(
        title="First note", content="# First note\n\nBody.", source_type="file"
    )

    path = tmp_path / "vault" / INBOX / "first-note.md"
    assert document.file_path == f"{INBOX}/first-note.md"
    assert document.file_mtime is not None
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# First note\n\nBody."
    assert as_naive_utc(document.file_mtime) == as_naive_utc(
        vault.mtime(document.file_path)
    )

    persisted = await documents.get(document.id)
    assert persisted is not None
    assert persisted.content == "# First note\n\nBody."
    assert persisted.file_path == f"{INBOX}/first-note.md"


async def test_ingest_uses_project_name_for_folder(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, projects = build_stack(db_session, tmp_path)
    project = await projects.create(name="Deep Dive Notes")

    document = await ingestion.ingest(
        title="Note", content="body", source_type="file", project_id=project.id
    )

    assert document.file_path == "deep-dive-notes/note.md"
    assert (tmp_path / "vault" / "deep-dive-notes" / "note.md").exists()
    assert document.project_id == project.id


async def test_ingest_unknown_project_falls_back_to_inbox(
    db_session, tmp_path
) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)

    document = await ingestion.ingest(
        title="Note", content="body", source_type="file", project_id="missing"
    )

    assert document.file_path == f"{INBOX}/note.md"


async def test_ingest_without_file_source_writes_no_vault_file(
    db_session, tmp_path
) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)

    document = await ingestion.ingest(title="Pasted", content="body", source_type="text")

    assert document.file_path is None
    assert document.file_mtime is None
    assert not (tmp_path / "vault").exists()


# -- PDF ingestion ------------------------------------------------------------


async def test_ingest_pdf_copies_file_and_extracts_text(db_session, tmp_path) -> None:
    ingestion, _, _, vault, _, _ = build_stack(db_session, tmp_path)
    pdf_bytes = (FIXTURES / "sample.pdf").read_bytes()

    document = await ingestion.ingest_pdf(title="Hello Paper", pdf_bytes=pdf_bytes)

    assert document.mime_type == "application/pdf"
    assert document.content == "Hello PKA"
    assert document.file_path == f"{INBOX}/hello-paper.pdf"
    assert vault.read_bytes(document.file_path) == pdf_bytes


def test_pdf_fixture_extracts_hello_pka() -> None:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO((FIXTURES / "sample.pdf").read_bytes()))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Hello PKA" in text


async def test_ingest_pdf_mirrors_file_path_in_vector_payload(
    db_session, tmp_path
) -> None:
    ingestion, _, store, _, _, _ = build_stack(db_session, tmp_path)

    document = await ingestion.ingest_pdf(
        title="Note", pdf_bytes=(FIXTURES / "sample.pdf").read_bytes()
    )

    point = store.upserted[0]
    assert point.payload[FILE_PATH_FIELD] == document.file_path
    assert point.payload[METADATA_FIELD][FILE_PATH_FIELD] == document.file_path
    assert "Hello PKA" in point.payload[CONTENT_FIELD]


async def test_ingest_pdf_empty_extraction_warns_and_still_ingests(
    db_session, tmp_path, caplog
) -> None:
    ingestion, _, store, _, _, _ = build_stack(db_session, tmp_path)

    with caplog.at_level(logging.WARNING, logger="ingestion_service"):
        document = await ingestion.ingest_pdf(title="Blank", pdf_bytes=_blank_pdf())

    assert document.content == ""
    assert document.file_path == f"{INBOX}/blank.pdf"
    assert store.upserted == []  # no text -> no chunks, no vectors
    assert any("no text" in record.message for record in caplog.records)


# -- detail / stale -----------------------------------------------------------


async def test_detail_fresh_document_is_not_stale(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="Fresh content.", source_type="file"
    )

    detail = await ingestion.detail(document.id)

    assert detail is not None
    assert detail.stale is False
    assert detail.content == "Fresh content."
    assert detail.file_path == f"{INBOX}/note.md"
    assert detail.chunk_count == 1


async def test_detail_edited_file_is_stale_with_new_content(
    db_session, tmp_path
) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="Old content.", source_type="file"
    )
    path = tmp_path / "vault" / document.file_path
    path.write_text("Edited content on disk.")
    _bump_mtime(path)

    detail = await ingestion.detail(document.id)

    assert detail.stale is True
    assert detail.content == "Edited content on disk."


async def test_detail_pdf_returns_extracted_text(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest_pdf(
        title="Paper", pdf_bytes=(FIXTURES / "sample.pdf").read_bytes()
    )

    detail = await ingestion.detail(document.id)

    assert detail.content == "Hello PKA"
    assert detail.stale is False


async def test_detail_missing_document_returns_none(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    assert await ingestion.detail("missing") is None


# -- resync --------------------------------------------------------------------


async def test_resync_reembeds_edited_file_and_clears_stale(
    db_session, tmp_path
) -> None:
    ingestion, _, store, vault, documents, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="Old content.", source_type="file"
    )
    path = tmp_path / "vault" / document.file_path
    path.write_text("New content on disk.")
    _bump_mtime(path)
    assert (await ingestion.detail(document.id)).stale is True

    detail = await ingestion.resync(document.id)

    assert detail is not None
    assert detail.content == "New content on disk."
    assert detail.stale is False
    assert store.deleted == [document.id]
    assert len(store.upserted) == 1
    assert "New content on disk." in store.upserted[0].payload[CONTENT_FIELD]

    persisted = await documents.get(document.id)
    assert persisted is not None
    assert as_naive_utc(persisted.file_mtime) == as_naive_utc(
        vault.mtime(persisted.file_path)
    )


async def test_resync_pdf_re_extracts_from_disk(db_session, tmp_path) -> None:
    ingestion, _, store, _, _, _ = build_stack(db_session, tmp_path)
    pdf_bytes = (FIXTURES / "sample.pdf").read_bytes()
    document = await ingestion.ingest_pdf(title="Paper", pdf_bytes=pdf_bytes)
    path = tmp_path / "vault" / document.file_path
    path.write_bytes(pdf_bytes)
    _bump_mtime(path)

    detail = await ingestion.resync(document.id)

    assert detail is not None
    assert detail.content == "Hello PKA"
    assert detail.stale is False
    assert store.deleted == [document.id]


async def test_resync_missing_document_returns_none(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    assert await ingestion.resync("missing") is None


async def test_resync_without_vault_file_raises(db_session, tmp_path) -> None:
    ingestion, _, _, _, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(title="Pasted", content="body", source_type="text")

    with pytest.raises(ResyncError, match="no vault file"):
        await ingestion.resync(document.id)


async def test_resync_missing_file_on_disk_raises(db_session, tmp_path) -> None:
    ingestion, _, _, vault, _, _ = build_stack(db_session, tmp_path)
    document = await ingestion.ingest(
        title="Note", content="body", source_type="file"
    )
    vault.delete(document.file_path)

    with pytest.raises(ResyncError, match="missing"):
        await ingestion.resync(document.id)