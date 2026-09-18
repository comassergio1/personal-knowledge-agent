"""Async persistence for memories (spec §13).

The repository works with SQLAlchemy `AsyncSession` only (same contract as
`DocumentRepository`); a swap to Postgres/asyncpg would not touch the domain
or schema layers. Every write operation commits exactly once, releasing the
SQLite write lock (same discipline as `UsageRepository`).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.memory import Memory


class MemoryRepository:
    """CRUD over `Memory` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_candidates(
        self, candidates: Sequence[dict]
    ) -> Sequence[Memory]:
        """Persist extracted candidates with ``status="candidate"``.

        Each dict follows the extractor's JSON contract: ``{"type", "content",
        "confidence"}`` with an optional ``"source"``. ``type`` maps to the
        model's ``memory_type`` attribute.
        """
        rows = [
            Memory(
                memory_type=c["type"],
                content=c["content"],
                source=c.get("source"),
                confidence=c.get("confidence", 0.5),
            )
            for c in candidates
        ]
        self._session.add_all(rows)
        await self._session.commit()
        return rows

    async def get(self, memory_id: str) -> Memory | None:
        """Return one memory row or None."""
        stmt = select(Memory).where(Memory.id == memory_id)
        return await self._session.scalar(stmt)

    async def list(
        self,
        memory_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[Memory]:
        """Return memories, newest first, optionally filtered by type/status."""
        stmt = select(Memory).order_by(Memory.created_at.desc())
        if memory_type is not None:
            stmt = stmt.where(Memory.memory_type == memory_type)
        if status is not None:
            stmt = stmt.where(Memory.status == status)
        return (await self._session.scalars(stmt)).all()

    async def set_status(self, memory_id: str, status: str) -> Memory | None:
        """Flip a memory's status and commit. Returns None when missing.

        The route layer owns the lifecycle rule (only candidates may be
        approved/rejected); this method only persists the requested value.
        """
        memory = await self.get(memory_id)
        if memory is None:
            return None
        if memory.status != status:
            memory.status = status
            await self._session.commit()
        return memory

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory row. Returns False when not found."""
        memory = await self.get(memory_id)
        if memory is None:
            return False
        await self._session.delete(memory)
        await self._session.commit()
        return True