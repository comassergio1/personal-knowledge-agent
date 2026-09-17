"""Async persistence and aggregates for per-request LLM usage.

The repository works with SQLAlchemy `AsyncSession` only (same contract as
`DocumentRepository`); queries use plain SQLAlchemy expressions so a swap to
Postgres/asyncpg would not touch this module (spec §30).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.usage import LLMUsage


@dataclass
class UsageTotals:
    """Aggregate counters across all recorded usage rows."""

    total_requests: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float


@dataclass
class UsageByProvider:
    """Usage aggregates grouped by provider, ordered by cost descending."""

    provider: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class UsageRepository:
    """CRUD and aggregates over `LLMUsage` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        request_id: str,
        provider: str,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        estimated_cost_usd: float,
        latency_ms: int,
    ) -> LLMUsage:
        """Persist one usage row and return it."""
        row = LLMUsage(
            request_id=request_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
        )
        self._session.add(row)
        await self._session.commit()
        return row

    async def list_recent(self, limit: int = 20) -> Sequence[LLMUsage]:
        """Return the newest ``limit`` usage rows, newest first."""
        stmt = (
            select(LLMUsage)
            .order_by(LLMUsage.created_at.desc(), LLMUsage.id.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def totals(self) -> UsageTotals:
        """Return aggregate counters across all usage rows."""
        stmt = select(
            func.count(LLMUsage.id),
            func.coalesce(func.sum(LLMUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LLMUsage.completion_tokens), 0),
            func.coalesce(func.sum(LLMUsage.estimated_cost_usd), 0.0),
        )
        row = (await self._session.execute(stmt)).one()
        return UsageTotals(
            total_requests=row[0],
            total_prompt_tokens=row[1],
            total_completion_tokens=row[2],
            total_cost_usd=row[3],
        )

    async def per_provider(self) -> Sequence[UsageByProvider]:
        """Return per-provider aggregates ordered by cost descending."""
        stmt = (
            select(
                LLMUsage.provider,
                func.count(LLMUsage.id),
                func.coalesce(func.sum(LLMUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LLMUsage.completion_tokens), 0),
                func.coalesce(func.sum(LLMUsage.estimated_cost_usd), 0.0),
            )
            .group_by(LLMUsage.provider)
            .order_by(func.sum(LLMUsage.estimated_cost_usd).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            UsageByProvider(
                provider=row[0],
                requests=row[1],
                prompt_tokens=row[2],
                completion_tokens=row[3],
                cost_usd=row[4],
            )
            for row in rows
        ]