"""Pydantic schemas for documents, decoupled from the ORM models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    """A document as returned to API consumers (no raw content)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    mime_type: str
    source_type: str
    created_at: datetime
    updated_at: datetime
    chunk_count: int


class DocumentDetail(DocumentRead):
    """One document with its current content and file staleness.

    ``content`` is the vault file's text when the file exists on disk (the
    source of truth), else the content column; PDFs always show the extracted
    text from the database. ``stale`` is True when the file on disk is newer
    than both the recorded ``file_mtime`` and the row's ``updated_at``.
    """

    content: str
    file_path: str | None
    stale: bool


class DocumentCreate(BaseModel):
    """Payload for creating a document."""

    title: str
    content: str
    mime_type: str
    source_type: str = "text"


class DocumentAppendRequest(BaseModel):
    """Payload for appending text to a document's vault file."""

    text: str = Field(min_length=1)
    section: str | None = None


class DocumentList(BaseModel):
    """A page of documents."""

    model_config = ConfigDict(from_attributes=True)

    items: list[DocumentRead]
    total: int