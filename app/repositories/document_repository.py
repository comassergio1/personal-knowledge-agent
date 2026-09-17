"""Async persistence for documents and their chunks.

The repository works with SQLAlchemy `AsyncSession` only; domain and schema
layers stay SQL-engine-agnostic (a swap to Postgres/asyncpg would not touch
them).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.document import Chunk, Document


class DocumentRepository:
    """CRUD over `Document` rows, always deleting chunks with their document."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        title: str,
        content: str,
        mime_type: str,
        source_type: str = "text",
        source_uri: str | None = None,
        project_id: str | None = None,
        chunks: Sequence[Chunk] | None = None,
    ) -> Document:
        """Create a document with its chunks in one transaction."""
        document = Document(
            title=title,
            content=content,
            mime_type=mime_type,
            source_type=source_type,
            source_uri=source_uri,
            project_id=project_id,
        )
        # Always initialize the collection so it is never lazy-loaded in an
        # async context after commit.
        document.chunks = list(chunks) if chunks else []
        self._session.add(document)
        await self._session.commit()
        return document

    async def get(self, document_id: str) -> Document | None:
        """Return one document (chunks loaded) or None."""
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id)
        )
        return await self._session.scalar(stmt)

    async def list(self) -> Sequence[Document]:
        """Return all documents (chunks loaded), newest first."""
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .order_by(Document.created_at.desc())
        )
        return (await self._session.scalars(stmt)).all()

    async def delete(self, document_id: str) -> bool:
        """Delete a document and its chunks. Returns False when not found."""
        document = await self.get(document_id)
        if document is None:
            return False
        await self._session.delete(document)
        await self._session.commit()
        return True