"""API integration tests for evaluation endpoints (TestClient + fakes, offline).

The datasets under ``tests/evals/`` are plain request bodies: they load
directly into ``POST /api/v1/evals/run``. The testing app's fake LLM answers
judge prompts with a frozen rubric (challenged premise true) and chat prompts
with a canned answer, so verdicts pass without any local stack.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

_EVALS_DIR = Path(__file__).resolve().parents[2] / "tests" / "evals"


def _load(name: str) -> dict:
    return json.loads((_EVALS_DIR / name).read_text(encoding="utf-8"))


def test_run_mikrotik_dataset_returns_metrics_and_verdicts(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/evals/run", json=_load("mikrotik.json"))

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"] == {"total": 3, "passes": 3, "fails": 0, "errors": 0}
    assert payload["judge"] == "llm"
    assert len(payload["cases"]) == 3
    for case in payload["cases"]:
        assert case["verdict"] == "pass"
        assert case["answer"] == "This is a fake grounded answer."
        assert case["sources"] == []
        metrics = case["metrics"]
        assert metrics["correctness"] == 0.9
        assert metrics["groundedness"] == 0.8
        assert metrics["source_quality"] == 0.0  # no sources retrieved offline
        assert metrics["challenged_premise"] is True


def test_run_adversarial_dataset_surfaces_the_flag(test_app: TestClient) -> None:
    response = test_app.post(
        "/api/v1/evals/run", json=_load("mikrotik-adversarial.json")
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"] == {"total": 1, "passes": 1, "fails": 0, "errors": 0}
    case = payload["cases"][0]
    assert case["case_name"] == "iot-premise"
    assert case["adversarial"] is True
    assert case["metrics"]["challenged_premise"] is True
    assert case["verdict"] == "pass"


def test_run_history_reflects_persisted_runs(test_app: TestClient) -> None:
    assert test_app.post("/api/v1/evals/run", json=_load("mikrotik.json")).status_code == 201

    response = test_app.get("/api/v1/evals/runs")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 3
    assert {item["case_name"] for item in items} == {
        "wan-port",
        "vlan-assignments",
        "openwrt-ap-setup",
    }
    for item in items:
        assert item["verdict"] == "pass"
        assert item["metrics"]["correctness"] == 0.9
        assert item["run_id"]
        assert item["created_at"]


def test_run_empty_dataset_is_422(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/evals/run", json={"dataset": []})

    assert response.status_code == 422


def test_run_history_limit_out_of_range_is_422(test_app: TestClient) -> None:
    response = test_app.get("/api/v1/evals/runs", params={"limit": 101})

    assert response.status_code == 422