"""API integration tests for documents (TestClient + fakes, fully offline)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_upload_markdown_returns_document_read(test_app: TestClient) -> None:
    response = test_app.post(
        "/api/v1/documents",
        files={
            "file": (
                "note.md",
                b"# Note title\n\nSome markdown content here.",
                "text/markdown",
            )
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"]
    assert payload["title"] == "note"
    assert payload["mime_type"] == "text/markdown"
    assert payload["source_type"] == "file"
    assert payload["chunk_count"] == 1
    assert payload["created_at"]
    assert payload["updated_at"]


def test_upload_provided_title_and_txt_mime(test_app: TestClient) -> None:
    response = test_app.post(
        "/api/v1/documents",
        files={"file": ("note.txt", b"Plain text note.", "text/plain")},
        data={"title": "My Note", "project_id": "proj-1"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "My Note"
    assert payload["mime_type"] == "text/plain"


def test_list_includes_uploaded_document(test_app: TestClient) -> None:
    created = test_app.post(
        "/api/v1/documents",
        files={"file": ("note.md", b"# Title\n\nContent.", "text/markdown")},
    ).json()

    response = test_app.get("/api/v1/documents")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]
    assert body["items"][0]["title"] == "note"


def test_list_filters_by_project(test_app: TestClient) -> None:
    first = test_app.post(
        "/api/v1/documents",
        files={"file": ("a.md", b"# A\n\nContent A.", "text/markdown")},
        data={"project_id": "proj-1"},
    ).json()
    test_app.post(
        "/api/v1/documents",
        files={"file": ("b.md", b"# B\n\nContent B.", "text/markdown")},
        data={"project_id": "proj-2"},
    )

    assert test_app.get("/api/v1/documents").json()["total"] == 2

    filtered = test_app.get("/api/v1/documents?project_id=proj-1").json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == first["id"]

    empty = test_app.get("/api/v1/documents?project_id=missing").json()
    assert empty["total"] == 0


def test_delete_removes_rows_and_vector_points(test_app: TestClient) -> None:
    document_id = test_app.post(
        "/api/v1/documents",
        files={"file": ("note.md", b"To be removed.", "text/markdown")},
    ).json()["id"]
    vector_store = test_app.app.state.vector_store

    response = test_app.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 204
    assert vector_store.deleted_documents == [document_id]
    assert test_app.get("/api/v1/documents").json()["total"] == 0


def test_delete_missing_document_is_404(test_app: TestClient) -> None:
    response = test_app.delete("/api/v1/documents/does-not-exist")

    assert response.status_code == 404