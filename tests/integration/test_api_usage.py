"""API integration tests for the usage endpoint (TestClient + fakes, offline)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_usage_returns_recorded_chat_row_and_totals(test_app: TestClient) -> None:
    chat = test_app.post("/api/v1/chat", json={"message": "hello"})
    assert chat.status_code == 200

    response = test_app.get("/api/v1/usage")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["recent"]) == 1
    row = payload["recent"][0]
    assert len(row["id"]) == 36
    assert len(row["request_id"]) == 32
    assert row["provider"] == "fake-llm"
    assert row["model"] == "fake"
    assert row["prompt_tokens"] == 0
    assert row["completion_tokens"] == 0
    assert row["estimated_cost_usd"] == 0.0
    assert isinstance(row["latency_ms"], int)
    assert row["created_at"]

    assert payload["totals"] == {
        "total_requests": 1,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_cost_usd": 0.0,
    }
    assert payload["per_provider"] == [
        {
            "provider": "fake-llm",
            "requests": 1,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
        }
    ]


def test_usage_empty_app_returns_zeros(test_app: TestClient) -> None:
    response = test_app.get("/api/v1/usage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recent"] == []
    assert payload["totals"] == {
        "total_requests": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_cost_usd": 0.0,
    }
    assert payload["per_provider"] == []


def test_usage_limit_out_of_range_is_422(test_app: TestClient) -> None:
    assert test_app.get("/api/v1/usage?limit=0").status_code == 422
    assert test_app.get("/api/v1/usage?limit=101").status_code == 422