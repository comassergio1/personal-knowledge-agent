"""API integration tests for the learning endpoints (TestClient + fakes, offline).

The learning loop runs over the testing app: retrieval hits come from the
in-memory vector store (fixed score 0.9), research uses the fake search
provider + fake LLM (no network), and the tutorial/memory flows reuse the
same seams. ``learn/run`` persists both the research report (when it runs)
and the tutorial into the tmp vault + index; ``learn/reflect`` persists
redacted candidate memories.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.learn_service import LearnError

_REFLECT_HINT = (
    "Respondé con lo que aprendiste/hiciste para guardarlo como memoria "
    "(POST /learn/reflect)."
)


class _BoomLearn:
    """LearnService stand-in that fails like an infrastructure outage."""

    async def run(self, goal, *, mode="learn", **kwargs) -> None:
        raise LearnError("vector store down")

    async def reflect(self, goal, what_i_learned, *, project_id=None) -> None:
        raise LearnError("memory extractor down")


def test_learn_run_researches_and_persists_tutorial(
    test_app: TestClient, tmp_path
) -> None:
    response = test_app.post(
        "/api/v1/learn/run",
        json={
            "goal": "Aprende VLANs 802.1Q",
            "mode": "deep_learn",
            "title": "VLAN Deep Dive",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["goal"] == "Aprende VLANs 802.1Q"
    assert payload["mode"] == "deep_learn"
    # Empty vault -> assessment finds no knowledge, so research ran.
    assert payload["needs_research"] is True
    research = payload["research"]
    assert research is not None
    assert research["document_id"]
    assert research["file_path"] == "inbox/vlan-deep-dive.md"

    tutorial = payload["tutorial"]
    assert tutorial["document_id"]
    # The research report already claimed the base filename, so the tutorial
    # lands in the -2 variant (Obsidian-style dedupe on disk).
    assert tutorial["file_path"] == "inbox/vlan-deep-dive-2.md"
    assert tutorial["content"] == "This is a fake grounded answer."
    assert tutorial["sources"]
    assert payload["reflect_hint"] == _REFLECT_HINT

    # The tutorial is immediately readable as a document and on disk.
    detail = test_app.get(f"/api/v1/documents/{tutorial['document_id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == tutorial["content"]
    assert detail.json()["file_path"] == tutorial["file_path"]

    vault_file = tmp_path / "vault" / "inbox" / "vlan-deep-dive-2.md"
    assert vault_file.exists()
    assert vault_file.read_text(encoding="utf-8") == tutorial["content"]


def test_learn_run_with_sufficient_knowledge_skips_research(
    test_app: TestClient,
) -> None:
    uploaded = test_app.post(
        "/api/v1/documents",
        files={
            "file": (
                "vlan-notes.md",
                b"802.1Q tags VLANs on trunk ports.\n",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201

    response = test_app.post(
        "/api/v1/learn/run", json={"goal": "VLAN 802.1Q tagging"}
    )

    assert response.status_code == 201
    payload = response.json()
    # Retrieval finds the uploaded note above the default threshold.
    assert payload["needs_research"] is False
    assert payload["research"] is None
    assert payload["tutorial"]["document_id"]


def test_learn_run_reports_gap_without_research_when_disallowed(
    test_app: TestClient,
) -> None:
    response = test_app.post(
        "/api/v1/learn/run",
        json={"goal": "Asincronía en Python", "allow_research": False},
    )

    assert response.status_code == 201
    payload = response.json()
    # No knowledge in the vault, but research is disabled: the gap is
    # reported and the tutorial is still generated from what the vault knows.
    assert payload["needs_research"] is True
    assert payload["research"] is None
    assert payload["tutorial"]["document_id"]


def test_learn_reflect_returns_redacted_candidate_memories(
    test_app: TestClient,
) -> None:
    response = test_app.post(
        "/api/v1/learn/reflect",
        json={
            "goal": "Docker",
            "what_i_learned": "aprendí a usar docker compose para levantar servicios",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["id"]
    assert candidate["status"] == "candidate"
    assert candidate["memory_type"] == "preference"
    assert candidate["confidence"] == 0.9
    assert "[REDACTED]" in candidate["content"]
    assert "hunter2" not in candidate["content"]

    # The candidate is persisted: fetchable by id.
    detail = test_app.get(f"/api/v1/memories/{candidate['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "candidate"


def test_learn_run_empty_goal_is_422(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/learn/run", json={"goal": ""})

    assert response.status_code == 422


def test_learn_reflect_empty_fields_are_422(test_app: TestClient) -> None:
    response = test_app.post(
        "/api/v1/learn/reflect",
        json={"goal": "Docker", "what_i_learned": ""},
    )

    assert response.status_code == 422


def test_learn_run_error_is_502(test_app: TestClient) -> None:
    test_app.app.state.learn_service = _BoomLearn()  # type: ignore[assignment]

    response = test_app.post("/api/v1/learn/run", json={"goal": "VLANs"})

    assert response.status_code == 502
    assert "vector store down" in response.json()["detail"]


def test_learn_reflect_error_is_502(test_app: TestClient) -> None:
    test_app.app.state.learn_service = _BoomLearn()  # type: ignore[assignment]

    response = test_app.post(
        "/api/v1/learn/reflect",
        json={"goal": "VLANs", "what_i_learned": "algo"},
    )

    assert response.status_code == 502
    assert "memory extractor down" in response.json()["detail"]