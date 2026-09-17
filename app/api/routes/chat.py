"""Chat endpoint: grounded answers with cited sources (spec §18/§25/§41)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_chat_service
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    """Answer ``message`` using retrieved knowledge and the LLM gateway."""
    result = await chat_service.chat(
        request.message, top_k=request.top_k, document_id=request.document_id
    )
    return ChatResponse(answer=result.answer, sources=result.sources)