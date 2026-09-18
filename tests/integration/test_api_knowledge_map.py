"""API integration tests for the knowledge-map endpoint (offline fakes).

The map endpoint runs over the testing app: retrieval and approved-memory
search hit the in-memory stores and the fake LLM answers the map prompt with
the canned chat text, so no network is touched. The response echoes the topic
and carries the generated markdown.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_knowledge_map_returns_generated_markdown(test_app: TestClient) -> None:
    response = test_app.get("/api/v1/knowledge/map", params={"topic": "redes"})

    assert response.status_code == 200
    assert response.json() == {
        "topic": "redes",
        "map": "This is a fake grounded answer.",
    }


def test_knowledge_map_accepts_project_id(test_app: TestClient) -> None:
    project = test_app.post("/api/v1/projects", json={"name": "Redes"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    response = test_app.get(
        "/api/v1/knowledge/map", params={"topic": "vlan", "project_id": project_id}
    )

    assert response.status_code == 200
    assert response.json()["topic"] == "vlan"


def test_knowledge_map_empty_topic_is_422(test_app: TestClient) -> None:
    response = test_app.get("/api/v1/knowledge/map", params={"topic": ""})

    assert response.status_code == 422


def test_knowledge_map_missing_topic_is_422(test_app: TestClient) -> None:
    response = test_app.get("/api/v1/knowledge/map")

    assert response.status_code == 422