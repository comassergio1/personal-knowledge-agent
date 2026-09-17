"""Unit tests for the Qdrant vector store (fake client, no network).

A fake ``AsyncQdrantClient`` is injected through the store's ``client``
parameter; the default-client construction path is covered by monkeypatching
the module's ``AsyncQdrantClient``.
"""

from __future__ import annotations

from types import SimpleNamespace

from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.vector import qdrant as qdrant_module
from app.vector.collections import DEFAULT_COLLECTION, DOCUMENT_ID_FIELD
from app.vector.qdrant import QdrantVectorStore, SearchHit, VectorPoint

_PAYLOAD = {
    "document_id": "doc-1",
    "chunk_id": "chunk-1",
    "chunk_index": 0,
    "title": "Note A",
    "content": "text A",
    "metadata": {"lang": "en"},
}


class FakeQdrantClient:
    """Records every call the store makes and returns canned responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.collections: set[str] = set()

    async def collection_exists(self, collection_name: str) -> bool:
        self.calls.append(("collection_exists", (collection_name,), {}))
        return collection_name in self.collections

    async def create_collection(self, **kwargs) -> None:
        self.calls.append(("create_collection", (), kwargs))
        self.collections.add(kwargs["collection_name"])

    async def create_payload_index(self, **kwargs) -> None:
        self.calls.append(("create_payload_index", (), kwargs))

    async def upsert(self, **kwargs) -> None:
        self.calls.append(("upsert", (), kwargs))

    async def query_points(self, **kwargs):
        self.calls.append(("query_points", (), kwargs))
        points = [SimpleNamespace(id="chunk-1", score=0.91, payload=dict(_PAYLOAD))]
        return SimpleNamespace(points=points)

    async def delete(self, **kwargs) -> None:
        self.calls.append(("delete", (), kwargs))

    async def close(self) -> None:
        self.calls.append(("close", (), {}))


def _call_names(fake: FakeQdrantClient) -> list[str]:
    return [name for name, _, _ in fake.calls]


async def test_ensure_collection_creates_with_cosine_and_index() -> None:
    fake = FakeQdrantClient()
    store = QdrantVectorStore(url="http://localhost:6333", client=fake)

    await store.ensure_collection(size=768)

    create = next(c for c in fake.calls if c[0] == "create_collection")
    assert create[2]["collection_name"] == DEFAULT_COLLECTION
    vectors = create[2]["vectors_config"]
    assert isinstance(vectors, VectorParams)
    assert vectors.size == 768
    assert vectors.distance == Distance.COSINE
    assert vectors.on_disk is True
    assert create[2]["on_disk_payload"] is True

    index = next(c for c in fake.calls if c[0] == "create_payload_index")
    assert index[2]["collection_name"] == DEFAULT_COLLECTION
    assert index[2]["field_name"] == DOCUMENT_ID_FIELD


async def test_ensure_collection_is_idempotent_when_exists() -> None:
    fake = FakeQdrantClient()
    fake.collections.add(DEFAULT_COLLECTION)
    store = QdrantVectorStore(url="http://localhost:6333", client=fake)

    await store.ensure_collection(size=768)

    assert not any(
        c[0] in ("create_collection", "create_payload_index") for c in fake.calls
    )


async def test_upsert_chunks_maps_to_point_structs() -> None:
    fake = FakeQdrantClient()
    store = QdrantVectorStore(url="http://localhost:6333", client=fake)

    await store.upsert_chunks(
        [VectorPoint(id="chunk-1", vector=[0.1, 0.2], payload=dict(_PAYLOAD))]
    )

    call = next(c for c in fake.calls if c[0] == "upsert")
    assert call[2]["collection_name"] == DEFAULT_COLLECTION
    assert call[2]["wait"] is True
    points = call[2]["points"]
    assert isinstance(points[0], PointStruct)
    assert points[0].id == "chunk-1"
    assert points[0].vector == [0.1, 0.2]
    assert points[0].payload == _PAYLOAD


async def test_search_maps_fields_and_score() -> None:
    fake = FakeQdrantClient()
    store = QdrantVectorStore(url="http://localhost:6333", client=fake)

    hits = await store.search([0.1, 0.2, 0.3], top_k=3)

    call = next(c for c in fake.calls if c[0] == "query_points")
    assert call[2]["collection_name"] == DEFAULT_COLLECTION
    assert call[2]["query"] == [0.1, 0.2, 0.3]
    assert call[2]["limit"] == 3
    assert call[2]["query_filter"] is None

    hit = hits[0]
    assert isinstance(hit, SearchHit)
    assert hit.chunk_id == "chunk-1"
    assert hit.document_id == "doc-1"
    assert hit.title == "Note A"
    assert hit.content == "text A"
    assert hit.score == 0.91
    assert hit.metadata == {"lang": "en"}


async def test_search_filters_by_document_id_and_threshold() -> None:
    fake = FakeQdrantClient()
    store = QdrantVectorStore(url="http://localhost:6333", client=fake)

    await store.search([0.1], document_id="doc-9", score_threshold=0.5)

    call = next(c for c in fake.calls if c[0] == "query_points")
    query_filter = call[2]["query_filter"]
    assert isinstance(query_filter, Filter)
    assert query_filter.must == [
        FieldCondition(key=DOCUMENT_ID_FIELD, match=MatchValue(value="doc-9"))
    ]
    assert call[2]["score_threshold"] == 0.5


async def test_delete_by_document_uses_payload_filter() -> None:
    fake = FakeQdrantClient()
    store = QdrantVectorStore(url="http://localhost:6333", client=fake)

    await store.delete_by_document("doc-9")

    call = next(c for c in fake.calls if c[0] == "delete")
    selector = call[2]["points_selector"]
    assert isinstance(selector, FilterSelector)
    assert selector.filter.must == [
        FieldCondition(key=DOCUMENT_ID_FIELD, match=MatchValue(value="doc-9"))
    ]


async def test_close_closes_the_client() -> None:
    fake = FakeQdrantClient()
    store = QdrantVectorStore(url="http://localhost:6333", client=fake)

    await store.close()

    assert "close" in _call_names(fake)


def test_default_client_is_constructed_from_url(monkeypatch) -> None:
    fake = FakeQdrantClient()

    def fake_ctor(url: str, **kwargs) -> FakeQdrantClient:
        fake.url_arg = url
        return fake

    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", fake_ctor)

    QdrantVectorStore(url="http://localhost:6333")

    assert fake.url_arg == "http://localhost:6333"