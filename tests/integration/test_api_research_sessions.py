"""API integration tests for research sessions (TestClient + fakes, offline).

The testing app answers research prompts with canned content: the fake LLM
returns a canned query array for interpretation and a canned Spanish report
for synthesis; the fake search provider returns mixed-quality hits. Research
reports are persisted into the vault and ingested, so "research was not run"
is observable by counting documents.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.research_chat_service import ResearchChatService


class _OfflineSearch:
    """Fake search provider that never answers (the SearXNG-down case)."""

    name = "offline-search"

    async def ping(self) -> bool:
        return False

    async def search(self, query: str, *, limit: int = 10) -> list:
        return []

    async def close(self) -> None:
        return None


def _create_session(client: TestClient, title: str | None = None) -> dict:
    response = client.post(
        "/api/v1/research/sessions", json={"title": title} if title else {}
    )
    assert response.status_code == 201
    return response.json()


def _send_turn(client: TestClient, session_id: str, message: str) -> dict:
    response = client.post(
        f"/api/v1/research/sessions/{session_id}/turn",
        json={"message": message},
    )
    assert response.status_code == 200
    return response.json()


# -- session lifecycle --------------------------------------------------------


def test_create_list_and_detail_session(test_app: TestClient) -> None:
    created = _create_session(test_app, title="VLANs en MikroTik")

    assert created["id"]
    assert created["title"] == "VLANs en MikroTik"
    assert created["turn_count"] == 0

    listed = test_app.get("/api/v1/research/sessions").json()
    assert listed["total"] == 1
    item = listed["items"][0]
    assert item["title"] == "VLANs en MikroTik"
    assert item["turn_count"] == 0
    assert item["updated_at"]

    detail = test_app.get(f"/api/v1/research/sessions/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["turns"] == []


def test_new_session_defaults_its_title(test_app: TestClient) -> None:
    created = _create_session(test_app)

    assert created["title"] == "Sesión de investigación"


# -- turns --------------------------------------------------------------------


def test_turn_without_trigger_answers_grounded_without_research(
    test_app: TestClient,
) -> None:
    client = test_app
    uploaded = client.post(
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
    session = _create_session(client)

    turn = _send_turn(client, session["id"], "¿qué son las anchoas?")

    assert turn["role"] == "assistant"
    assert turn["kind"] == "answer"
    assert turn["research_document_id"] is None
    assert turn["content"] == "This is a fake grounded answer."
    assert len(turn["sources"]) == 1
    assert turn["sources"][0]["document_id"] == uploaded.json()["id"]
    assert turn["sources"][0]["title"] == "facts"

    # No research report was produced: only the seeded document exists.
    documents = client.get("/api/v1/documents").json()
    assert [doc["id"] for doc in documents["items"]] == [uploaded.json()["id"]]

    # The thread records both the user message and the grounded answer.
    detail = client.get(f"/api/v1/research/sessions/{session['id']}").json()
    assert detail["turn_count"] == 2
    assert [(t["role"], t["kind"]) for t in detail["turns"]] == [
        ("user", "answer"),
        ("assistant", "answer"),
    ]


def test_turn_with_trigger_runs_research_and_persists_the_report(
    test_app: TestClient,
) -> None:
    client = test_app
    session = _create_session(client)

    turn = _send_turn(client, session["id"], "buscar en la web ¿qué es asyncio?")

    assert turn["role"] == "assistant"
    assert turn["kind"] == "research"
    assert turn["research_document_id"]
    # The assistant turn carries a short Spanish summary of the report plus
    # the vault file path and the consulted sources.
    assert "Resumen breve de los hallazgos." in turn["content"]
    assert "inbox/que-es-asyncio.md" in turn["content"]
    assert "Fuentes:" in turn["content"]
    assert len(turn["sources"]) >= 1
    assert turn["sources"][0]["title"].startswith("asyncio")

    # The report is readable as a persisted, ingested document.
    report = client.get(f"/api/v1/documents/{turn['research_document_id']}")
    assert report.status_code == 200
    assert "# Objetivo" in report.json()["content"]
    assert report.json()["file_path"] == "inbox/que-es-asyncio.md"
    assert report.json()["source_type"] == "research"

    # The empty-default session title adopted the research topic (raw target;
    # only vault file paths are slugified).
    detail = client.get(f"/api/v1/research/sessions/{session['id']}").json()
    assert detail["title"] == "qué es asyncio"
    assert detail["turn_count"] == 2


def test_bare_trigger_falls_back_to_the_session_topic(test_app: TestClient) -> None:
    client = test_app
    session = _create_session(client)

    first = _send_turn(client, session["id"], "buscar en la web pydantic")
    assert first["kind"] == "research"

    # A bare trigger (no target) researches the session topic again.
    second = _send_turn(client, session["id"], "buscá en la web")

    assert second["kind"] == "research"
    report = client.get(f"/api/v1/documents/{second['research_document_id']}")
    assert report.status_code == 200
    # The fallback resolved the empty target to the session topic: the new
    # report is about pydantic again (the canned report is byte-identical, so
    # idempotent ingest may dedupe to the same document id).
    assert report.json()["title"] == "pydantic"
    assert "inbox/pydantic.md" in second["content"]


def test_turn_with_voseo_trigger_runs_research(test_app: TestClient) -> None:
    client = test_app
    session = _create_session(client)

    turn = _send_turn(client, session["id"], "buscá en internet ollama")

    assert turn["kind"] == "research"
    assert turn["research_document_id"]
    assert "inbox/ollama.md" in turn["content"]


# -- tutorial -----------------------------------------------------------------


def test_save_tutorial_returns_file_path_and_content(test_app: TestClient) -> None:
    client = test_app
    session = _create_session(client)
    _send_turn(client, session["id"], "buscar en la web asyncio")

    response = client.post(
        f"/api/v1/research/sessions/{session['id']}/tutorial",
        json={"mode": "do"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content"] == "This is a fake grounded answer."
    assert payload["file_path"]
    assert payload["file_path"].startswith("inbox/")
    assert payload["file_path"].endswith(".md")
    assert payload["mode"] == "do"
    assert payload["document_id"]


def test_save_tutorial_rejects_unknown_mode(test_app: TestClient) -> None:
    session = _create_session(test_app)

    response = test_app.post(
        f"/api/v1/research/sessions/{session['id']}/tutorial",
        json={"mode": "bogus"},
    )

    assert response.status_code == 422


# -- route errors -------------------------------------------------------------


def test_missing_session_is_404(test_app: TestClient) -> None:
    assert test_app.get("/api/v1/research/sessions/missing").status_code == 404
    assert (
        test_app.post(
            "/api/v1/research/sessions/missing/turn", json={"message": "hola"}
        ).status_code
        == 404
    )
    assert (
        test_app.post(
            "/api/v1/research/sessions/missing/tutorial", json={"mode": "do"}
        ).status_code
        == 404
    )


def test_empty_message_is_422(test_app: TestClient) -> None:
    session = _create_session(test_app)

    response = test_app.post(
        f"/api/v1/research/sessions/{session['id']}/turn", json={"message": ""}
    )

    assert response.status_code == 422


def test_trigger_with_unreachable_search_is_503(test_app: TestClient) -> None:
    app = test_app.app
    app.state.research_chat_service = ResearchChatService(  # type: ignore[arg-type]
        llm=app.state.llm,
        retrieval=app.state.retrieval_service,
        research=app.state.research_service,
        tutorial=app.state.tutorial_service,
        search=_OfflineSearch(),
        settings=app.state.settings,
        repository=app.state.research_session_repository,
        usage_repository=app.state.usage_repository,
        memory=app.state.memory_service,
    )
    session = _create_session(test_app)

    response = test_app.post(
        f"/api/v1/research/sessions/{session['id']}/turn",
        json={"message": "buscar en la web asyncio"},
    )

    assert response.status_code == 503
    assert "SearXNG no responde" in response.json()["detail"]


# -- console contract ---------------------------------------------------------


def test_console_serves_the_explore_tab(test_app: TestClient) -> None:
    index = test_app.get("/").text
    app_js = test_app.get("/static/app.js").text

    assert 'data-tab="explore"' in index
    assert "Explorar" in index
    assert "/api/v1/research/sessions" in app_js
    # The muted hint listing the trigger phrases is user-facing copy.
    assert "buscar en la web" in index