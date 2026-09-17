"""Unit tests for ProjectRepository over in-memory SQLite."""

from __future__ import annotations

import pytest

from app.repositories.project_repository import (
    ProjectNameConflict,
    ProjectRepository,
)


async def test_create_and_get_by_id(db_session) -> None:
    repo = ProjectRepository(db_session)
    project = await repo.create(name="Research", description="Deep dive")

    fetched = await repo.get_by_id(project.id)
    assert fetched is not None
    assert fetched.id == project.id
    assert fetched.name == "Research"
    assert fetched.description == "Deep dive"
    assert fetched.created_at is not None
    assert fetched.updated_at is not None

    assert await repo.get_by_id("missing-id") is None


async def test_create_description_optional(db_session) -> None:
    project = await ProjectRepository(db_session).create(name="Notes")
    assert project.description is None


async def test_get_by_name(db_session) -> None:
    repo = ProjectRepository(db_session)
    await repo.create(name="Alpha")

    assert await repo.get_by_name("Alpha") is not None
    assert await repo.get_by_name("missing") is None


async def test_duplicate_name_raises_friendly_conflict(db_session) -> None:
    repo = ProjectRepository(db_session)
    await repo.create(name="Alpha")

    with pytest.raises(ProjectNameConflict):
        await repo.create(name="Alpha")


async def test_list_returns_all_projects(db_session) -> None:
    repo = ProjectRepository(db_session)
    await repo.create(name="A")
    await repo.create(name="B")

    names = [p.name for p in await repo.list()]
    assert set(names) == {"A", "B"}


async def test_delete_removes_row_and_reports_missing(db_session) -> None:
    repo = ProjectRepository(db_session)
    project = await repo.create(name="Gone")

    assert await repo.delete(project.id) is True
    assert await repo.get_by_id(project.id) is None
    assert await repo.delete(project.id) is False