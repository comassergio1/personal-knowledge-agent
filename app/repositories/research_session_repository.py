"""Async persistence for research sessions and their turns.

The repository works with SQLAlchemy `AsyncSession` only (same contract as
`MemoryRepository`); queries use plain SQLAlchemy expressions so a swap to
Postgres/asyncpg would not touch this module. Every write commits exactly
once, releasing the SQLite write lock (same discipline as the other
repositories). Sessions are app-lifetime; the service owns the conversation
rules (trigger detection, roles) and this class only persists state.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.research_session import ResearchSession, ResearchTurn


class ResearchSessionRepository:
    """CRUD over research session rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(self, title: str) -> ResearchSession:
        """Persist one session row and return it."""
        row = ResearchSession(title=title)
        self._session.add(row)
        await self._session.commit()
        return row

    async def get_session(self, session_id: str) -> ResearchSession | None:
        """Return one session row or None."""
        return await self._session.get(ResearchSession, session_id)

    async def list(self) -> Sequence[ResearchSession]:
        """Return sessions ordered by most recent activity first."""
        stmt = select(ResearchSession).order_by(
            ResearchSession.updated_at.desc(), ResearchSession.id.desc()
        )
        return (await self._session.scalars(stmt)).all()

    async def update_title(
        self, session_id: str, title: str
    ) -> ResearchSession | None:
        """Replace a session's title. Returns None when the session is missing."""
        session = await self.get_session(session_id)
        if session is None:
            return None
        session.title = title
        await self._session.commit()
        return session

    async def add_turn(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        kind: str = "answer",
        research_document_id: str | None = None,
        sources: list | None = None,
    ) -> ResearchTurn:
        """Append one turn to a session and bump the session's activity.

        The activity bump keeps the ``list`` ordering (most recent activity
        first). Raises ``ValueError`` when the session does not exist, so an
        orphan turn can never be persisted.
        """
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"unknown research session: {session_id}")
        turn = ResearchTurn(
            session_id=session_id,
            role=role,
            content=content,
            kind=kind,
            research_document_id=research_document_id,
            sources=sources,
        )
        self._session.add(turn)
        session.updated_at = datetime.now(UTC)
        await self._session.commit()
        return turn

    async def list_turns(self, session_id: str) -> Sequence[ResearchTurn]:
        """Return the session's turns in thread order (oldest first)."""
        stmt = (
            select(ResearchTurn)
            .where(ResearchTurn.session_id == session_id)
            .order_by(ResearchTurn.created_at.asc())
        )
        return (await self._session.scalars(stmt)).all()

    async def count_turns(self, session_id: str) -> int:
        """Return how many turns a session has (0 for unknown sessions)."""
        stmt = select(func.count(ResearchTurn.id)).where(
            ResearchTurn.session_id == session_id
        )
        return int((await self._session.execute(stmt)).scalar_one())