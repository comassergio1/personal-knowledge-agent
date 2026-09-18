"""Async persistence for documents and their chunks.

The repository works with SQLAlchemy `AsyncSession` only; domain and schema
layers stay SQL-engine-agnostic (a swap to Postgres/asyncpg would not touch
them).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

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
        file_path: str | None = None,
        file_mtime: datetime | None = None,
        content_hash: str | None = None,
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
            file_path=file_path,
            file_mtime=file_mtime,
            content_hash=content_hash,
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

    async def get_by_file_path(self, rel_path: str) -> Document | None:
        """Return the document stored for a vault-relative path, or None."""
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.file_path == rel_path)
        )
        return await self._session.scalar(stmt)

    async def list_with_file_paths(self) -> Sequence[Document]:
        """Return every document that has a vault file (chunks NOT loaded).

        Used by vault sync to reconcile rows against the files on disk; the
        chunk rows are not needed, so they stay unloaded to keep the scan fast.
        """
        stmt = select(Document).where(Document.file_path.is_not(None))
        return (await self._session.scalars(stmt)).all()

    async def list(self, project_id: str | None = None) -> Sequence[Document]:
        """Return documents (chunks loaded), newest first, optionally scoped.

        ``project_id`` filters the rows to one project; the default (None)
        keeps the historical behavior of listing every document.
        """
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .order_by(Document.created_at.desc())
        )
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)
        return (await self._session.scalars(stmt)).all()

    async def find_by_content_hash(
        self, content_hash: str, project_id: str | None
    ) -> Document | None:
        """Return an existing document with the same content hash in the same
        project scope (chunks loaded), or None.

        Backs idempotent ingestion: re-uploading identical content into the
        same project returns the existing document instead of adding duplicate
        rows and vectors (evals surfaced duplicated copies degrading retrieval
        recall).
        """
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(
                Document.content_hash == content_hash,
                Document.project_id == project_id,
            )
        )
        return await self._session.scalar(stmt)

    async def replace_file_content(
        self,
        document_id: str,
        *,
        content: str,
        file_mtime: datetime,
        chunks: Sequence[Chunk],
    ) -> Document | None:
        """Replace a document's content and chunks, bumping ``updated_at``.

        The old chunk rows are cascade-deleted on commit and the new ones take
        their place. ``file_mtime`` is refreshed to the file's current mtime so
        the row is no longer stale. Returns None when the document is missing.
        """
        document = await self.get(document_id)
        if document is None:
            return None
        document.content = content
        document.file_mtime = file_mtime
        document.updated_at = datetime.now(UTC)
        document.chunks = list(chunks)
        await self._session.commit()
        return document

    async def delete(self, document_id: str) -> bool:
        """Delete a document and its chunks. Returns False when not found."""
        document = await self.get(document_id)
        if document is None:
            return False
        await self._session.delete(document)
        await self._session.commit()
        return True

    async def update_chunk_embedding_ids(
        self, pairs: Sequence[tuple[str, str]]
    ) -> None:
        """Persist ``(chunk_id, embedding_id)`` pairs in one committed write.

        The chunk rows are already tracked by this session (created together
        with the document), so mutation + a single :meth:`commit` persists
        them. Committing is what releases the SQLite write lock: an earlier
        version reused mutating objects on the shared app-scoped session
        without committing, leaving an open write transaction that locked the
        database for every later writer (observed live as "database is
        locked" on the ``llm_usage`` insert).
        """
        for chunk_id, embedding_id in pairs:
            chunk = await self._session.get(Chunk, chunk_id)
            if chunk is not None:
                chunk.embedding_id = embedding_id
        await self._session.commit()