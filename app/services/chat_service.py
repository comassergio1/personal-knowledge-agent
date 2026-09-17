"""Grounded chat: retrieve context, build the §25 prompt, call the LLM gateway.

The prompt is a cheap string builder with labeled sections: ``SYSTEM`` carries
the assistant identity and grounding rules, ``KNOWLEDGE`` lists the retrieved
chunks as ``[n] (title) content``, and ``USER REQUEST`` carries the user's
message. Without retrieved chunks the reply is generated from the system
prompt alone and sources stay empty.
"""

from __future__ import annotations

import time
import uuid

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.llm.base import ChatMessage, LLMProvider
from app.schemas.chat import ChatResult, SourceRef
from app.services.retrieval_service import RetrievalService
from app.vector.collections import CHUNK_INDEX_FIELD

_SYSTEM_PROMPT = (
    "You are a personal knowledge assistant. Answer grounded in the provided "
    "knowledge. If the knowledge is insufficient, say so and never invent facts."
)
_EXCERPT_LENGTH = 200


class ChatService:
    """Answers a message using retrieved knowledge and an LLM gateway."""

    def __init__(
        self, llm: LLMProvider, retrieval: RetrievalService, settings: Settings
    ) -> None:
        self._llm = llm
        self._retrieval = retrieval
        self._settings = settings
        self._logger = get_logger("chat_service")

    async def chat(
        self, message: str, *, top_k: int = 5, document_id: str | None = None
    ) -> ChatResult:
        """Return a grounded answer plus the sources it used."""
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        hits = await self._retrieval.retrieve(
            message, top_k=top_k, document_id=document_id
        )

        if hits:
            knowledge = "\n".join(
                f"[{index + 1}] ({hit.title}) {hit.content}"
                for index, hit in enumerate(hits)
            )
            user_content = f"KNOWLEDGE\n{knowledge}\n\nUSER REQUEST\n{message}"
        else:
            user_content = f"USER REQUEST\n{message}"

        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ]
        answer = await self._llm.generate(messages=messages, model=None)

        sources = [
            SourceRef(
                document_id=hit.document_id,
                title=hit.title,
                chunk_index=int(hit.metadata.get(CHUNK_INDEX_FIELD, 0)),
                score=hit.score,
                excerpt=hit.content[:_EXCERPT_LENGTH],
            )
            for hit in hits
        ]

        latency_ms = int((time.perf_counter() - started) * 1000)
        self._logger.info(
            "chat request completed",
            extra={
                "request_id": request_id,
                "provider": self._llm.name,
                "model": self._settings.llm_model,
                "retrieved_chunks": len(hits),
                "latency_ms": latency_ms,
                "answer_length": len(answer),
            },
        )
        return ChatResult(answer=answer, sources=sources)