"""Chat request/response shapes shared by the chat service and the API.

``SourceRef`` and ``ChatResult`` are Pydantic models so FastAPI can serialize
service results directly; ``ChatService.chat`` keeps returning ``ChatResult``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """One knowledge source cited in a chat answer."""

    document_id: str
    title: str
    chunk_index: int
    score: float
    excerpt: str


class ChatResult(BaseModel):
    """A chat answer together with the sources it was grounded in.

    ``prompt_tokens``/``completion_tokens`` are copied from the LLM provider
    response when it reports usage (spec §30); they stay ``None`` when the
    provider does not (e.g. the offline test fake).
    """

    answer: str
    sources: list[SourceRef] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ChatRequest(BaseModel):
    """Payload for POST /api/v1/chat."""

    message: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1)
    document_id: str | None = None
    project_id: str | None = None


class ChatResponse(BaseModel):
    """Response payload for POST /api/v1/chat."""

    answer: str
    sources: list[SourceRef] = []