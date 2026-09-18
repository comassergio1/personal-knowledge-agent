"""API integration tests for tutorial generation (TestClient + fakes, offline)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.providers.llm.base import LLMProviderError
from app.services.tutorial_service import TutorialService


class _BoomLLM:
    """Fake LLM that fails like a real provider outage."""

    name = "boom-llm"

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> None:
        raise LLMProviderError("ollama exploded")


def test_generate_tutorial_returns_persisted_document(test_app: TestClient) -> None:
    uploaded = test_app.post(
        "/api/v1/documents",
        files={
            "file": (
                "facts.md",
                b"Anchovies are tiny fish with a sharp, salty taste.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201

    response = test_app.post(
        "/api/v1/tutorials/generate",
        json={"objective": "Write a tutorial about anchovies"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content"] == "This is a fake grounded answer."
    assert payload["document_id"]
    # No project -> the tutorial lands in the inbox folder.
    assert payload["file_path"] == "inbox/write-a-tutorial-about-anchovies.md"
    # The canned fake answer skips the §20 headers; the post-check surfaces it.
    assert payload["warnings"] == ["# Objetivo", "# Fuentes"]
    assert len(payload["sources"]) == 1
    source = payload["sources"][0]
    assert source["title"] == "facts"
    assert source["score"] == 0.9

    # The persisted tutorial is immediately readable as a document.
    detail = test_app.get(f"/api/v1/documents/{payload['document_id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == "This is a fake grounded answer."
    assert detail.json()["file_path"] == payload["file_path"]
    assert detail.json()["stale"] is False


def test_generate_tutorial_into_project_folder(test_app: TestClient) -> None:
    project = test_app.post(
        "/api/v1/projects",
        json={"name": "Home Lab", "description": "network notes"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    response = test_app.post(
        "/api/v1/tutorials/generate",
        json={
            "objective": "Configura una VLAN de invitados",
            "project_id": project_id,
            "title": "Guest VLAN Guide",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["file_path"] == "home-lab/guest-vlan-guide.md"
    assert payload["title"] == "Guest VLAN Guide"


def test_generate_empty_objective_is_422(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/tutorials/generate", json={"objective": ""})

    assert response.status_code == 422


def test_generate_provider_error_is_502(test_app: TestClient) -> None:
    app = test_app.app
    app.state.tutorial_service = TutorialService(  # type: ignore[arg-type]
        _BoomLLM(),
        retrieval=app.state.retrieval_service,
        memory=None,
        vault=app.state.vault_service,
        ingestion=app.state.ingestion_service,
        settings=app.state.settings,
    )

    response = test_app.post(
        "/api/v1/tutorials/generate", json={"objective": "anything"}
    )

    assert response.status_code == 502
    assert "ollama exploded" in response.json()["detail"]


def test_generate_tutorial_respects_requested_mode(test_app: TestClient) -> None:
    """Phase 7: the requested depth is passed to the service and echoed back."""
    response = test_app.post(
        "/api/v1/tutorials/generate",
        json={"objective": "Redes VLANs", "mode": "deep_learn"},
    )

    assert response.status_code == 201
    assert response.json()["mode"] == "deep_learn"