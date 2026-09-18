"""Unit tests for MemoryRepository over in-memory SQLite."""

from __future__ import annotations

from app.repositories.memory_repository import MemoryRepository


def _candidates():
    return [
        {"type": "semantic", "content": "User prefers concise answers", "confidence": 0.9},
        {"type": "episodic", "content": "On Tuesday the user asked about Qdrant", "confidence": 0.6},
        {
            "type": "preference",
            "content": "Notes are written in Obsidian",
            "confidence": 0.4,
            "source": "vault",
        },
    ]


async def test_create_candidates_persists_with_default_status(db_session) -> None:
    repo = MemoryRepository(db_session)

    rows = await repo.create_candidates(_candidates())

    assert len(rows) == 3
    for row in rows:
        assert len(row.id) == 36
        assert row.status == "candidate"
        assert row.confidence in (0.9, 0.6, 0.4)
        assert row.created_at is not None
        assert row.updated_at is not None


async def test_get_returns_one_or_none(db_session) -> None:
    repo = MemoryRepository(db_session)
    created = await repo.create_candidates(_candidates())

    fetched = await repo.get(created[0].id)

    assert fetched is not None
    assert fetched.id == created[0].id
    assert fetched.memory_type == "semantic"
    assert fetched.content == "User prefers concise answers"
    assert fetched.source is None

    assert await repo.get("missing-id") is None


async def test_list_returns_newest_first(db_session) -> None:
    repo = MemoryRepository(db_session)
    await repo.create_candidates(_candidates())

    rows = await repo.list()

    assert len(rows) == 3
    timestamps = [row.created_at for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_list_filters_by_type(db_session) -> None:
    repo = MemoryRepository(db_session)
    await repo.create_candidates(_candidates())

    semantic = await repo.list(memory_type="semantic")
    episodic = await repo.list(memory_type="episodic")

    assert [m.content for m in semantic] == ["User prefers concise answers"]
    assert [m.content for m in episodic] == ["On Tuesday the user asked about Qdrant"]
    assert await repo.list(memory_type="procedural") == []


async def test_list_filters_by_status(db_session) -> None:
    repo = MemoryRepository(db_session)
    created = await repo.create_candidates(_candidates())
    await repo.set_status(created[0].id, "approved")

    approved = await repo.list(status="approved")
    candidates = await repo.list(status="candidate")

    assert [m.id for m in approved] == [created[0].id]
    # Inserted rows may share a created_at microsecond, so only membership is
    # asserted (ordering is enforced in test_list_returns_newest_first).
    assert {m.id for m in candidates} == {created[1].id, created[2].id}


async def test_set_status_flips_status_and_bumps_updated_at(db_session) -> None:
    repo = MemoryRepository(db_session)
    created = (await repo.create_candidates(_candidates()))[0]

    flipped = await repo.set_status(created.id, "approved")

    assert flipped is not None
    assert flipped.status == "approved"
    assert flipped.updated_at >= flipped.created_at

    fetched = await repo.get(created.id)
    assert fetched is not None
    assert fetched.status == "approved"


async def test_set_status_missing_returns_none(db_session) -> None:
    repo = MemoryRepository(db_session)
    assert await repo.set_status("missing-id", "approved") is None


async def test_set_status_same_status_is_idempotent(db_session) -> None:
    repo = MemoryRepository(db_session)
    created = (await repo.create_candidates(_candidates()))[0]

    same = await repo.set_status(created.id, "candidate")

    assert same is not None
    assert same.status == "candidate"


async def test_delete_removes_row_and_returns_true(db_session) -> None:
    repo = MemoryRepository(db_session)
    created = (await repo.create_candidates(_candidates()))[0]

    deleted = await repo.delete(created.id)

    assert deleted is True
    assert await repo.get(created.id) is None
    assert len(await repo.list()) == 2


async def test_delete_missing_returns_false(db_session) -> None:
    repo = MemoryRepository(db_session)
    assert await repo.delete("missing-id") is False