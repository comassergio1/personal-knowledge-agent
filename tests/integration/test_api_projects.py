"""API integration tests for projects (create/list/delete cascade, offline)."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models.document import Document
from app.main import create_app
from app.services.vault_service import VaultService


def test_create_project_returns_project_read(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/projects", json={"name": "Research"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"]
    assert payload["name"] == "Research"
    assert payload["description"] is None
    assert payload["created_at"]
    assert payload["updated_at"]


def test_create_project_with_description(test_app: TestClient) -> None:
    response = test_app.post(
        "/api/v1/projects", json={"name": "Notes", "description": "Daily notes"}
    )

    assert response.status_code == 201
    assert response.json()["description"] == "Daily notes"


def test_create_duplicate_project_is_409(test_app: TestClient) -> None:
    test_app.post("/api/v1/projects", json={"name": "Research"})

    response = test_app.post("/api/v1/projects", json={"name": "Research"})

    assert response.status_code == 409
    # The existing project is untouched.
    assert len(test_app.get("/api/v1/projects").json()) == 1


def test_list_projects_returns_all(test_app: TestClient) -> None:
    test_app.post("/api/v1/projects", json={"name": "Alpha"})
    test_app.post("/api/v1/projects", json={"name": "Beta", "description": "second"})

    response = test_app.get("/api/v1/projects")

    assert response.status_code == 200
    names = {project["name"] for project in response.json()}
    assert names == {"Alpha", "Beta"}


def test_delete_project_removes_rows_and_vector_points(test_app: TestClient) -> None:
    project_id = test_app.post("/api/v1/projects", json={"name": "Gone"}).json()["id"]
    doc_1 = test_app.post(
        "/api/v1/documents",
        files={"file": ("a.md", b"# A\n\n'alpha' content here.", "text/markdown")},
        data={"project_id": project_id},
    ).json()["id"]
    doc_2 = test_app.post(
        "/api/v1/documents",
        files={"file": ("b.md", b"# B\n\n'beta' content here.", "text/markdown")},
        data={"project_id": project_id},
    ).json()["id"]

    vector_store = test_app.app.state.vector_store
    response = test_app.delete(f"/api/v1/projects/{project_id}")

    assert response.status_code == 204
    assert set(vector_store.deleted_documents) == {doc_1, doc_2}
    assert test_app.get("/api/v1/documents").json()["total"] == 0
    assert test_app.get("/api/v1/projects").json() == []


def test_delete_missing_project_is_404(test_app: TestClient) -> None:
    response = test_app.delete("/api/v1/projects/does-not-exist")

    assert response.status_code == 404


async def test_delete_project_removes_vault_files(tmp_path) -> None:
    """Full cascade including vault files (file_path set, unit 2 simulation)."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        vault_path=tmp_path / "vault",
        ollama_base_url="http://127.0.0.1:59999",
    )
    app = create_app(settings=settings, testing=True)
    root = (tmp_path / "vault").resolve()

    # Run the lifespan in this loop so the app's session factory and the
    # test's sessions share one event loop (StaticPool single connection).
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            created = await client.post("/api/v1/projects", json={"name": "Cascade"})
            assert created.status_code == 201
            project_id = created.json()["id"]

            uploaded = await client.post(
                "/api/v1/documents",
                files={"file": ("note.md", b"# Note\n\nBody.", "text/markdown")},
                data={"project_id": project_id},
            )
            assert uploaded.status_code == 201
            document_id = uploaded.json()["id"]

            # Unit 2 writes vault files during ingestion; simulate the file
            # here so the route's vault-file branch is exercised.
            vault: VaultService = app.state.vault_service
            path = vault.markdown_path("Cascade", "note")
            vault.write_text(path, "# Note\n\nBody.")
            async with app.state.session_factory() as session:
                document = await session.get(Document, document_id)
                assert document is not None
                document.file_path = path.relative_to(root).as_posix()
                await session.commit()

            deleted = await client.delete(f"/api/v1/projects/{project_id}")

            assert deleted.status_code == 204
            assert not vault.exists(path)
            assert app.state.vector_store.deleted_documents == [document_id]
            listing = await client.get("/api/v1/documents")
            assert listing.json()["total"] == 0