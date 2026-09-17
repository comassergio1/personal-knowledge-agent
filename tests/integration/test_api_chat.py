"""API integration tests for chat (TestClient + fakes, fully offline)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_chat_answers_with_sources_from_seeded_document(test_app: TestClient) -> None:
    uploaded = test_app.post(
        "/api/v1/documents",
        files={
            "file": (
                "facts.md",
                b"Anchovies are tiny fish with a sharp, salty taste; many pizzas use anchovies.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201

    response = test_app.post(
        "/api/v1/chat", json={"message": "What can you tell me about anchovies?"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "This is a fake grounded answer."
    assert len(payload["sources"]) == 1
    source = payload["sources"][0]
    assert source["document_id"] == uploaded.json()["id"]
    assert source["title"] == "facts"
    assert source["chunk_index"] == 0
    assert source["score"] == 0.9
    assert "anchovies" in source["excerpt"]


def test_chat_empty_message_is_422(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/chat", json={"message": ""})

    assert response.status_code == 422