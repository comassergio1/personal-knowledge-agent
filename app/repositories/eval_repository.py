"""Async persistence for knowledge evaluations (spec §31/§32).

Same contract as the other repositories: SQLAlchemy ``AsyncSession`` only,
and every write operation commits exactly once, releasing the SQLite write
lock. Runs are stored for history; they are never fed back into retrieval.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.eval import EvalCase, EvalRun


class EvalRepository:
    """CRUD over ``EvalCase`` and ``EvalRun`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_case(
        self,
        *,
        question: str,
        name: str | None = None,
        expected_facts: Sequence[str] | None = None,
        adversarial: bool = False,
        project_id: str | None = None,
    ) -> EvalCase:
        """Persist one evaluation case and commit."""
        case = EvalCase(
            name=name,
            question=question,
            expected_facts=list(expected_facts or []),
            adversarial=adversarial,
            project_id=project_id,
        )
        self._session.add(case)
        await self._session.commit()
        return case

    async def get_case(self, case_id: str) -> EvalCase | None:
        """Return one eval case or None."""
        stmt = select(EvalCase).where(EvalCase.id == case_id)
        return await self._session.scalar(stmt)

    async def list_cases(self) -> Sequence[EvalCase]:
        """Return all eval cases, newest first."""
        stmt = select(EvalCase).order_by(EvalCase.created_at.desc())
        return (await self._session.scalars(stmt)).all()

    async def create_run(
        self,
        *,
        case_id: str,
        answer: str,
        sources: Sequence[dict] | None = None,
        metrics: dict | None = None,
        verdict: str = "fail",
    ) -> EvalRun:
        """Persist one eval run for a case and commit.

        The caller (EvalService) owns metrics/verdict computation; this method
        only persists the given values.
        """
        run = EvalRun(
            case_id=case_id,
            answer=answer,
            sources=list(sources or []),
            metrics=dict(metrics or {}),
            verdict=verdict,
        )
        self._session.add(run)
        await self._session.commit()
        return run

    async def list_runs(self, limit: int = 20) -> Sequence[EvalRun]:
        """Return the most recent runs, newest first, capped at ``limit``."""
        stmt = (
            select(EvalRun)
            .order_by(EvalRun.created_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()