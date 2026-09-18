"""API integration tests for the research endpoint (TestClient + fakes, offline).

The testing app answers research prompts with canned content: the fake LLM
returns a canned query array for interpretation and a canned Spanish report
(without ``# Fuentes``, so the post-check warning surfaces) for synthesis; the
fake search provider returns mixed-quality hits. No network is touched.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.providers.llm.base import LLMProviderError
from app.services.research_service import ResearchService


class _BoomResearchLLM:
    """Fake LLM that fails like a real provider outage."""

    name = "boom-research-llm"

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> None:
        raise LLMProviderError("research llm exploded")


class _OfflineSearch:
    """Fake search provider that never answers (the SearXNG-down case)."""

    name = "offline-search"

    async def ping(self) -> bool:
        return False

    async def search(self, query: str, *, limit: int = 10) -> list:
        return []

    async def close(self) -> None:
        return None


def test_run_research_returns_persisted_document(test_app: TestClient) -> None:
    response = test_app.post(
        "/api/v1/research/run",
        json={"question": "¿Qué es asyncio?", "title": "Informe asyncio"},
    )

    assert response.status_code == 201
    payload = response.json()
    # Canned Spanish report from the fake LLM; it skips # Fuentes, so the
    # post-check surfaces as a warning instead of failing the request.
    assert "# Objetivo" in payload["report"]
    assert "# Resumen" in payload["report"]
    assert "# Hallazgos" in payload["report"]
    assert "Hallazgo principal [1]." in payload["report"]
    assert payload["warnings"] == ["# Fuentes"]
    assert payload["title"] == "Informe asyncio"
    assert payload["document_id"]
    assert payload["file_path"] == "inbox/informe-asyncio.md"

    # Sources come back in ranked order (docs > stack overflow > medium > reddit).
    assert [source["domain"] for source in payload["sources"]] == [
        "docs.python.org",
        "stackoverflow.com",
        "medium.com",
        "www.reddit.com",
    ]
    first = payload["sources"][0]
    assert first["title"].startswith("asyncio")
    assert first["url"].startswith("https://docs.python.org/")

    # The persisted report is immediately readable as a document.
    detail = test_app.get(f"/api/v1/documents/{payload['document_id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == payload["report"]
    assert detail.json()["file_path"] == payload["file_path"]
    assert detail.json()["stale"] is False


def test_empty_question_is_422(test_app: TestClient) -> None:
    response = test_app.post("/api/v1/research/run", json={"question": ""})

    assert response.status_code == 422


def test_max_sources_out_of_range_is_422(test_app: TestClient) -> None:
    for value in (0, 16):
        response = test_app.post(
            "/api/v1/research/run", json={"question": "x", "max_sources": value}
        )
        assert response.status_code == 422


def test_unreachable_search_is_503(test_app: TestClient) -> None:
    test_app.app.state.search_provider = _OfflineSearch()

    response = test_app.post(
        "/api/v1/research/run", json={"question": "anything"}
    )

    assert response.status_code == 503
    assert "SearXNG no responde" in response.json()["detail"]


def test_llm_failure_is_502(test_app: TestClient) -> None:
    app = test_app.app
    app.state.research_service = ResearchService(  # type: ignore[arg-type]
        _BoomResearchLLM(),
        search=app.state.search_provider,
        vault=app.state.vault_service,
        ingestion=app.state.ingestion_service,
        settings=app.state.settings,
    )

    response = test_app.post(
        "/api/v1/research/run", json={"question": "anything"}
    )

    assert response.status_code == 502
    assert "research llm exploded" in response.json()["detail"]