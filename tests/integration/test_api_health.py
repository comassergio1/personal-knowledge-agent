"""API integration tests for the health endpoint (no daemons running)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_ok_with_unreachable_backends(test_app: TestClient) -> None:
    response = test_app.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # The testing fakes expose no live Qdrant client and this machine has no
    # Ollama daemon, so both reachability flags must read False — never 5xx.
    assert body["qdrant"] is False
    assert body["ollama"] is False