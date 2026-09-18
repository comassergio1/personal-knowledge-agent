"""Unit tests for the OpenAI-compatible surface (v1).

The router is mounted on a bare FastAPI app with a stubbed ``chat_service`` in
``app.state`` (no lifespan, no network). These tests pin the wire format: 400
errors, last-user-message selection, response shape, usage passthrough, the
Fuentes block, the SSE pseudo-stream, and /v1/models.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.v1_compat import MODEL_ID, router
from app.schemas.chat import ChatResult, SourceRef


class FakeChatService:
    """Stub ChatService returning a canned result and recording queries."""

    def __init__(self, result: ChatResult) -> None:
        self._result = result
        self.queries: list[str] = []

    async def chat(self, message, *, top_k=5, document_id=None, project_id=None):
        self.queries.append(message)
        return self._result


def _client(result: ChatResult) -> tuple[TestClient, FakeChatService]:
    app = FastAPI()
    app.include_router(router)
    service = FakeChatService(result)
    app.state.chat_service = service
    return TestClient(app), service


def _source(title: str) -> SourceRef:
    return SourceRef(
        document_id="doc-1", title=title, chunk_index=0, score=0.9, excerpt="excerpt"
    )


# -- request model ------------------------------------------------------------


def test_request_model_defaults() -> None:
    from app.api.routes.v1_compat import CompletionsRequest

    payload = CompletionsRequest(
        model=MODEL_ID, messages=[{"role": "user", "content": "hello"}]
    )
    assert payload.stream is False
    assert payload.temperature is None
    assert payload.max_tokens is None


def test_unknown_role_returns_400_with_openai_error_shape() -> None:
    client, _ = _client(ChatResult(answer="ok"))
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "wizard", "content": "hello"}],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert "wizard" in body["error"]["message"]
    assert body["error"]["type"] == "invalid_request_error"


def test_empty_content_returns_400_with_openai_error_shape() -> None:
    client, _ = _client(ChatResult(answer="ok"))
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": "   "}],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert "non-empty" in body["error"]["message"]


def test_empty_messages_returns_400_with_openai_error_shape() -> None:
    client, _ = _client(ChatResult(answer="ok"))
    response = client.post(
        "/v1/chat/completions", json={"model": MODEL_ID, "messages": []}
    )

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert "user message is required" in body["error"]["message"]


def test_missing_user_message_returns_400() -> None:
    client, _ = _client(ChatResult(answer="ok"))
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "system", "content": "be brief"}],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


def test_last_user_message_is_used_as_query() -> None:
    client, service = _client(ChatResult(answer="ok"))
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "an answer"},
                {"role": "user", "content": "second question"},
            ],
        },
    )

    assert response.status_code == 200
    # Multi-turn summarization is a later enhancement: only the last user
    # message reaches the chat service.
    assert service.queries == ["second question"]


# -- response shape -----------------------------------------------------------


def test_completion_response_shape_and_message_fields() -> None:
    client, _ = _client(ChatResult(answer="A grounded answer."))
    response = client.post(
        "/v1/chat/completions",
        json={"model": MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("chatcmpl-")
    assert body["object"] == "chat.completion"
    assert isinstance(body["created"], int)
    assert body["model"] == MODEL_ID
    assert body["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "A grounded answer."},
            "finish_reason": "stop",
        }
    ]
    assert set(body["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}


def test_usage_passthrough_when_tokens_present() -> None:
    client, _ = _client(
        ChatResult(answer="ok", prompt_tokens=11, completion_tokens=7)
    )
    response = client.post(
        "/v1/chat/completions",
        json={"model": MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )

    body = response.json()
    assert body["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }


def test_usage_total_is_none_when_tokens_unknown() -> None:
    client, _ = _client(ChatResult(answer="ok", prompt_tokens=None, completion_tokens=None))
    response = client.post(
        "/v1/chat/completions",
        json={"model": MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )

    body = response.json()
    assert body["usage"] == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }


# -- Fuentes block ------------------------------------------------------------


def test_sources_block_appended_when_sources_exist() -> None:
    client, _ = _client(
        ChatResult(answer="A grounded answer.", sources=[_source("Note A"), _source("Note B")])
    )
    response = client.post(
        "/v1/chat/completions",
        json={"model": MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )

    content = response.json()["choices"][0]["message"]["content"]
    assert content == "A grounded answer.\n\n**Fuentes:**\n- Note A\n- Note B"


def test_sources_block_absent_without_sources() -> None:
    client, _ = _client(ChatResult(answer="Plain answer."))
    response = client.post(
        "/v1/chat/completions",
        json={"model": MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )

    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Plain answer."
    assert "Fuentes" not in content


# -- stream -------------------------------------------------------------------


def test_stream_response_contains_delta_finish_and_done() -> None:
    client, _ = _client(ChatResult(answer="Streamed answer."))
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "data: [DONE]" in body
    assert '"object": "chat.completion.chunk"' in body
    # The full content arrives in one delta (single-shot pseudo-stream).
    assert '"content": "Streamed answer."' in body
    assert '"finish_reason": "stop"' in body
    # The stream carries usage-free, delta-only chunks; no server-side token
    # scheduling happens, so there is exactly one content delta.
    assert body.count('"content": "Streamed answer."') == 1


# -- /v1/models ---------------------------------------------------------------


def test_get_models_lists_single_model() -> None:
    client, _ = _client(ChatResult(answer="ok"))
    response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 1
    model = body["data"][0]
    assert model["id"] == MODEL_ID
    assert model["object"] == "model"
    assert isinstance(model["created"], int)
    assert model["owned_by"] == "pka"