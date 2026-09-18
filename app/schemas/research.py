"""Pydantic schemas for the research endpoint (spec §21)."""

from __future__ import annotations

from fastapi import Query
from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    """Payload for POST /api/v1/research/run."""

    question: str = Field(min_length=1)
    project_id: str | None = None
    title: str | None = None
    # Clamped to 1–15 sources; None falls back to ``Settings.research_max_sources``.
    max_sources: int | None = Query(None, ge=1, le=15)


class ResearchSourceRead(BaseModel):
    """One source a research report was grounded in."""

    title: str
    url: str
    domain: str
    snippet: str


class ResearchRead(BaseModel):
    """A completed research report: markdown plus its consulted sources."""

    document_id: str | None
    title: str
    file_path: str | None
    report: str
    sources: list[ResearchSourceRead] = []
    warnings: list[str] | None = None