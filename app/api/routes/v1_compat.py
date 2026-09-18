"""OpenAI-compatible surface for My NotebookLM (feature: openai-shim).

Exposes ``GET /v1/models`` and ``POST /v1/chat/completions`` following the
OpenAI wire format so external clients (e.g. Open WebUI) can use PKA as a
chat provider while PKA keeps ownership of retrieval, memory, and sources
(spec §25). The provider stack is fixed by Settings, so the request ``model``
field is accepted and intentionally ignored; ``MODEL_ID`` is what
``/v1/models`` advertises.

The grounded answer is produced by the same ``ChatService`` used by
``/api/v1/chat``. Retrieved titles are appended as a markdown block using one
``- {title}`` line per source (leading ``- `` bullets; the ``**Fuentes:**``
heading stays in Spanish per the product language):

    **Fuentes:**
    - Note A

Research-intent messages (``app.api.routes.research_intent``) take the
research branch instead: the shared ``ResearchService`` runs the §21 flow
(interpret → search → extract → synthesize → persist) and the report, saved
into the vault by the service itself, is returned verbatim under a one-line
header — no extra LLM turn. A failed research run surfaces as a 500 OpenAI
error envelope, never a silent fallback to grounded chat.

``stream: true`` is honored as a single-shot SSE pseudo-stream in the OpenAI
delta format: one chunk carrying the full content, then a finish chunk, then
``data: [DONE]``. No token-level scheduling is performed.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_chat_service
from app.api.routes.research_intent import is_research_request
from app.core.logging import get_logger
from app.schemas.chat import ChatResult
from app.services.chat_service import ChatService
from app.services.research_service import ResearchError, ResearchService

router = APIRouter(prefix="/v1", tags=["v1-compat"])

MODEL_ID = "my-notebooklm"
_OWNED_BY = "pka"
_ALLOWED_ROLES = {"system", "user", "assistant"}
_logger = get_logger("v1_compat")


class CompletionsMessage(BaseModel):
    """One chat turn in the OpenAI wire format."""

    role: str
    content: str


class CompletionsRequest(BaseModel):
    """Payload accepted by POST /v1/chat/completions (OpenAI wire format)."""

    model: str
    messages: list[CompletionsMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


def _error(message: str) -> dict[str, str]:
    """OpenAI-style error envelope: ``{"error": {"message", "type"}}``."""
    return {"error": {"message": message, "type": "invalid_request_error"}}


class _InvalidRequest(Exception):
    """Invalid OpenAI request; the endpoint renders it as a 400."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _query_from_messages(messages: list[CompletionsMessage]) -> str:
    """Return the last user message content, rejecting invalid turns with 400.

    Unknown roles and empty content are rejected with an OpenAI-style error;
    a request with no user turn is rejected the same way. The query is the
    **last** user message: multi-turn history summarization is a later
    enhancement, so earlier turns are ignored.
    """
    for message in messages:
        if message.role not in _ALLOWED_ROLES:
            raise _InvalidRequest(f"unsupported role: {message.role!r}")
        if not message.content.strip():
            raise _InvalidRequest("message content must be a non-empty string")
    user_messages = [message for message in messages if message.role == "user"]
    if not user_messages:
        raise _InvalidRequest("at least one user message is required")
    return user_messages[-1].content


def _get_research_service(request: Request) -> ResearchService | None:
    """The shared research service from ``app.state``, or None when unwired.

    The research service is optional in this shim: apps that never wired it
    keep the grounded chat path working without research.
    """
    return getattr(request.app.state, "research_service", None)


def _usage(prompt_tokens: int | None, completion_tokens: int | None) -> dict:
    """Usage object; ``total_tokens`` is None when either count is unknown."""
    total_tokens = None
    if prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _content_with_sources(result: ChatResult) -> str:
    """The answer plus the trailing ``**Fuentes:**`` block when sources exist."""
    if not result.sources:
        return result.answer
    sources_block = "\n\n**Fuentes:**\n" + "\n".join(
        f"- {source.title}" for source in result.sources
    )
    return f"{result.answer}{sources_block}"


def _completion_response(
    content: str, *, prompt_tokens: int | None, completion_tokens: int | None
) -> dict:
    """One non-streamed chat completion in the OpenAI wire format."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(prompt_tokens, completion_tokens),
    }


def _completion_payload(content: str, result: ChatResult) -> dict:
    """Chat completion payload with the grounded result's token counts."""
    return _completion_response(
        content,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )


async def _stream_chunks(content: str) -> AsyncIterator[str]:
    """Yield the single-shot SSE pseudo-stream (delta + finish + [DONE])."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    base = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_ID,
    }
    content_chunk = {
        **base,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(content_chunk)}\n\n"
    finish_chunk = {
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(finish_chunk)}\n\n"
    yield "data: [DONE]\n\n"


@router.get("/models")
async def list_models() -> dict:
    """Advertise the single fixed model ``MODEL_ID``."""
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": _OWNED_BY,
            }
        ],
    }


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: CompletionsRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    research_service: Annotated[ResearchService | None, Depends(_get_research_service)],
) -> StreamingResponse | dict:
    """Answer the last user message with a grounded OpenAI-format reply.

    Research-intent messages (see ``app.api.routes.research_intent``) run
    through the shared ``ResearchService`` instead: the report is persisted
    into the vault by the service and returned under a short header, with no
    extra chat turn; a ``ResearchError`` renders as a 500 OpenAI error
    envelope. Every other message runs through the shared ``ChatService``
    with the default project scope (``top_k=5``, no document/project
    filter). ``stream: true`` switches to the SSE pseudo-stream described in
    the module docstring.
    """
    try:
        query = _query_from_messages(request.messages)
    except _InvalidRequest as exc:
        return JSONResponse(status_code=400, content=_error(exc.message))

    research_content: str | None = None
    if research_service is not None and is_research_request(query):
        try:
            research_result = await research_service.run(
                query, project_id=None, title=None
            )
        except ResearchError as exc:
            # No silent fallback: the user explicitly asked for research.
            return JSONResponse(
                status_code=500,
                content=_error(f"no pude completar la investigación: {exc}"),
            )
        if research_result.report:
            header = (
                "Investigación web completada. Informe guardado en el vault: "
                f"{research_result.file_path}"
            )
            research_content = f"{header}\n\n---\n\n{research_result.report}"
        else:
            _logger.warning("research report is empty; falling back to grounded chat")
    if research_content is not None:
        if request.stream:
            return StreamingResponse(
                _stream_chunks(research_content),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        # The research flow keeps no token accounting: usage fields are null.
        return _completion_response(
            research_content, prompt_tokens=None, completion_tokens=None
        )

    result = await chat_service.chat(query, top_k=5)
    content = _content_with_sources(result)
    if request.stream:
        return StreamingResponse(
            _stream_chunks(content),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    return _completion_payload(content, result)