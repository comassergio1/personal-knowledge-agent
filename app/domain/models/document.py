"""SQLAlchemy 2.0 mapped models for documents and their chunks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    """A user document (note, pasted text, file) with its chunks."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(64), default="text")
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # sha256 of the raw content: idempotent ingestion skips re-uploading
    # identical content within the same project (evals surfaced duplication
    # noise degrading retrieval recall).
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Vault-relative POSIX path of the source-of-truth markdown file (None
    # when the document was ingested without a file, e.g. pasted text).
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Modification time of the vault file at the last sync; a newer mtime on
    # disk marks the row stale (the file is the source of truth).
    file_mtime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )


class Chunk(Base):
    """An embeddable chunk of a document."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # `metadata` is reserved on declarative classes, so the attribute is
    # `metadata_` while the physical column stays `metadata`.
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")