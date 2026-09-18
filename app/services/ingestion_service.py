"""Document ingestion: chunk, persist, embed, and upsert vectors (spec §14/§15).

The service orchestrates the slice's storage steps: deterministic chunking of
the raw content, one ``Document`` row with its ``Chunk`` rows, one embedding
call per chunk, and one vector point per chunk upserted into Qdrant.

Since Phase 3 the vault file on disk is the source of truth (spec §14/§17):
markdown/plain-text uploads are written into the vault before persisting and
PDFs are copied there, so every ingested document records its vault-relative
``file_path`` and the file's ``file_mtime``. The service also owns the vault
reconciliation primitives (detail with staleness, resync, delete) so routes
and the vault sync service never touch the vault or vector store directly.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from io import BytesIO

from pypdf import PdfReader

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.models.document import Chunk, Document
from app.providers.embeddings.base import EmbeddingProvider, EmbeddingProviderError
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.document import DocumentDetail
from app.services.chunking import chunk_text
from app.services.vault_service import VaultService
from app.vector.collections import (
    CHUNK_ID_FIELD,
    CHUNK_INDEX_FIELD,
    CONTENT_FIELD,
    DOCUMENT_ID_FIELD,
    FILE_PATH_FIELD,
    METADATA_FIELD,
    PROJECT_ID_FIELD,
    TITLE_FIELD,
)
from app.vector.qdrant import QdrantVectorStore, VectorPoint

# Vault folder for documents that belong to no project (the default project).
INBOX = "inbox"

PDF_MIME_TYPE = "application/pdf"


class IngestionError(Exception):
    """Raised when a document cannot be embedded or stored in the vector store."""


class ResyncError(Exception):
    """Raised when a document cannot be resynced from its vault file."""


def as_naive_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to naive UTC for cross-source comparisons.

    Vault mtimes are timezone-aware while SQLite returns naive datetimes, so
    comparisons must normalize both sides (aware/naive ordering raises).
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _is_stale(
    disk_mtime: datetime,
    file_mtime: datetime | None,
    updated_at: datetime,
) -> bool:
    """True when the file on disk is newer than both recorded datetimes."""
    disk = as_naive_utc(disk_mtime)
    for recorded in (file_mtime, updated_at):
        normalized = as_naive_utc(recorded)
        if normalized is not None and disk <= normalized:
            return False
    return True


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract the concatenated text of a PDF (blocking; run in a thread)."""
    reader = PdfReader(BytesIO(pdf_bytes), strict=False)
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


class IngestionService:
    """Chunks, persists, embeds, and upserts one document at a time."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        vector_store: QdrantVectorStore,
        embeddings: EmbeddingProvider,
        vault: VaultService | None = None,
        projects: ProjectRepository | None = None,
    ) -> None:
        self._documents = document_repository
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._vault = vault
        self._projects = projects
        self._logger = get_logger("ingestion_service")

    async def _project_name(self, project_id: str | None) -> str:
        """Return the project's name, or ``INBOX`` when there is no project."""
        if project_id is None or self._projects is None:
            return INBOX
        project = await self._projects.get_by_id(project_id)
        return project.name if project is not None else INBOX

    async def _store_vectors(self, document: Document) -> Document:
        """Shared tail: embed chunks, upsert vector points, persist ids.

        Raises ``IngestionError`` when embedding or the vector store fails.
        """
        try:
            vectors = [await self._embeddings.embed(c.content) for c in document.chunks]
        except EmbeddingProviderError as exc:
            raise IngestionError(f"Failed to embed document chunks: {exc}") from exc

        points = [
            VectorPoint(
                id=chunk.id,
                vector=vector,
                payload={
                    DOCUMENT_ID_FIELD: document.id,
                    CHUNK_ID_FIELD: chunk.id,
                    CHUNK_INDEX_FIELD: chunk.chunk_index,
                    TITLE_FIELD: document.title,
                    CONTENT_FIELD: chunk.content,
                    PROJECT_ID_FIELD: document.project_id,
                    FILE_PATH_FIELD: document.file_path,
                    METADATA_FIELD: {
                        **dict(chunk.metadata_ or {}),
                        CHUNK_INDEX_FIELD: chunk.chunk_index,
                        PROJECT_ID_FIELD: document.project_id,
                        FILE_PATH_FIELD: document.file_path,
                    },
                },
            )
            for chunk, vector in zip(document.chunks, vectors)
        ]
        try:
            await self._vector_store.upsert_chunks(points)
        except Exception as exc:
            # qdrant-client transport errors share no common base class.
            raise IngestionError(f"Failed to upsert vector points: {exc}") from exc

        # Persist embedding ids in a committed write: mutating the tracked
        # objects without committing left an open write transaction on the
        # shared app-scoped session, holding the SQLite write lock and
        # failing later writers ("database is locked") — see the repository
        # method docstring.
        await self._documents.update_chunk_embedding_ids(
            [(chunk.id, chunk.id) for chunk in document.chunks]
        )

        persisted = await self._documents.get(document.id)
        return persisted if persisted is not None else document

    async def ingest(
        self,
        *,
        title: str,
        content: str,
        mime_type: str = "text/markdown",
        source_type: str = "text",
        source_uri: str | None = None,
        project_id: str | None = None,
        file_path: str | None = None,
        file_mtime: datetime | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> Document:
        """Chunk, persist, embed, and upsert ``content``; return the document.

        File ingestion is file-first: when no ``file_path`` is given and the
        service has a vault, the content is written into the vault BEFORE
        persisting (``source_type="file"``), so the row records where the
        source of truth lives. Callers that already hold an on-disk file
        (vault sync) pass its ``file_path``/``file_mtime`` and no write
        happens. Chunk sizing defaults to ``Settings.chunk_size``/
        ``chunk_overlap`` unless explicit values are given. ``chunk_index``
        is mirrored inside the point's ``metadata`` payload so consumers of
        ``SearchHit.metadata`` (``ChatService``) can build chunk-level source
        references.
        """
        if not content.strip():
            raise ValueError("content must not be empty")
        if file_path is None and self._vault is not None and source_type == "file":
            project_name = await self._project_name(project_id)
            target = self._vault.markdown_path(project_name, title)
            self._vault.write_text(target, content)
            file_path = self._vault.relative_path(target)
            file_mtime = self._vault.mtime(file_path)
        elif file_path is not None and file_mtime is None and self._vault is not None:
            file_mtime = self._vault.mtime(file_path)

        settings = get_settings()
        size = settings.chunk_size if chunk_size is None else chunk_size
        overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap

        # Idempotent ingestion: identical content into the same project scope
        # returns the existing document instead of duplicating rows/vectors
        # (evals surfaced duplicate copies degrading retrieval recall).
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = await self._documents.find_by_content_hash(
            content_hash, project_id
        )
        if existing is not None:
            self._logger.info(
                "duplicate content skipped (idempotent ingest)",
                extra={"document_id": existing.id, "content_hash": content_hash[:12]},
            )
            return existing

        chunks = [
            Chunk(chunk_index=index, content=part)
            for index, part in enumerate(chunk_text(content, size=size, overlap=overlap))
        ]
        document = await self._documents.create(
            title=title,
            content=content,
            mime_type=mime_type,
            source_type=source_type,
            source_uri=source_uri,
            project_id=project_id,
            file_path=file_path,
            file_mtime=file_mtime,
            content_hash=content_hash,
            chunks=chunks,
        )
        return await self._store_vectors(document)

    async def ingest_pdf(
        self,
        *,
        title: str,
        pdf_bytes: bytes,
        project_id: str | None = None,
        source_uri: str | None = None,
        file_path: str | None = None,
        file_mtime: datetime | None = None,
    ) -> Document:
        """Copy PDF bytes into the vault, extract text, and ingest it.

        The PDF is stored verbatim under ``<project_folder>/<slug(title)>.pdf``
        (openable from Obsidian) and its text is extracted with pypdf for
        chunking/RAG. An extraction that yields no text still ingests (the
        content may be short) but logs a warning. Callers that already hold an
        on-disk PDF (vault sync) pass its ``file_path``/``file_mtime`` and no
        copy happens.
        """
        if file_path is None:
            if self._vault is None:
                raise ValueError("a VaultService is required to ingest a PDF")
            project_name = await self._project_name(project_id)
            target = self._vault.pdf_path(project_name, title)
            self._vault.write_bytes(target, pdf_bytes)
            file_path = self._vault.relative_path(target)
            file_mtime = self._vault.mtime(file_path)

        extracted = await asyncio.to_thread(_extract_pdf_text, pdf_bytes)
        if not extracted:
            self._logger.warning(
                "pdf text extraction returned no text", extra={"file_path": file_path}
            )

        settings = get_settings()
        content_hash = hashlib.sha256(extracted.encode("utf-8")).hexdigest()
        existing = await self._documents.find_by_content_hash(
            content_hash, project_id
        )
        if existing is not None:
            self._logger.info(
                "duplicate pdf content skipped (idempotent ingest)",
                extra={"document_id": existing.id, "content_hash": content_hash[:12]},
            )
            return existing
        chunks = [
            Chunk(chunk_index=index, content=part)
            for index, part in enumerate(
                chunk_text(
                    extracted, size=settings.chunk_size, overlap=settings.chunk_overlap
                )
            )
        ]
        document = await self._documents.create(
            title=title,
            content=extracted,
            mime_type=PDF_MIME_TYPE,
            source_type="file",
            source_uri=source_uri,
            project_id=project_id,
            file_path=file_path,
            file_mtime=file_mtime,
            content_hash=content_hash,
            chunks=chunks,
        )
        return await self._store_vectors(document)

    def _resolve_detail(self, document: Document) -> DocumentDetail:
        """Build the API detail: current content and staleness vs the file."""
        content = document.content
        stale = False
        if document.file_path is not None and self._vault is not None:
            disk_mtime = self._vault.mtime(document.file_path)
            if disk_mtime is not None:
                stale = _is_stale(disk_mtime, document.file_mtime, document.updated_at)
                if document.mime_type != PDF_MIME_TYPE:
                    content = self._vault.read_text(document.file_path)
        return DocumentDetail(
            id=document.id,
            title=document.title,
            mime_type=document.mime_type,
            source_type=document.source_type,
            created_at=document.created_at,
            updated_at=document.updated_at,
            chunk_count=len(document.chunks),
            content=content,
            file_path=document.file_path,
            stale=stale,
        )

    async def detail(self, document_id: str) -> DocumentDetail | None:
        """Return a document's API detail, or None when it is missing."""
        document = await self._documents.get(document_id)
        if document is None:
            return None
        return self._resolve_detail(document)

    async def resync(self, document_id: str) -> DocumentDetail | None:
        """Re-read a document's vault file and re-embed it; None when missing.

        Raises ``ResyncError`` when the document has no vault file or the file
        is gone from the vault, so callers surface a clear 4xx.
        """
        document = await self._documents.get(document_id)
        if document is None:
            return None
        if document.file_path is None:
            raise ResyncError("document has no vault file to resync from")
        if self._vault is None or not self._vault.exists(document.file_path):
            raise ResyncError(f"vault file is missing: {document.file_path}")

        file_mtime = self._vault.mtime(document.file_path)
        if document.mime_type == PDF_MIME_TYPE:
            raw = self._vault.read_bytes(document.file_path)
            content = await asyncio.to_thread(_extract_pdf_text, raw)
            if not content:
                self._logger.warning(
                    "pdf text extraction returned no text",
                    extra={"file_path": document.file_path},
                )
        else:
            content = self._vault.read_text(document.file_path)

        settings = get_settings()
        chunks = [
            Chunk(chunk_index=index, content=part)
            for index, part in enumerate(
                chunk_text(
                    content, size=settings.chunk_size, overlap=settings.chunk_overlap
                )
            )
        ]
        updated = await self._documents.replace_file_content(
            document_id, content=content, file_mtime=file_mtime, chunks=chunks
        )
        if updated is None:
            return None
        await self._vector_store.delete_by_document(document_id)
        refreshed = await self._store_vectors(updated)
        return self._resolve_detail(refreshed)

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document's vector points and rows. False when missing.

        Used by vault sync and any caller that must cascade a delete through
        both stores.
        """
        document = await self._documents.get(document_id)
        if document is None:
            return False
        await self._vector_store.delete_by_document(document_id)
        await self._documents.delete(document_id)
        return True