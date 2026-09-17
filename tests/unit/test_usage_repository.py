"""Unit tests for UsageRepository over in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.usage import LLMUsage
from app.repositories.usage_repository import UsageRepository


async def _create_row(
    session: AsyncSession,
    *,
    request_id: str = "req-1",
    provider: str = "ollama",
    model: str = "gemma4:26b",
    prompt_tokens: int | None = 10,
    completion_tokens: int | None = 5,
    estimated_cost_usd: float = 0.0,
    latency_ms: int = 42,
    created_at: datetime | None = None,
) -> LLMUsage:
    """Persist one usage row, optionally pinning its creation time."""
    row = await UsageRepository(session).create(
        request_id=request_id,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
        latency_ms=latency_ms,
    )
    if created_at is not None:
        row.created_at = created_at
        await session.commit()
    return row


async def test_create_persists_row_with_all_fields(db_session) -> None:
    row = await _create_row(
        db_session,
        request_id="req-abc",
        provider="payperq",
        model="some-model",
        prompt_tokens=100,
        completion_tokens=50,
        estimated_cost_usd=2.5,
        latency_ms=123,
    )

    assert row.id and len(row.id) == 36
    assert row.request_id == "req-abc"
    assert row.provider == "payperq"
    assert row.model == "some-model"
    assert row.prompt_tokens == 100
    assert row.completion_tokens == 50
    assert row.estimated_cost_usd == 2.5
    assert row.latency_ms == 123
    assert row.created_at is not None


async def test_create_allows_null_tokens(db_session) -> None:
    row = await _create_row(db_session, prompt_tokens=None, completion_tokens=None)

    assert row.prompt_tokens is None
    assert row.completion_tokens is None
    assert row.estimated_cost_usd == 0.0


async def test_list_recent_returns_newest_first(db_session) -> None:
    await _create_row(
        db_session, request_id="req-1", created_at=datetime(2026, 9, 17, 9, tzinfo=UTC)
    )
    await _create_row(
        db_session, request_id="req-2", created_at=datetime(2026, 9, 17, 10, tzinfo=UTC)
    )
    await _create_row(
        db_session, request_id="req-3", created_at=datetime(2026, 9, 17, 11, tzinfo=UTC)
    )

    rows = await UsageRepository(db_session).list_recent()

    assert [r.request_id for r in rows] == ["req-3", "req-2", "req-1"]


async def test_list_recent_honors_limit(db_session) -> None:
    for i in range(5):
        await _create_row(
            db_session,
            request_id=f"req-{i}",
            created_at=datetime(2026, 9, 17, 9, i, tzinfo=UTC),
        )

    rows = await UsageRepository(db_session).list_recent(limit=2)

    assert [r.request_id for r in rows] == ["req-4", "req-3"]


async def test_totals_sums_all_rows(db_session) -> None:
    await _create_row(
        db_session,
        provider="payperq",
        prompt_tokens=100,
        completion_tokens=50,
        estimated_cost_usd=2.0,
    )
    await _create_row(
        db_session,
        provider="payperq",
        prompt_tokens=200,
        completion_tokens=100,
        estimated_cost_usd=4.5,
    )

    totals = await UsageRepository(db_session).totals()

    assert totals.total_requests == 2
    assert totals.total_prompt_tokens == 300
    assert totals.total_completion_tokens == 150
    assert totals.total_cost_usd == 6.5


async def test_totals_empty_database_returns_zeros(db_session) -> None:
    totals = await UsageRepository(db_session).totals()

    assert totals.total_requests == 0
    assert totals.total_prompt_tokens == 0
    assert totals.total_completion_tokens == 0
    assert totals.total_cost_usd == 0.0


async def test_per_provider_groups_and_orders_by_cost_desc(db_session) -> None:
    await _create_row(
        db_session,
        provider="payperq",
        prompt_tokens=100,
        completion_tokens=100,
        estimated_cost_usd=4.0,
    )
    await _create_row(
        db_session,
        provider="payperq",
        prompt_tokens=50,
        completion_tokens=50,
        estimated_cost_usd=2.0,
    )
    await _create_row(
        db_session,
        provider="ollama",
        prompt_tokens=10,
        completion_tokens=5,
        estimated_cost_usd=0.0,
    )

    by_provider = await UsageRepository(db_session).per_provider()

    assert [(p.provider, p.cost_usd) for p in by_provider] == [
        ("payperq", 6.0),
        ("ollama", 0.0),
    ]
    assert by_provider[0].requests == 2
    assert by_provider[0].prompt_tokens == 150
    assert by_provider[0].completion_tokens == 150
    assert by_provider[1].requests == 1
    assert by_provider[1].prompt_tokens == 10


async def test_per_provider_empty_database_returns_empty(db_session) -> None:
    by_provider = await UsageRepository(db_session).per_provider()

    assert by_provider == []