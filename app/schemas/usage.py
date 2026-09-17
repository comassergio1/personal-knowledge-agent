"""Pydantic schemas for the usage endpoint (spec §30)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UsageRowRead(BaseModel):
    """One recorded LLM usage row, as returned to API consumers."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    estimated_cost_usd: float
    latency_ms: int
    created_at: datetime


class UsageTotalsRead(BaseModel):
    """Aggregate counters across all recorded usage rows."""

    model_config = ConfigDict(from_attributes=True)

    total_requests: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float


class UsageByProviderRead(BaseModel):
    """Usage aggregates for one provider, ordered by cost descending."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class UsageSummary(BaseModel):
    """Response payload for GET /api/v1/usage."""

    recent: list[UsageRowRead]
    totals: UsageTotalsRead
    per_provider: list[UsageByProviderRead]