"""Pydantic schemas for research sessions (the "Explorar" console tab).

Turns carry ``sources`` as raw JSON because the shape depends on the turn
kind: vault-grounded answers store chat-style source refs (``document_id``,
``title``, ``chunk_index``, ``score``, ``excerpt``) while research turns
store consulted web sources (``title``, ``url``, ``domain``). The console
renders both generically.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tutorial import TutorialMode


class ResearchSessionCreate(BaseModel):
    """Payload for POST /api/v1/research/sessions."""

    # Optional; a missing or empty title gets the Spanish default.
    title: str | None = Field(default=None, max_length=512)


class ResearchTurnRead(BaseModel):
    """One turn of a research session thread."""

    id: str
    session_id: str
    role: str
    content: str
    # ``answer`` (grounded chat / plain message) or ``research`` (web flow).
    kind: str
    research_document_id: str | None
    sources: list[dict] | None = None
    created_at: datetime


class ResearchSessionRead(BaseModel):
    """A session as listed/created: metadata plus its turn count."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0


class ResearchSessionList(BaseModel):
    """A page of research sessions."""

    items: list[ResearchSessionRead]
    total: int


class ResearchSessionDetail(ResearchSessionRead):
    """A session with its full thread."""

    turns: list[ResearchTurnRead] = []


class ResearchTurnRequest(BaseModel):
    """Payload for POST /api/v1/research/sessions/{id}/turn."""

    message: str = Field(min_length=1)


class ResearchTutorialRequest(BaseModel):
    """Payload for POST /api/v1/research/sessions/{id}/tutorial."""

    # Single source of truth for the supported tutorial depths (Phase 7).
    mode: TutorialMode = "do"