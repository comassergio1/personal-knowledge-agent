"""SQLAlchemy 2.0 mapped models for conversational research sessions.

A research session is the server-side home of the console's "Explorar" tab:
a title plus an ordered thread of turns. Turns carry the speaker (``role``),
the message body (``content``) and how the assistant answered (``kind``):
``answer`` for vault-grounded chat replies, ``research`` when the turn ran
the §21 web-research flow. Research turns optionally reference the persisted
report document (``research_document_id``) and record the consulted sources
as JSON.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base

TURN_ROLES = ("user", "assistant")
TURN_KINDS = ("answer", "research")


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ResearchSession(Base):
    """A conversational research thread persisted server-side."""

    __tablename__ = "research_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<ResearchSession id={self.id!r} title={self.title!r}>"


class ResearchTurn(Base):
    """One message in a research session thread.

    ``kind`` describes how the assistant answered the turn: ``answer`` (a
    vault-grounded chat reply, or any user message) or ``research`` (the §21
    web-research flow ran; ``research_document_id`` points at the persisted
    report and ``sources`` holds the consulted sources as JSON).
    """

    __tablename__ = "research_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(8))
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), default="answer")
    # References the document the report was ingested into, when the turn ran
    # web research. Deliberately a plain column (no FK): deleting a report's
    # document must never block or cascade into a session's history.
    research_document_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<ResearchTurn id={self.id!r} role={self.role!r} "
            f"kind={self.kind!r}>"
        )