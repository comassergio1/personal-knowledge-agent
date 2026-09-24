"""Unit tests for ResearchSessionRepository over in-memory SQLite."""

from __future__ import annotations

import pytest

from app.repositories.research_session_repository import (
    ResearchSessionRepository,
)


async def test_create_session_persists_title_and_timestamps(db_session) -> None:
    repo = ResearchSessionRepository(db_session)

    session = await repo.create_session("VLANs en MikroTik")

    assert len(session.id) == 36
    assert session.title == "VLANs en MikroTik"
    assert session.created_at is not None
    assert session.updated_at is not None


async def test_get_session_returns_one_or_none(db_session) -> None:
    repo = ResearchSessionRepository(db_session)
    created = await repo.create_session("Tema")

    fetched = await repo.get_session(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Tema"

    assert await repo.get_session("missing-id") is None


async def test_list_returns_sessions_newest_activity_first(db_session) -> None:
    repo = ResearchSessionRepository(db_session)
    first = await repo.create_session("Primera")
    second = await repo.create_session("Segunda")

    rows = await repo.list()

    assert [row.id for row in rows] == [second.id, first.id]


async def test_add_turn_persists_fields_and_bumps_session_activity(db_session) -> None:
    repo = ResearchSessionRepository(db_session)
    session = await repo.create_session("Tema")
    before = session.updated_at

    turn = await repo.add_turn(
        session.id,
        role="user",
        content="buscar en la web asyncio",
    )
    research_turn = await repo.add_turn(
        session.id,
        role="assistant",
        content="Resumen",
        kind="research",
        research_document_id="doc-123",
        sources=[{"title": "A", "url": "https://a.example"}],
    )

    assert turn.role == "user"
    assert turn.kind == "answer"
    assert turn.research_document_id is None
    assert turn.sources is None
    assert research_turn.kind == "research"
    assert research_turn.research_document_id == "doc-123"
    assert research_turn.sources == [{"title": "A", "url": "https://a.example"}]

    # Adding a turn refreshes the session's updated_at (list ordering).
    refreshed = await repo.get_session(session.id)
    assert refreshed is not None
    assert refreshed.updated_at >= before


async def test_add_turn_orders_turns_by_creation(db_session) -> None:
    repo = ResearchSessionRepository(db_session)
    session = await repo.create_session("Tema")
    await repo.add_turn(session.id, role="user", content="uno")
    await repo.add_turn(session.id, role="assistant", content="dos")

    turns = await repo.list_turns(session.id)

    assert [(t.role, t.content) for t in turns] == [
        ("user", "uno"),
        ("assistant", "dos"),
    ]


async def test_add_turn_rejects_unknown_session(db_session) -> None:
    repo = ResearchSessionRepository(db_session)

    with pytest.raises(ValueError):
        await repo.add_turn("missing-id", role="user", content="hola")


async def test_count_turns_is_zero_then_grows(db_session) -> None:
    repo = ResearchSessionRepository(db_session)
    session = await repo.create_session("Tema")

    assert await repo.count_turns(session.id) == 0

    await repo.add_turn(session.id, role="user", content="uno")
    await repo.add_turn(session.id, role="assistant", content="dos")

    assert await repo.count_turns(session.id) == 2


async def test_update_title_changes_session_title(db_session) -> None:
    repo = ResearchSessionRepository(db_session)
    session = await repo.create_session("Sesión de investigación")

    updated = await repo.update_title(session.id, "asyncio")

    assert updated is not None
    assert updated.title == "asyncio"
    fetched = await repo.get_session(session.id)
    assert fetched is not None
    assert fetched.title == "asyncio"

    assert await repo.update_title("missing-id", "x") is None