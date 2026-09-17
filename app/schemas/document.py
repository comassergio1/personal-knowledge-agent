"""Pydantic schemas for documents, decoupled from the ORM models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class DocumentCreate(BaseModel):
    """Payload for creating a document."""

    title: str
    content: str
    mime_type: str
    source_type: str = "text"


class DocumentList(BaseModel):
    """A page of documents."""

    model_config = ConfigDict(from_attributes=True)

    items: list[DocumentRead]
    total: int