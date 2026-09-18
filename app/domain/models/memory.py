"""SQLAlchemy 2.0 mapped model for memories (spec §12/§13).

A memory is a knowledge item extracted from a conversation. The lifecycle is
``candidate → (approved | rejected)``: candidates are written redacted by the
extractor, approval promotes them to the vectors + vault mirror (unit 2), and
rejection discards them from retrieval. The allowed type/status values are
plain module constants; validation happens at the schema layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base

MEMORY_TYPES = ("semantic", "episodic", "procedural", "preference")
MEMORY_STATUSES = ("candidate", "approved", "rejected")


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Memory(Base):
    """A knowledge item extracted from a conversation, redacted before storage."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    # ``memory_type`` is the python attribute; the physical column is ``type``
    # (``type`` is reserved on some tooling, so the attribute is not named
    # after the column).
    memory_type: Mapped[str] = mapped_column("type", String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<Memory id={self.id!r} type={self.memory_type!r} "
            f"status={self.status!r}>"
        )