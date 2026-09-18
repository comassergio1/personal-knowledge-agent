"""API integration tests for memories (status flips, filters, 404/409, delete).

Candidates are seeded through the app-scoped ``MemoryRepository`` because no
route creates candidates yet (the extract route lands in unit 2). The app
lifespan runs inside each async test so seeding and requests share one event
loop and the shared in-memory SQLite connection.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.main import create_app


def _test_settings(tmp_path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        vault_path=tmp_path / "vault",
        ollama_base_url="http://127.0.0.1:59999",
    )


def create_test_app(tmp_path):
    """Build the offline app (fakes for LLM/embeddings/vector store)."""
    return create_app(settings=_test_settings(tmp_path), testing=True)


def _candidates():
    return [
        {"type": "semantic", "content": "Prefers concise answers", "confidence": 0.9},
        {"type": "episodic", "content": "Asked about Qdrant on Tuesday", "confidence": 0.6},
    ]


async def _seed(app, candidates=None):
    """Persist candidates through the app-scoped repository, return their ids."""
    rows = await app.state.memory_repository.create_candidates(
        candidates or _candidates()
    )
    return [row.id for row in rows]


async def test_list_empty_returns_no_items(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/memories")
            assert response.status_code == 200
            assert response.json() == {"items": [], "total": 0}


async def test_list_returns_candidates_newest_first(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        await _seed(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/memories")
            assert response.status_code == 200
            payload = response.json()
            assert payload["total"] == 2
            items = payload["items"]
            assert {item["memory_type"] for item in items} == {"semantic", "episodic"}
            assert all(item["status"] == "candidate" for item in items)
            timestamps = [item["created_at"] for item in items]
            assert timestamps == sorted(timestamps, reverse=True)


async def test_list_filters_by_type_and_status(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        ids = await _seed(app)
        await app.state.memory_repository.set_status(ids[0], "approved")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            semantic = await client.get("/api/v1/memories", params={"type": "semantic"})
            assert semantic.status_code == 200
            assert [i["content"] for i in semantic.json()["items"]] == [
                "Prefers concise answers"
            ]

            approved = await client.get("/api/v1/memories", params={"status": "approved"})
            assert approved.status_code == 200
            assert approved.json()["total"] == 1
            assert approved.json()["items"][0]["id"] == ids[0]

            combined = await client.get(
                "/api/v1/memories", params={"type": "episodic", "status": "approved"}
            )
            assert combined.json()["total"] == 0


async def test_list_rejects_invalid_type_and_status(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/api/v1/memories", params={"type": "bogus"})).status_code == 422
            assert (await client.get("/api/v1/memories", params={"status": "deleted"})).status_code == 422


async def test_get_returns_one_memory(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        ids = await _seed(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/memories/{ids[0]}")
            assert response.status_code == 200
            item = response.json()
            assert item["id"] == ids[0]
            assert item["memory_type"] == "semantic"
            assert item["content"] == "Prefers concise answers"
            assert item["confidence"] == 0.9
            assert item["source"] is None
            assert item["created_at"]
            assert item["updated_at"]


async def test_get_missing_is_404(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/memories/does-not-exist")
            assert response.status_code == 404


async def test_approve_flips_status(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        ids = await _seed(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/v1/memories/{ids[0]}/approve")
            assert response.status_code == 200
            item = response.json()
            assert item["id"] == ids[0]
            assert item["status"] == "approved"
            assert item["memory_type"] == "semantic"
            assert item["content"] == "Prefers concise answers"

            listed = await client.get("/api/v1/memories", params={"status": "approved"})
            assert listed.json()["total"] == 1


async def test_approve_non_candidate_and_missing(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        ids = await _seed(app)
        await app.state.memory_repository.set_status(ids[0], "approved")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            again = await client.post(f"/api/v1/memories/{ids[0]}/approve")
            assert again.status_code == 409

            missing = await client.post("/api/v1/memories/does-not-exist/approve")
            assert missing.status_code == 404


async def test_reject_flips_status_and_rejects_when_not_candidate(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        ids = await _seed(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            rejected = await client.post(f"/api/v1/memories/{ids[0]}/reject")
            assert rejected.status_code == 200
            assert rejected.json()["status"] == "rejected"

            again = await client.post(f"/api/v1/memories/{ids[0]}/reject")
            assert again.status_code == 409

            missing = await client.post("/api/v1/memories/does-not-exist/reject")
            assert missing.status_code == 404


async def test_approved_memory_cannot_be_rejected(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        ids = await _seed(app)
        await app.state.memory_repository.set_status(ids[1], "approved")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/v1/memories/{ids[1]}/reject")
            assert response.status_code == 409


async def test_delete_removes_row(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        ids = await _seed(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            deleted = await client.delete(f"/api/v1/memories/{ids[0]}")
            assert deleted.status_code == 204

            gone = await client.get(f"/api/v1/memories/{ids[0]}")
            assert gone.status_code == 404

            listing = await client.get("/api/v1/memories")
            assert listing.json()["total"] == 1


async def test_delete_missing_is_404(tmp_path) -> None:
    app = create_test_app(tmp_path)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/v1/memories/does-not-exist")
            assert response.status_code == 404