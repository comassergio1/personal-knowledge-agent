"""Pydantic schemas for the tutorial generation endpoint (spec §20)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Single source of truth for the supported tutorial depths (Phase 7).
TutorialMode = Literal["do", "learn", "deep_learn"]


class TutorialRequest(BaseModel):
    """Payload for POST /api/v1/tutorials/generate."""

    objective: str = Field(min_length=1)
    # ``do`` keeps the legacy concrete-steps tutorial; ``learn`` and
    # ``deep_learn`` grow the structure (Phase 7, spec change §1).
    mode: TutorialMode = "do"
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
    # Echoes the requested depth; defaults to ``do`` so the pre-Phase-7 route
    # (which does not send the field yet; wiring lands in unit 5) stays valid.
    mode: TutorialMode = "do"