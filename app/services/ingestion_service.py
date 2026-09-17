"""Document ingestion: chunk, persist, embed, and upsert vectors (spec §14/§15).

The service orchestrates the slice's storage steps: deterministic chunking of
the raw content, one ``Document`` row with its ``Chunk`` rows, one embedding
call per chunk, and one vector point per chunk upserted into Qdrant.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.domain.models.document import Chunk, Document
from app.providers.embeddings.base import EmbeddingProvider, EmbeddingProviderError
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import chunk_text
from app.vector.collections import (
    CHUNK_ID_FIELD,
    CHUNK_INDEX_FIELD,
    CONTENT_FIELD,
    DOCUMENT_ID_FIELD,
    METADATA_FIELD,
    TITLE_FIELD,
)
from app.vector.qdrant import QdrantVectorStore, VectorPoint


class IngestionError(Exception):
    """Raised when a document cannot be embedded or stored in the vector store."""


class IngestionService:
    """Chunks, persists, embeds, and upserts one document at a time."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        vector_store: QdrantVectorStore,
        embeddings: EmbeddingProvider,
    ) -> None:
        self._documents = document_repository
        self._vector_store = vector_store
        self._embeddings = embeddings

    async def ingest(
        self,
        *,
        title: str,
        content: str,
        mime_type: str = "text/markdown",
        source_type: str = "text",
        source_uri: str | None = None,
        project_id: str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> Document:
        """Chunk, persist, embed, and upsert ``content``; return the document.

        Chunk sizing defaults to ``Settings.chunk_size``/``chunk_overlap``
        unless explicit values are given. ``chunk_index`` is mirrored inside
        the point's ``metadata`` payload so consumers of ``SearchHit.metadata``
        (``ChatService``) can build chunk-level source references.
        """
        if not content.strip():
            raise ValueError("content must not be empty")
        settings = get_settings()
        size = settings.chunk_size if chunk_size is None else chunk_size
        overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap

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
            chunks=chunks,
        )

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
                    METADATA_FIELD: {
                        **dict(chunk.metadata_ or {}),
                        CHUNK_INDEX_FIELD: chunk.chunk_index,
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

        for chunk in document.chunks:
            chunk.embedding_id = chunk.id

        persisted = await self._documents.get(document.id)
        return persisted if persisted is not None else document