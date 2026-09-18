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
from app.repositories.usage_repository import UsageRepository
from app.schemas.chat import ChatResult, SourceRef
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.vector.collections import CHUNK_INDEX_FIELD

_SYSTEM_PROMPT = (
    "You are a personal knowledge assistant. Answer grounded in the provided "
    "knowledge. If the knowledge is insufficient, say so and never invent facts."
)
_EXCERPT_LENGTH = 200


# Provider name -> (USD per 1k input tokens, USD per 1k output tokens). The
# rates come from Settings so cost accounting never hardcodes billing (spec
# §30); unknown providers (e.g. the test fake) estimate at zero cost.
def _provider_rates(
    provider: str, settings: Settings
) -> tuple[float, float]:
    rates: dict[str, tuple[float, float]] = {
        "ollama": (settings.ollama_usd_per_1k_in, settings.ollama_usd_per_1k_out),
        "payperq": (settings.payperq_usd_per_1k_in, settings.payperq_usd_per_1k_out),
        "opencode_go": (
            settings.opencode_go_usd_per_1k_in,
            settings.opencode_go_usd_per_1k_out,
        ),
    }
    return rates.get(provider.strip().lower(), (0.0, 0.0))


def _estimate_cost_usd(
    provider: str,
    settings: Settings,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float:
    """Estimate the request cost in USD from the provider's per-1k rates."""
    rate_in, rate_out = _provider_rates(provider, settings)
    tokens_in = prompt_tokens or 0
    tokens_out = completion_tokens or 0
    return (tokens_in / 1000 * rate_in) + (tokens_out / 1000 * rate_out)


class ChatService:
    """Answers a message using retrieved knowledge and an LLM gateway."""

    def __init__(
        self,
        llm: LLMProvider,
        retrieval: RetrievalService,
        settings: Settings,
        usage_repository: UsageRepository | None = None,
        memory: MemoryService | None = None,
    ) -> None:
        self._llm = llm
        self._retrieval = retrieval
        self._settings = settings
        self._usage_repository = usage_repository
        # Optional memory provider (spec §25); when set, approved memories are
        # injected as a MEMORY section ahead of the knowledge chunks. The
        # default keeps existing callers and tests working unchanged.
        self._memory = memory
        self._logger = get_logger("chat_service")

    async def chat(
        self,
        message: str,
        *,
        top_k: int = 5,
        document_id: str | None = None,
        project_id: str | None = None,
    ) -> ChatResult:
        """Return a grounded answer plus the sources it used."""
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        hits = await self._retrieval.retrieve(
            message, top_k=top_k, document_id=document_id, project_id=project_id
        )

        memories: list[str] = []
        if self._memory is not None:
            memories = await self._memory.search_approved(message, top_k=3)

        memory_block = ""
        if memories:
            memory_block = (
                "MEMORY\n" + "\n".join(f"- {item}" for item in memories) + "\n\n"
            )

        if hits:
            knowledge = "\n".join(
                f"[{index + 1}] ({hit.title}) {hit.content}"
                for index, hit in enumerate(hits)
            )
            user_content = (
                f"{memory_block}KNOWLEDGE\n{knowledge}\n\nUSER REQUEST\n{message}"
            )
        else:
            user_content = f"{memory_block}USER REQUEST\n{message}"

        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ]
        result = await self._llm.generate(messages=messages, model=None)
        answer = result.content

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
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens
        estimated_cost_usd = _estimate_cost_usd(
            provider=result.provider,
            settings=self._settings,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        if self._usage_repository is not None:
            await self._usage_repository.create(
                request_id=request_id,
                provider=result.provider,
                model=result.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=estimated_cost_usd,
                latency_ms=latency_ms,
            )
        self._logger.info(
            "chat request completed",
            extra={
                "request_id": request_id,
                "provider": self._llm.name,
                "model": self._settings.llm_model,
                "retrieved_chunks": len(hits),
                "memory_chunks": len(memories),
                "latency_ms": latency_ms,
                "answer_length": len(answer),
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "estimated_cost_usd": estimated_cost_usd,
            },
        )
        return ChatResult(
            answer=answer,
            sources=sources,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )