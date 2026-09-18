"""Regression: DB writes after ingestion must not hit \"database is locked\".

Uses a real file-backed SQLite database (multi-connection pool) instead of the
in-memory single-connection StaticPool, so cross-connection write-lock bugs are
visible. The chat usage insert writes through a second connection after the
ingest; a previous implementation left an uncommitted write transaction on the
app-scoped ingestion session, holding the write lock (observed live, Phase 2).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _file_app(tmp_path) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'regression.db'}",
        vault_path=tmp_path / "vault",
        ollama_base_url="http://127.0.0.1:59999",
    )
    app = create_app(settings=settings, testing=True)
    return TestClient(app)


def test_ingest_then_chat_writes_usage_without_db_lock(tmp_path) -> None:
    with _file_app(tmp_path) as client:
        response = client.post(
            "/api/v1/documents",
            files={
                "file": (
                    "regression.md",
                    b"# Regresion\n\nContenido de prueba para el lock.",
                    "text/markdown",
                )
            },
            data={"title": "regression"},
        )
        assert response.status_code == 201, response.text

        documents = client.get("/api/v1/documents").json()["items"]
        assert documents, "document must be listed"

        chat = client.post(
            "/api/v1/chat",
            json={"message": "lock", "document_id": documents[0]["id"]},
        )
        assert chat.status_code == 200, chat.text
        assert chat.json()["answer"]

        usage = client.get("/api/v1/usage").json()
        assert usage["totals"]["total_requests"] >= 1
        assert usage["recent"], "chat usage must be recorded"
        assert usage["recent"][0]["provider"] == "fake-llm"


def test_sequential_chats_all_record_usage(tmp_path) -> None:
    with _file_app(tmp_path) as client:
        response = client.post(
            "/api/v1/documents",
            files={
                "file": (
                    "seq.md",
                    b"# Secuencia\n\nOtra prueba del lock.",
                    "text/markdown",
                )
            },
            data={"title": "seq"},
        )
        assert response.status_code == 201, response.text
        document_id = response.json()["id"]

        for _ in range(3):
            chat = client.post(
                "/api/v1/chat",
                json={"message": "hola", "document_id": document_id},
            )
            assert chat.status_code == 200, chat.text

        usage = client.get("/api/v1/usage?limit=10").json()
        assert usage["totals"]["total_requests"] == 3