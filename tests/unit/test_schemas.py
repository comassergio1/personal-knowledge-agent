"""Unit tests for the decoupled document Pydantic schemas."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.document import DocumentCreate, DocumentList, DocumentRead

_TS = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)


def _read(**overrides: object) -> DocumentRead:
    values: dict[str, object] = {
        "id": "doc-1",
        "title": "Note",
        "mime_type": "text/markdown",
        "source_type": "text",
        "created_at": _TS,
        "updated_at": _TS,
        "chunk_count": 3,
    }
    values.update(overrides)
    return DocumentRead(**values)  # type: ignore[arg-type]


def test_document_read_validates_fields() -> None:
    doc = _read()
    assert doc.id == "doc-1"
    assert doc.chunk_count == 3
    assert doc.created_at == _TS


def test_document_read_rejects_wrong_id_type() -> None:
    with pytest.raises(ValidationError):
        _read(id=123)  # type: ignore[call-arg]


def test_document_read_rejects_bad_chunk_count() -> None:
    with pytest.raises(ValidationError):
        _read(chunk_count="three")


def test_document_create_applies_source_type_default() -> None:
    doc = DocumentCreate(title="T", content="C", mime_type="text/plain")
    assert doc.source_type == "text"
    assert doc.content == "C"


def test_document_create_requires_title() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(content="C", mime_type="text/plain")


def test_document_create_requires_content() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(title="T", mime_type="text/plain")


def test_document_create_requires_mime_type() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(title="T", content="C")


def test_document_list_roundtrips_items_and_total() -> None:
    listing = DocumentList(items=[_read()], total=1)
    assert listing.total == 1
    assert listing.items[0].title == "Note"