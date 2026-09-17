"""Async persistence for projects (spec §17)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.project import Project


class ProjectNameConflict(Exception):
    """Raised when creating a project under an existing name (unique constraint)."""


class ProjectRepository:
    """CRUD over ``Project`` rows; name conflicts surface as friendly errors."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, name: str, description: str | None = None
    ) -> Project:
        """Create a project. Raises ``ProjectNameConflict`` on a duplicate name."""
        if await self.get_by_name(name) is not None:
            raise ProjectNameConflict(f"A project named {name!r} already exists")
        project = Project(name=name, description=description)
        self._session.add(project)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ProjectNameConflict(f"A project named {name!r} already exists") from exc
        return project

    async def get_by_id(self, project_id: str) -> Project | None:
        """Return one project by id, or None."""
        return await self._session.get(Project, project_id)

    async def get_by_name(self, name: str) -> Project | None:
        """Return one project by exact name, or None."""
        stmt = select(Project).where(Project.name == name)
        return await self._session.scalar(stmt)

    async def list(self) -> Sequence[Project]:
        """Return all projects, newest first."""
        stmt = select(Project).order_by(Project.created_at.desc())
        return (await self._session.scalars(stmt)).all()

    async def delete(self, project_id: str) -> bool:
        """Delete a project row. Returns False when it is not found.

        Deleting the project does not touch its documents here: the API route
        removes rows, vector points, and vault files in an explicit cascade.
        """
        project = await self._session.get(Project, project_id)
        if project is None:
            return False
        await self._session.delete(project)
        await self._session.commit()
        return True