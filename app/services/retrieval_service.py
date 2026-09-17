"""Query-time retrieval: embed the query and search the vector store (spec §16).

No LLM is involved; the service is a thin orchestration of the embedding
provider and the vector store so API routes never touch either directly.
"""

from __future__ import annotations

from app.providers.embeddings.base import EmbeddingProvider
from app.vector.qdrant import QdrantVectorStore, SearchHit


class RetrievalService:
    """Embeds a query and returns the top-k most similar chunks."""

    def __init__(
        self, vector_store: QdrantVectorStore, embeddings: EmbeddingProvider
    ) -> None:
        self._vector_store = vector_store
        self._embeddings = embeddings

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_id: str | None = None,
        project_id: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        """Return the nearest chunks for ``query``, optionally scoped."""
        embedding = await self._embeddings.embed(query)
        return await self._vector_store.search(
            embedding,
            top_k=top_k,
            document_id=document_id,
            project_id=project_id,
            score_threshold=score_threshold,
        )