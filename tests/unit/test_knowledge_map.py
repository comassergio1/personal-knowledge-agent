"""Unit tests for KnowledgeMapService: on-demand "Qué sé sobre X?" maps.

The service is prompt orchestration over retrieval/memory/LLM, so every
dependency is a fake that records its calls; the LLM fake captures the exact
messages so the MEMORY/KNOWLEDGE/TOPIC prompt contract is asserted textually,
and the title-dedupe/truncation behavior is verified on the captured prompt.
"""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.providers.llm.base import LLMResult
from app.services.knowledge_map import KnowledgeMapService
from app.vector.qdrant import SearchHit

_CANNED_MAP = """# Qué sé sobre redes

## Conceptos

- VLAN: etiquetado 802.1Q.
"""


class FakeLLM:
    """Records the messages passed to ``generate`` and returns a canned map."""

    name = "fake-map-llm"

    def __init__(self, content: str | None = None) -> None:
        self.messages: list | None = None
        self.content = content if content is not None else _CANNED_MAP

    async def generate(
        self, messages, *, model: str | None = None, **kwargs
    ) -> LLMResult:
        self.messages = list(messages)
        return LLMResult(
            content=self.content,
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-map-llm",
            model="test-model",
        )


class FakeRetrieval:
    """Returns pre-built hits and records the retrieval arguments."""

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits = hits if hits is not None else []
        self.calls: list[dict] = []

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_id: str | None = None,
        project_id: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "document_id": document_id,
                "project_id": project_id,
                "score_threshold": score_threshold,
            }
        )
        return self.hits


class FakeMemory:
    """Returns canned approved-memory contents and records the queries."""

    def __init__(self, memories: list[str] | None = None) -> None:
        self.memories = memories if memories is not None else []
        self.calls: list[dict] = []

    async def search_approved(self, query: str, top_k: int = 3) -> list[str]:
        self.calls.append({"query": query, "top_k": top_k})
        return self.memories


def _hit(index: int, title: str, content: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=f"chunk-{index}",
        document_id=f"doc-{index}",
        title=title,
        content=content,
        score=score,
        metadata={},
    )


def _service(
    llm: FakeLLM | None = None,
    hits: list[SearchHit] | None = None,
    memories: list[str] | None = None,
) -> tuple[KnowledgeMapService, FakeLLM, FakeRetrieval, FakeMemory]:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    fake_llm = llm if llm is not None else FakeLLM()
    retrieval = FakeRetrieval(hits)
    memory = FakeMemory(memories)
    service = KnowledgeMapService(
        memory,  # type: ignore[arg-type]
        retrieval,  # type: ignore[arg-type]
        fake_llm,  # type: ignore[arg-type]
        settings,
    )
    return service, fake_llm, retrieval, memory


async def test_knowledge_map_builds_prompt_with_memory_and_knowledge() -> None:
    hits = [
        _hit(0, "Nota A", "contenido alpha", 0.91),
        _hit(3, "Nota B", "contenido beta", 0.77),
    ]
    service, llm, retrieval, memory = _service(
        hits=hits, memories=["Prefiere explicaciones con ejemplos"]
    )

    result = await service.knowledge_map("redes")

    assert retrieval.calls == [
        {
            "query": "redes",
            "top_k": 6,
            "document_id": None,
            "project_id": None,
            "score_threshold": None,
        }
    ]
    assert memory.calls == [{"query": "redes", "top_k": 10}]
    assert llm.messages is not None
    assert len(llm.messages) == 2
    system, user = llm.messages
    assert system.role == "system"
    assert "SPANISH" in system.content
    assert "# Qué sé sobre redes" in system.content
    assert "## Huecos" in system.content
    assert user.role == "user"
    assert "MEMORY\n- Prefiere explicaciones con ejemplos\n\nKNOWLEDGE" in user.content
    assert "[1] (Nota A) contenido alpha" in user.content
    assert "[2] (Nota B) contenido beta" in user.content
    assert "TOPIC\nredes" in user.content

    assert result == _CANNED_MAP


async def test_knowledge_map_dedupes_hits_by_title_keeping_the_highest_score() -> None:
    hits = [
        _hit(0, "Nota A", "contenido debil", 0.5),
        _hit(1, "Nota B", "contenido beta", 0.9),
        _hit(2, "Nota A", "contenido fuerte", 0.8),
    ]
    service, llm, _, _ = _service(hits=hits)

    await service.knowledge_map("redes")

    assert llm.messages is not None
    user = llm.messages[1]
    assert "contenido beta" in user.content
    assert "contenido fuerte" in user.content
    assert "contenido debil" not in user.content
    # Survivors keep the retrieval rank (highest score first), renumbered.
    assert "[1] (Nota B) contenido beta" in user.content
    assert "[2] (Nota A) contenido fuerte" in user.content


async def test_knowledge_map_truncates_long_chunk_content_to_1800_chars() -> None:
    service, llm, _, _ = _service(hits=[_hit(0, "Nota A", "x" * 5000, 0.91)])

    await service.knowledge_map("redes")

    assert llm.messages is not None
    user = llm.messages[1]
    line = next(line for line in user.content.splitlines() if line.startswith("[1]"))
    assert line == "[1] (Nota A) " + "x" * 1800


async def test_empty_knowledge_still_builds_a_prompt_with_the_huecos_instruction() -> None:
    service, llm, _, _ = _service(hits=[], memories=[])

    result = await service.knowledge_map("temas oscuros")

    assert llm.messages is not None
    system, user = llm.messages
    assert "## Huecos" in system.content
    assert "TOPIC\ntemas oscuros" in user.content
    assert "MEMORY" not in user.content
    assert "KNOWLEDGE" not in user.content
    assert result == _CANNED_MAP


async def test_missing_title_header_warns_without_raising(caplog) -> None:
    service, _, _, _ = _service(
        llm=FakeLLM(content="## Conceptos\n\nNada.\n"), hits=[]
    )

    with caplog.at_level(logging.WARNING, logger="knowledge_map_service"):
        result = await service.knowledge_map("redes")

    assert result == "## Conceptos\n\nNada.\n"
    assert any(
        record.getMessage() == "knowledge map output is missing the title header"
        for record in caplog.records
    )


async def test_knowledge_map_passes_project_id_and_top_k_to_retrieval() -> None:
    service, _, retrieval, _ = _service(hits=[])

    await service.knowledge_map("redes", project_id="proj-7", top_k=3)

    assert retrieval.calls[0]["project_id"] == "proj-7"
    assert retrieval.calls[0]["top_k"] == 3