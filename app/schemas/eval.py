"""Pydantic schemas for knowledge evaluations (spec §31/§32).

Request/response contracts for running evaluation datasets and reading run
history, decoupled from the ORM models. Thresholds are request-scoped
overrides; without them the judge's defaults (groundedness >= 0.7,
correctness >= 0.5) apply.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EvalThresholds(BaseModel):
    """Per-request verdict thresholds (used when provided)."""

    groundedness: float = Field(default=0.7, ge=0.0, le=1.0)
    correctness: float = Field(default=0.5, ge=0.0, le=1.0)


class EvalCaseInput(BaseModel):
    """One case of an evaluation dataset (question + expected facts)."""

    name: str | None = None
    question: str = Field(min_length=1)
    expected_facts: list[str] = Field(default_factory=list)
    # Adversarial cases embed a false premise in the question; their verdict
    # additionally requires the answer to challenge that premise (spec §32).
    adversarial: bool = False
    project_id: str | None = None


class EvalRequest(BaseModel):
    """Payload for ``POST /evals/run``: a dataset plus run options."""

    dataset: list[EvalCaseInput] = Field(min_length=1)
    project_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=15)
    thresholds: EvalThresholds | None = None


class EvalMetricsRead(BaseModel):
    """Computed per-case metrics, all normalized to 0..1."""

    correctness: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    groundedness: float = Field(ge=0.0, le=1.0)
    hallucination_rate: float = Field(ge=0.0, le=1.0)
    source_quality: float = Field(ge=0.0, le=1.0)
    challenged_premise: bool


class EvalSourceRead(BaseModel):
    """One retrieved source shown alongside an answer."""

    title: str
    score: float


class EvalCaseResultRead(BaseModel):
    """Per-case outcome: answer, sources, metrics and verdict."""

    case_name: str
    adversarial: bool
    question: str
    answer: str
    sources: list[EvalSourceRead]
    metrics: EvalMetricsRead
    verdict: Literal["pass", "fail", "error"]
    reason: str | None


class EvalRunSummary(BaseModel):
    """Counts across the cases of one evaluation run."""

    total: int
    passes: int
    fails: int
    errors: int


class EvalRunRead(BaseModel):
    """Result of one evaluation run: summary plus per-case details."""

    summary: EvalRunSummary
    cases: list[EvalCaseResultRead]


class EvalRunHistoryItem(BaseModel):
    """One persisted run in the history listing (newest first)."""

    run_id: str
    case_name: str
    verdict: str
    created_at: datetime
    metrics: dict


class EvalRunHistoryRead(BaseModel):
    """History of evaluation runs, newest first."""

    items: list[EvalRunHistoryItem]