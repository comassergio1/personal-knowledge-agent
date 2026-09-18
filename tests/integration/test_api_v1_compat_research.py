"""Integration tests for research routing in the OpenAI-compatible shim.

Uses the shared ``test_app`` fixture, whose research service is a fully
offline fake: canned search hits, a canned Spanish §21 report from the fake
LLM, and page extraction swapped for search snippets. A research-triggering
/v1 chat message therefore runs the real research flow against canned
providers and persists the report into the per-test tmp vault.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.research_service import ResearchError

MODEL_ID = "my-notebooklm"
RESEARCH_QUESTION = "investigá en la web qué es asyncio"
RESEARCH_HEADER = "Investigación web completada. Informe guardado en el vault:"
# The header's non-ASCII character is JSON-escaped inside the SSE payload
# (json.dumps with ensure_ascii=True in _stream_chunks), so stream assertions
# use this pure-ASCII fragment instead.
RESEARCH_HEADER_ASCII = "Informe guardado en el vault: inbox/"


class _FailingResearchService:
    """Fake research service that fails like a real search/LLM outage."""

    async def run(self, question, *, project_id=None, title=None):
        raise ResearchError("simulated research outage")


def test_research_trigger_returns_report_with_header(test_app: TestClient) -> None:
    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": RESEARCH_QUESTION}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == MODEL_ID
    assert body["id"].startswith("chatcmpl-")
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["finish_reason"] == "stop"
    content = body["choices"][0]["message"]["content"]
    assert content.startswith(f"{RESEARCH_HEADER} inbox/")
    assert "---" in content
    # The canned §21 report from the fake LLM lands verbatim under the header.
    assert "# Objetivo" in content
    assert "# Hallazgos" in content
    assert "Hallazgo principal [1]." in content
    # The research flow keeps no token accounting: usage is null, not omitted.
    assert body["usage"] == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }


def test_non_trigger_message_uses_grounded_chat(test_app: TestClient) -> None:
    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [
                {"role": "user", "content": "What can you tell me about anchovies?"}
            ],
        },
    )

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "This is a fake grounded answer."
    assert RESEARCH_HEADER not in content


def test_research_trigger_without_research_service_falls_back_to_chat(
    test_app: TestClient,
) -> None:
    # An app that never wired the research service (None) stays on the
    # grounded chat path for trigger messages instead of crashing.
    test_app.app.state.research_service = None

    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": RESEARCH_QUESTION}],
        },
    )

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "This is a fake grounded answer."


def test_research_failure_returns_500_with_openai_error_envelope(
    test_app: TestClient,
) -> None:
    test_app.app.state.research_service = _FailingResearchService()

    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": RESEARCH_QUESTION}],
        },
    )

    assert response.status_code == 500
    body = response.json()
    # Same OpenAI-style envelope as the shim's 400s, only with HTTP 500.
    assert set(body) == {"error"}
    assert "no pude completar la investigación" in body["error"]["message"]
    assert "simulated research outage" in body["error"]["message"]
    assert body["error"]["type"] == "invalid_request_error"


def test_research_trigger_stream_contains_header_delta(
    test_app: TestClient,
) -> None:
    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "stream": True,
            "messages": [{"role": "user", "content": RESEARCH_QUESTION}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    # Single-delta pseudo-stream: the header and report travel inside the one
    # content delta; assertions use ASCII fragments (# Objetivo is pure ASCII,
    # the header's accented chars are JSON-escaped in the SSE payload).
    assert RESEARCH_HEADER_ASCII in body
    assert "# Objetivo" in body
    assert '"finish_reason": "stop"' in body
    assert "data: [DONE]" in body