"""On-demand knowledge map: "Qué sé sobre X?" from memories and chunks (Phase 7).

The service mirrors the chat/tutorial prompt contract (SYSTEM persona plus
optional MEMORY and KNOWLEDGE sections plus the TOPIC request) but for a
knowledge map: the topic is embedded and searched against the top-k chunks
(scoped to ``project_id`` when given) and the top approved memories, and the
LLM writes a hierarchical Spanish markdown map (## Conceptos / ## Tutoriales /
## Experiencias / ## Recursos / ## Huecos), citing document titles inline.
The map is response-only in v1: it is generated on demand and never persisted
to the vault.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.llm.base import ChatMessage, LLMProvider
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.vector.qdrant import SearchHit

# The map title header the LLM must emit; a missing header triggers a
# post-check warning (never a raise), like the tutorial/research post-checks.
_MAP_HEADER = "# Qué sé sobre"
# Approved memories fed to the map prompt (spec: top-k 10).
_MEMORY_TOP_K = 10
# Chunk excerpt length per KNOWLEDGE line, mirroring the chat prompt.
_KNOWLEDGE_EXCERPT = 300

# Knowledge-map builder persona; the title embeds the topic. The sections are
# emitted verbatim in Spanish (the map's content language); the writer
# instructions stay English.
_SYSTEM_PROMPT = (
    "You are a knowledge-map builder. Build a hierarchical knowledge map in "
    "SPANISH with the title `# Qué sé sobre {topic}` and exactly these "
    "sections: ## Conceptos, ## Tutoriales, ## Experiencias, ## Recursos, "
    "## Huecos. Ground the map ONLY on the provided knowledge and memories; "
    "cite document titles inline when you use them; if the topic is not "
    "covered by the provided material, say so clearly under ## Huecos and "
    "never invent facts."
)


class KnowledgeMapService:
    """Builds an on-demand hierarchical knowledge map for a topic."""

    def __init__(
        self,
        memory: MemoryService,
        retrieval: RetrievalService,
        llm: LLMProvider,
        settings: Settings,
    ) -> None:
        self._memory = memory
        self._retrieval = retrieval
        self._llm = llm
        self._settings = settings
        self._logger = get_logger("knowledge_map_service")

    async def knowledge_map(
        self,
        topic: str,
        *,
        project_id: str | None = None,
        top_k: int = 6,
    ) -> str:
        """Return the Spanish hierarchical knowledge map markdown for ``topic``.

        The topic is embedded and searched for the top-k chunks (scoped to
        ``project_id`` when given) plus the top approved memories. Chunks are
        deduped by title keeping the highest score, so one document never
        shows twice; every KNOWLEDGE line cites the title plus a 300-char
        excerpt. The prompt follows the chat/tutorial pattern with a SYSTEM
        knowledge-map persona (embedding the topic), optional MEMORY and
        KNOWLEDGE sections (only when non-empty), and the TOPIC request. A
        light post-check warns — never raises — when the LLM output skips the
        `# Qué sé sobre` title. Response-only: the map is never persisted.
        """
        hits = await self._retrieval.retrieve(
            topic, top_k=top_k, project_id=project_id
        )
        memories = await self._memory.search_approved(topic, top_k=_MEMORY_TOP_K)

        memory_block = ""
        if memories:
            memory_block = (
                "MEMORY\n" + "\n".join(f"- {item}" for item in memories) + "\n\n"
            )

        knowledge_block = ""
        if hits:
            lines = [
                f"[{index + 1}] ({hit.title}) {hit.content[:_KNOWLEDGE_EXCERPT]}"
                for index, hit in enumerate(_dedupe_by_title(hits))
            ]
            knowledge_block = "KNOWLEDGE\n" + "\n".join(lines) + "\n\n"

        messages = [
            ChatMessage(
                role="system",
                content=_SYSTEM_PROMPT.format(topic=topic),
            ),
            ChatMessage(
                role="user",
                content=f"{memory_block}{knowledge_block}TOPIC\n{topic}",
            ),
        ]
        result = await self._llm.generate(messages=messages, model=None)
        markdown = result.content

        # Light post-check: warn (never fail) when the LLM skipped the title;
        # the map is still returned unfiltered.
        if _MAP_HEADER not in markdown:
            self._logger.warning(
                "knowledge map output is missing the title header",
                extra={"topic": topic},
            )
        self._logger.info(
            "knowledge map generated",
            extra={
                "provider": self._llm.name,
                "model": self._settings.llm_model,
                "retrieved_chunks": len(hits),
                "memory_chunks": len(memories),
                "content_length": len(markdown),
            },
        )
        return markdown


def _dedupe_by_title(hits: list[SearchHit]) -> list[SearchHit]:
    """Keep the highest-scoring hit per title, ordered by descending score.

    Retrieval can return several chunks of one document; the map wants each
    title once, grounded on its strongest chunk. Survivors keep the retrieval
    rank meaning (best first), so the ``[n]`` numbering still reads as
    relevance.
    """
    best: dict[str, SearchHit] = {}
    for hit in hits:
        current = best.get(hit.title)
        if current is None or hit.score > current.score:
            best[hit.title] = hit
    return sorted(best.values(), key=lambda hit: hit.score, reverse=True)