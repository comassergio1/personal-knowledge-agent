"""Unit tests for RetrievalService (fake providers/stores, no network)."""

from __future__ import annotations

from app.services.retrieval_service import RetrievalService
from app.vector.qdrant import SearchHit


class FakeEmbeddingProvider:
    """Returns a fixed vector and records every embedded query."""

    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return [1.0, 2.0, 3.0]


class FakeVectorStore:
    """Records search calls and returns canned hits."""

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits = hits if hits is not None else []
        self.calls: list[dict] = []

    async def search(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        document_id: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        self.calls.append(
            {
                "embedding": embedding,
                "top_k": top_k,
                "document_id": document_id,
                "score_threshold": score_threshold,
            }
        )
        return self.hits


def _hit(chunk_id: str = "chunk-1") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id="doc-1",
        title="Note A",
        content="Some chunk content.",
        score=0.81,
        metadata={},
    )


async def test_retrieve_embeds_query_and_passes_options_through() -> None:
    embedding = FakeEmbeddingProvider()
    store = FakeVectorStore(hits=[_hit()])
    service = RetrievalService(store, embedding)  # type: ignore[arg-type]

    hits = await service.retrieve(
        "when was it written?", top_k=3, document_id="doc-9", score_threshold=0.5
    )

    assert embedding.embedded == ["when was it written?"]
    assert store.calls == [
        {
            "embedding": [1.0, 2.0, 3.0],
            "top_k": 3,
            "document_id": "doc-9",
            "score_threshold": 0.5,
        }
    ]
    assert hits == store.hits


async def test_retrieve_uses_defaults_when_options_omitted() -> None:
    embedding = FakeEmbeddingProvider()
    store = FakeVectorStore()
    service = RetrievalService(store, embedding)  # type: ignore[arg-type]

    await service.retrieve("hello")

    assert store.calls[0]["top_k"] == 5
    assert store.calls[0]["document_id"] is None
    assert store.calls[0]["score_threshold"] is None


async def test_retrieve_returns_the_embedding_query_per_hit() -> None:
    embedding = FakeEmbeddingProvider()
    hits_in = [_hit("a"), _hit("b")]
    store = FakeVectorStore(hits=hits_in)
    service = RetrievalService(store, embedding)  # type: ignore[arg-type]

    hits_out = await service.retrieve("query")

    assert hits_out == hits_in
    assert embedding.embedded == ["query"]