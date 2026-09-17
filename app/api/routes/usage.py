"""Usage endpoint: recent rows, totals, and per-provider breakdown (spec §30)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.repositories.usage_repository import UsageRepository
from app.schemas.usage import (
    UsageByProviderRead,
    UsageRowRead,
    UsageSummary,
    UsageTotalsRead,
)

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=UsageSummary)
async def get_usage(
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UsageSummary:
    """Return recent usage rows (newest first), totals, and a provider breakdown."""
    repository = UsageRepository(session)
    recent = await repository.list_recent(limit=limit)
    totals = await repository.totals()
    per_provider = await repository.per_provider()
    return UsageSummary(
        recent=[UsageRowRead.model_validate(row) for row in recent],
        totals=UsageTotalsRead.model_validate(totals),
        per_provider=[UsageByProviderRead.model_validate(item) for item in per_provider],
    )