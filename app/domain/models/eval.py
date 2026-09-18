"""SQLAlchemy 2.0 mapped models for knowledge evaluations (spec §31/§32).

Evaluations are knowledge-system health checks, not a memory source: an
``EvalCase`` is a question plus the facts it must cover (optionally with a
false premise embedded for adversarial testing), and an ``EvalRun`` captures
one execution of a case: the answer, the sources it was grounded on, the
computed metrics and the verdict. Runs persist for history only; they never
pollute prompts or memories.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base

EVAL_VERDICTS = ("pass", "fail")


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EvalCase(Base):
    """One evaluation case: a question, its expected facts and its setup."""

    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    expected_facts: Mapped[list] = mapped_column(JSON, default=list)
    # Adversarial cases embed a false premise in the question; the judge must
    # check whether the answer explicitly disputes that premise (spec §32).
    adversarial: Mapped[bool] = mapped_column(Boolean, default=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    def __repr__(self) -> str:
        return f"<EvalCase id={self.id!r} name={self.name!r} adversarial={self.adversarial!r}>"


class EvalRun(Base):
    """One execution of an ``EvalCase``: answer, sources, metrics, verdict."""

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("eval_cases.id"), index=True
    )
    answer: Mapped[str] = mapped_column(Text)
    # Retrieved sources as ``{"title", "content", "score"}`` dicts plus the
    # per-case metrics dict straight from the metrics/judge module.
    sources: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    verdict: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<EvalRun id={self.id!r} case_id={self.case_id!r} "
            f"verdict={self.verdict!r}>"
        )