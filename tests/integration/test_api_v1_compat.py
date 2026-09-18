"""API integration tests for the OpenAI-compatible surface (TestClient + fakes).

Uses the shared ``test_app`` fixture: the fake LLM answers with a canned
grounded answer and the seeded document provides real retrieved sources, so
the full /v1 flow (retrieval -> chat -> wire format) is exercised offline.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

MODEL_ID = "my-notebooklm"


def _seed_document(test_app: TestClient) -> None:
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


def test_v1_chat_completions_returns_grounded_answer_with_fuentes(
    test_app: TestClient,
) -> None:
    _seed_document(test_app)

    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": "What can you tell me about anchovies?"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == MODEL_ID
    assert body["id"].startswith("chatcmpl-")
    assert body["choices"][0]["index"] == 0
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["finish_reason"] == "stop"
    # Grounded answer plus the trailing Fuentes block listing the retrieved
    # document title (seeded doc "facts.md" -> title "facts").
    assert body["choices"][0]["message"]["content"] == (
        "This is a fake grounded answer.\n\n**Fuentes:**\n- facts"
    )
    # The fake LLM reports zero tokens: usage is present, not omitted.
    assert body["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def test_v1_models_lists_my_notebooklm(test_app: TestClient) -> None:
    response = test_app.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"] == [
        {
            "id": MODEL_ID,
            "object": "model",
            "created": body["data"][0]["created"],
            "owned_by": "pka",
        }
    ]


def test_v1_stream_returns_sse_pseudo_stream(test_app: TestClient) -> None:
    _seed_document(test_app)

    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "stream": True,
            "messages": [{"role": "user", "content": "What can you tell me about anchovies?"}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert '"content": "This is a fake grounded answer.' in body
    assert '"finish_reason": "stop"' in body
    assert "data: [DONE]" in body


def test_v1_unknown_role_returns_400_with_openai_error_shape(
    test_app: TestClient,
) -> None:
    response = test_app.post(
        "/v1/chat/completions",
        json={
            "model": MODEL_ID,
            "messages": [{"role": "systemx", "content": "hello"}],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert "systemx" in body["error"]["message"]
    assert body["error"]["type"] == "invalid_request_error"