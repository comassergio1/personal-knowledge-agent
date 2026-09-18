"""Unit tests for SyncService: new/updated/deleted + folder→project mapping."""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.services.sync_service import SyncSummary
from app.vector.collections import CONTENT_FIELD
from tests.unit.fakes import build_stack

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _bump_mtime(path: Path) -> None:
    """Force a strictly newer mtime than any prior write (same-second safe)."""
    now = time.time()
    os.utime(path, (now + 5.0, now + 5.0))


async def test_sync_ingests_new_file_and_creates_project(db_session, tmp_path) -> None:
    _, sync, store, vault, documents, projects = build_stack(db_session, tmp_path)
    vault.write_text("research/note.md", "Research content alpha.")

    summary = await sync.sync()

    assert summary == SyncSummary(created=1, updated=0, deleted=0)
    project = await projects.get_by_name("research")
    assert project is not None
    document = await documents.get_by_file_path("research/note.md")
    assert document is not None
    assert document.project_id == project.id
    assert document.content == "Research content alpha."
    assert store.upserted


async def test_sync_reattaches_existing_project_by_slug(db_session, tmp_path) -> None:
    _, sync, _, vault, documents, projects = build_stack(db_session, tmp_path)
    project = await projects.create(name="Research Notes")
    vault.write_text("research-notes/note.md", "Content.")

    summary = await sync.sync()

    assert summary.created == 1
    document = await documents.get_by_file_path("research-notes/note.md")
    assert document is not None
    assert document.project_id == project.id
    assert len(await projects.list()) == 1  # no duplicate project created


async def test_sync_root_and_inbox_files_use_default_project(
    db_session, tmp_path
) -> None:
    _, sync, _, vault, documents, projects = build_stack(db_session, tmp_path)
    vault.write_text("root-note.md", "Root content.")
    vault.write_text("inbox/boxed.md", "Inbox content.")

    summary = await sync.sync()

    assert summary.created == 2
    assert list(await projects.list()) == []
    root_doc = await documents.get_by_file_path("root-note.md")
    assert root_doc is not None and root_doc.project_id is None
    inbox_doc = await documents.get_by_file_path("inbox/boxed.md")
    assert inbox_doc is not None and inbox_doc.project_id is None


async def test_sync_ingests_new_pdf_from_disk(db_session, tmp_path) -> None:
    _, sync, _, _, documents, projects = build_stack(db_session, tmp_path)
    (tmp_path / "vault" / "papers").mkdir(parents=True)
    (tmp_path / "vault" / "papers" / "report.pdf").write_bytes(
        (FIXTURES / "sample.pdf").read_bytes()
    )

    summary = await sync.sync()

    assert summary.created == 1
    document = await documents.get_by_file_path("papers/report.pdf")
    assert document is not None
    assert document.mime_type == "application/pdf"
    assert document.content == "Hello PKA"
    project = await projects.get_by_name("papers")
    assert document.project_id == project.id


async def test_sync_updates_changed_file_via_resync(db_session, tmp_path) -> None:
    _, sync, store, vault, documents, _ = build_stack(db_session, tmp_path)
    vault.write_text("note.md", "Original content.")
    await sync.sync()
    assert store.upserted

    path = tmp_path / "vault" / "note.md"
    path.write_text("Edited content on disk.")
    _bump_mtime(path)

    summary = await sync.sync()

    assert summary == SyncSummary(created=0, updated=1, deleted=0)
    document = await documents.get_by_file_path("note.md")
    assert document is not None
    assert document.content == "Edited content on disk."
    assert any(
        "Edited content on disk." in point.payload[CONTENT_FIELD]
        for point in store.upserted
    )


async def test_sync_deletes_documents_for_removed_files(db_session, tmp_path) -> None:
    _, sync, store, vault, documents, _ = build_stack(db_session, tmp_path)
    vault.write_text("gone.md", "Will be removed.")
    await sync.sync()
    document = await documents.get_by_file_path("gone.md")
    assert document is not None and store.upserted

    (tmp_path / "vault" / "gone.md").unlink()
    summary = await sync.sync()

    assert summary == SyncSummary(created=0, updated=0, deleted=1)
    assert await documents.get(document.id) is None
    assert store.deleted == [document.id]
    assert store.upserted == []


async def test_sync_skips_unsupported_and_empty_files(db_session, tmp_path) -> None:
    _, sync, _, vault, documents, _ = build_stack(db_session, tmp_path)
    vault.write_text("image.png", "not text")
    vault.write_text("empty.md", "")

    summary = await sync.sync()

    assert summary.created == 0
    assert list(await documents.list()) == []


async def test_sync_is_idempotent(db_session, tmp_path) -> None:
    _, sync, _, vault, _, _ = build_stack(db_session, tmp_path)
    vault.write_text("note.md", "Stable content.")

    first = await sync.sync()
    second = await sync.sync()

    assert first == SyncSummary(created=1, updated=0, deleted=0)
    assert second == SyncSummary(created=0, updated=0, deleted=0)