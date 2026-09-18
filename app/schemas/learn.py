"""Pydantic schemas for the learning loop (Phase 7: learn/run, learn/reflect).

The learning loop reuses the existing retrieval, research, tutorial, and
memory services; these schemas only model the request/response contract for
the deferred routes (wiring lands in unit 5).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.tutorial import TutorialMode


class LearnRequest(BaseModel):
    """Payload for the deferred POST /api/v1/learn/run."""

    goal: str = Field(min_length=1)
    # Depth for the generated tutorial; defaults to the learning mode.
    mode: TutorialMode = "learn"
    project_id: str | None = None
    title: str | None = None
    # When the top retrieval score runs below ``research_threshold`` (or there
    # are no hits) the loop considers the knowledge insufficient and, unless
    # ``allow_research`` is False, runs the research agent to fill the gap.
    allow_research: bool = True
    research_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class LearnSourceRead(BaseModel):
    """One source a generated tutorial was grounded in."""

    title: str
    score: float


class TutorialRefRead(BaseModel):
    """The persisted tutorial: vault document ref plus its markdown content."""

    document_id: str | None
    file_path: str | None
    content: str
    sources: list[LearnSourceRead] = []


class ResearchRefRead(BaseModel):
    """The research report persisted during the loop, when one ran."""

    document_id: str | None
    file_path: str | None


class LearnResultRead(BaseModel):
    """Outcome of a learning-loop run."""

    goal: str
    mode: TutorialMode
    needs_research: bool
    research: ResearchRefRead | None = None
    tutorial: TutorialRefRead
    # Fixed hint telling the human how to turn the experience into memory.
    reflect_hint: str


class ReflectRequest(BaseModel):
    """Payload for the deferred POST /api/v1/learn/reflect."""

    goal: str = Field(min_length=1)
    what_i_learned: str = Field(min_length=1)
    project_id: str | None = None