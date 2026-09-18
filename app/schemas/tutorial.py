"""Pydantic schemas for the tutorial generation endpoint (spec §20)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TutorialRequest(BaseModel):
    """Payload for POST /api/v1/tutorials/generate."""

    objective: str = Field(min_length=1)
    project_id: str | None = None
    title: str | None = None


class TutorialSourceRead(BaseModel):
    """One source a generated tutorial was grounded in."""

    title: str
    score: float


class TutorialRead(BaseModel):
    """A generated tutorial: markdown content plus its grounding sources."""

    document_id: str | None
    title: str
    file_path: str | None
    content: str
    sources: list[TutorialSourceRead] = []
    warnings: list[str] | None = None