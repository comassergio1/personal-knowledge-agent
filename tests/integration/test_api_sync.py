"""API integration tests for the manual vault sync route (TestClient, offline)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient


def _bump_mtime(path: Path) -> None:
    """Force a strictly newer mtime than any prior write (same-second safe)."""
    now = time.time()
    os.utime(path, (now + 5.0, now + 5.0))


def test_vault_sync_creates_and_updates_counts(test_app: TestClient, tmp_path) -> None:
    uploaded = test_app.post(
        "/api/v1/documents",
        files={"file": ("tracked.md", b"Original tracked content.", "text/markdown")},
    ).json()

    tracked = tmp_path / "vault" / "inbox" / "tracked.md"
    tracked.write_text("Edited tracked content.")
    _bump_mtime(tracked)
    (tmp_path / "vault" / "brand-new.md").write_text("Brand new note.")

    response = test_app.post("/api/v1/vault/sync")

    assert response.status_code == 200
    assert response.json() == {"created": 1, "updated": 1, "deleted": 0}

    docs = test_app.get("/api/v1/documents").json()
    assert docs["total"] == 2
    assert {item["title"] for item in docs["items"]} == {"tracked", "brand-new"}

    detail = test_app.get(f"/api/v1/documents/{uploaded['id']}").json()
    assert detail["content"] == "Edited tracked content."
    assert detail["stale"] is False


def test_vault_sync_project_creation(test_app: TestClient, tmp_path) -> None:
    (tmp_path / "vault" / "research").mkdir(parents=True)
    (tmp_path / "vault" / "research" / "idea.md").write_text("Idea content.")

    response = test_app.post("/api/v1/vault/sync")

    assert response.json() == {"created": 1, "updated": 0, "deleted": 0}
    projects = test_app.get("/api/v1/projects").json()
    assert [project["name"] for project in projects] == ["research"]

    scoped = test_app.get(
        f"/api/v1/documents?project_id={projects[0]['id']}"
    ).json()
    assert scoped["total"] == 1
    assert scoped["items"][0]["title"] == "idea"

    detail = test_app.get(f"/api/v1/documents/{scoped['items'][0]['id']}").json()
    assert detail["file_path"] == "research/idea.md"
    assert detail["stale"] is False


def test_vault_sync_deletes_documents_for_removed_files(
    test_app: TestClient, tmp_path
) -> None:
    created = test_app.post(
        "/api/v1/documents",
        files={"file": ("gone.md", b"Bye.", "text/markdown")},
    ).json()
    (tmp_path / "vault" / "inbox" / "gone.md").unlink()

    response = test_app.post("/api/v1/vault/sync")

    assert response.json() == {"created": 0, "updated": 0, "deleted": 1}
    assert test_app.get("/api/v1/documents").json()["total"] == 0
    assert created["id"] in test_app.app.state.vector_store.deleted_documents
    # a second sync is a no-op
    assert test_app.post("/api/v1/vault/sync").json() == {
        "created": 0,
        "updated": 0,
        "deleted": 0,
    }


def test_vault_sync_empty_vault_is_noop(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/vault/sync")

    assert response.status_code == 200
    assert response.json() == {"created": 0, "updated": 0, "deleted": 0}