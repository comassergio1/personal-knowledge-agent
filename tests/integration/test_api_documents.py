"""API integration tests for documents (TestClient + fakes, fully offline)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _bump_mtime(path: Path) -> None:
    """Force a strictly newer mtime than any prior write (same-second safe)."""
    now = time.time()
    os.utime(path, (now + 5.0, now + 5.0))


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


def test_upload_markdown_writes_file_into_vault_and_detail_not_stale(
    test_app: TestClient, tmp_path
) -> None:
    response = test_app.post(
        "/api/v1/documents",
        files={"file": ("note.md", b"# Note\n\nContent.", "text/markdown")},
    )
    assert response.status_code == 201

    detail = test_app.get(f"/api/v1/documents/{response.json()['id']}").json()
    assert detail["file_path"] == "inbox/note.md"
    assert detail["stale"] is False
    assert detail["content"] == "# Note\n\nContent."

    vault_file = tmp_path / "vault" / "inbox" / "note.md"
    assert vault_file.exists()
    assert vault_file.read_text(encoding="utf-8") == "# Note\n\nContent."


def test_edit_file_on_disk_then_resync_reflects_in_chat(
    test_app: TestClient, tmp_path
) -> None:
    created = test_app.post(
        "/api/v1/documents",
        files={"file": ("facts.md", b"Original fact: the sky is blue.", "text/markdown")},
    ).json()
    document_id = created["id"]
    assert test_app.get(f"/api/v1/documents/{document_id}").json()["stale"] is False

    path = tmp_path / "vault" / "inbox" / "facts.md"
    path.write_text("Updated fact: pears are green.")
    _bump_mtime(path)

    detail = test_app.get(f"/api/v1/documents/{document_id}").json()
    assert detail["stale"] is True
    assert detail["content"] == "Updated fact: pears are green."

    resynced = test_app.post(f"/api/v1/documents/{document_id}/resync").json()
    assert resynced["stale"] is False
    assert resynced["content"] == "Updated fact: pears are green."

    chat = test_app.post("/api/v1/chat", json={"message": "What about pears?"}).json()
    assert any("pears are green" in source["excerpt"] for source in chat["sources"])


def test_resync_missing_document_is_404(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/documents/missing/resync")

    assert response.status_code == 404


def test_resync_missing_vault_file_is_409(test_app: TestClient, tmp_path) -> None:
    created = test_app.post(
        "/api/v1/documents",
        files={"file": ("note.md", b"To be orphaned.", "text/markdown")},
    ).json()
    (tmp_path / "vault" / "inbox" / "note.md").unlink()

    response = test_app.post(f"/api/v1/documents/{created['id']}/resync")

    assert response.status_code == 409


def test_get_detail_missing_document_is_404(test_app: TestClient) -> None:
    response = test_app.get("/api/v1/documents/missing")

    assert response.status_code == 404


def test_upload_pdf_stores_file_and_detail_has_extracted_text(
    test_app: TestClient, tmp_path
) -> None:
    pdf_bytes = (FIXTURES / "sample.pdf").read_bytes()
    response = test_app.post(
        "/api/v1/documents",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Paper"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Paper"
    assert payload["mime_type"] == "application/pdf"
    assert payload["chunk_count"] == 1

    detail = test_app.get(f"/api/v1/documents/{payload['id']}").json()
    assert detail["content"] == "Hello PKA"
    assert detail["stale"] is False

    vault_file = tmp_path / "vault" / "inbox" / "paper.pdf"
    assert vault_file.exists()
    assert vault_file.read_bytes() == pdf_bytes


# -- append (PATCH /documents/{id}/append) ------------------------------------


def test_append_writes_file_reindexes_and_detail_has_section(
    test_app: TestClient, tmp_path
) -> None:
    created = test_app.post(
        "/api/v1/documents",
        files={"file": ("note.md", b"# Note\n\nBase content.", "text/markdown")},
    ).json()
    document_id = created["id"]
    vector_store = test_app.app.state.vector_store

    response = test_app.patch(
        f"/api/v1/documents/{document_id}/append",
        json={"text": "Appended fact.", "section": "Facts"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stale"] is False
    assert payload["content"] == "# Note\n\nBase content.\n## Facts\n\nAppended fact.\n"

    detail = test_app.get(f"/api/v1/documents/{document_id}").json()
    assert "Appended fact." in detail["content"]

    vault_file = tmp_path / "vault" / "inbox" / "note.md"
    assert "## Facts" in vault_file.read_text(encoding="utf-8")
    assert vector_store.deleted_documents == [document_id]

    chat = test_app.post(
        "/api/v1/chat", json={"message": "What appended fact?"}
    ).json()
    assert any("Appended fact." in source["excerpt"] for source in chat["sources"])


def test_append_missing_document_is_404(test_app: TestClient) -> None:
    response = test_app.patch(
        "/api/v1/documents/missing/append", json={"text": "more"}
    )

    assert response.status_code == 404


def test_append_pdf_document_is_409(test_app: TestClient) -> None:
    pdf_bytes = (FIXTURES / "sample.pdf").read_bytes()
    created = test_app.post(
        "/api/v1/documents",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Paper"},
    ).json()

    response = test_app.patch(
        f"/api/v1/documents/{created['id']}/append", json={"text": "more"}
    )

    assert response.status_code == 409
    assert "text/markdown" in response.json()["detail"]


def test_append_empty_text_is_422(test_app: TestClient) -> None:
    created = test_app.post(
        "/api/v1/documents",
        files={"file": ("note.md", b"# Note\n\nContent.", "text/markdown")},
    ).json()

    response = test_app.patch(
        f"/api/v1/documents/{created['id']}/append", json={"text": ""}
    )

    assert response.status_code == 422