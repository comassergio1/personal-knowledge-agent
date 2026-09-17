"""SQLAlchemy 2.0 mapped model for knowledge projects (spec §17).

A project groups documents under one vault subfolder; documents already
carry ``project_id``, so projects need no relationship to keep the model
minimal. Deleting a project removes its documents (rows, vector points, and
vault files) — destructive by design, driven by the API route, not by a
database cascade.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    """A named knowledge project with an optional description."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )