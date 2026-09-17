"""Qdrant vector store wrapper: bootstrap, upsert, search, and delete (spec §9).

The store owns the mapping between our own dataclasses (``VectorPoint``,
``SearchHit``) and qdrant's wire types, so services never import qdrant models.
A client can be injected for tests; by default one is built from the URL.
"""

from __future__ import annotations

from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.vector.collections import (
    CHUNK_ID_FIELD,
    CONTENT_FIELD,
    DEFAULT_COLLECTION,
    DOCUMENT_ID_FIELD,
    METADATA_FIELD,
    PROJECT_ID_FIELD,
    TITLE_FIELD,
)


@dataclass
class VectorPoint:
    """A single vector point to upsert, in the store's own types."""

    id: str
    vector: list[float]
    payload: dict


@dataclass
class SearchHit:
    """A search result carrying the payload fields services need."""

    chunk_id: str
    document_id: str
    title: str
    content: str
    score: float
    metadata: dict


class QdrantVectorStore:
    """Thin async wrapper over ``AsyncQdrantClient`` for the default collection."""

    def __init__(self, url: str, *, client: AsyncQdrantClient | None = None) -> None:
        self._url = url
        self._client = client if client is not None else AsyncQdrantClient(url=url)

    async def ensure_collection(self, size: int) -> None:
        """Create the collection if missing, with keyword indexes on common filter fields."""
        if await self._client.collection_exists(DEFAULT_COLLECTION):
            return
        # on_disk=True suits a home server: vectors live on disk, not RAM.
        await self._client.create_collection(
            collection_name=DEFAULT_COLLECTION,
            vectors_config=VectorParams(size=size, distance=Distance.COSINE, on_disk=True),
            on_disk_payload=True,
        )
        await self._client.create_payload_index(
            collection_name=DEFAULT_COLLECTION,
            field_name=DOCUMENT_ID_FIELD,
            field_schema=PayloadSchemaType.KEYWORD,
        )
        await self._client.create_payload_index(
            collection_name=DEFAULT_COLLECTION,
            field_name=PROJECT_ID_FIELD,
            field_schema=PayloadSchemaType.KEYWORD,
        )

    async def upsert_chunks(self, points: list[VectorPoint]) -> None:
        """Map our ``VectorPoint`` list to qdrant ``PointStruct`` and upsert."""
        await self._client.upsert(
            collection_name=DEFAULT_COLLECTION,
            points=[
                PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points
            ],
            wait=True,
        )

    async def search(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        document_id: str | None = None,
        project_id: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        """Return the top-k nearest chunks, scoped by document and/or project."""
        conditions: list[FieldCondition] = []
        if document_id is not None:
            conditions.append(
                FieldCondition(key=DOCUMENT_ID_FIELD, match=MatchValue(value=document_id))
            )
        if project_id is not None:
            conditions.append(
                FieldCondition(key=PROJECT_ID_FIELD, match=MatchValue(value=project_id))
            )
        query_filter = Filter(must=conditions) if conditions else None
        response = await self._client.query_points(
            collection_name=DEFAULT_COLLECTION,
            query=embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
            score_threshold=score_threshold,
        )
        hits: list[SearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                SearchHit(
                    chunk_id=payload.get(CHUNK_ID_FIELD, str(point.id)),
                    document_id=payload.get(DOCUMENT_ID_FIELD, ""),
                    title=payload.get(TITLE_FIELD, ""),
                    content=payload.get(CONTENT_FIELD, ""),
                    score=point.score,
                    metadata=payload.get(METADATA_FIELD, {}) or {},
                )
            )
        return hits

    async def delete_by_document(self, document_id: str) -> None:
        """Delete every point whose payload ``document_id`` matches."""
        await self._client.delete(
            collection_name=DEFAULT_COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(key=DOCUMENT_ID_FIELD, match=MatchValue(value=document_id))
                    ]
                )
            ),
            wait=True,
        )

    async def close(self) -> None:
        """Close the underlying qdrant client."""
        await self._client.close()