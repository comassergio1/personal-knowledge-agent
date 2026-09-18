"""Unit tests for LearnService: the Phase 7 learning loop, offline.

The loop is orchestration over existing services, so every dependency is a
fake that records its calls: retrieval supplies hits of configurable score,
research returns a canned ResearchResult, and tutorials generate/persist.
One test runs the real TutorialService over the shared in-memory DB + tmp
vault stack to prove the tutorial lands in the vault and the index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models.memory import Memory
from app.providers.llm.base import LLMResult
from app.schemas.memory import ConversationTurn
from app.services.learn_service import LearnError, LearnService
from app.services.research_service import ResearchResult
from app.services.tutorial_service import (
    TutorialResult,
    TutorialService,
    TutorialSource,
)
from app.vector.qdrant import SearchHit
from tests.unit.fakes import build_stack

_REFLECT_HINT = (
    "Respondé con lo que aprendiste/hiciste para guardarlo como memoria "
    "(POST /learn/reflect)."
)


def _hit(index: int, title: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=f"chunk-{index}",
        document_id=f"doc-{index}",
        title=title,
        content="contenido",
        score=score,
        metadata={},
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
                "project_id": project_id,
            }
        )
        return self.hits


class BoomRetrieval:
    """Retrieval that fails like an infra outage."""

    async def retrieve(self, query: str, **kwargs) -> list[SearchHit]:
        raise RuntimeError("vector store down")


class FakeResearch:
    """Returns a canned ResearchResult and records run arguments."""

    def __init__(self) -> None:
        self.result = ResearchResult(
            document_id="res-doc-1",
            title="Investigación",
            file_path="inbox/investigacion.md",
            report="# Objetivo\n\nHallazgos.\n",
            sources=[],
        )
        self.calls: list[dict] = []

    async def run(
        self,
        question: str,
        *,
        project_id: str | None = None,
        title: str | None = None,
        max_sources: int | None = None,
    ) -> ResearchResult:
        self.calls.append(
            {
                "question": question,
                "project_id": project_id,
                "title": title,
                "max_sources": max_sources,
            }
        )
        return self.result


class FakeMemory:
    """Returns canned candidates and records the conversation received."""

    def __init__(self) -> None:
        self.extracted: list[list[ConversationTurn]] = []

    async def extract(self, conversation: list[ConversationTurn]) -> list[Memory]:
        self.extracted.append(conversation)
        return [
            Memory(
                memory_type="semantic",
                content="aprendí docker compose",
                confidence=0.9,
                status="candidate",
            )
        ]


class _DocumentStub:
    """Minimal Document stand-in returned by the fake tutorial's persist."""

    def __init__(self, doc_id: str, file_path: str | None) -> None:
        self.id = doc_id
        self.file_path = file_path


class FakeTutorial:
    """Records generate/persist calls and returns canned results."""

    def __init__(self) -> None:
        self.result = TutorialResult(
            document_id=None,
            title="Tutorial",
            file_path=None,
            content="# Objetivo\n\nPasos.\n\n# Fuentes\n\n- [1] Nota A\n",
            sources=[TutorialSource(title="Nota A", score=0.9)],
        )
        self.document = _DocumentStub(doc_id="tut-doc-1", file_path="inbox/tutorial.md")
        self.generated: list[dict] = []
        self.persisted: list[dict] = []

    async def generate(
        self,
        objective: str,
        *,
        project_id: str | None = None,
        title: str | None = None,
        top_k: int = 6,
        mode: str = "do",
    ) -> TutorialResult:
        self.generated.append(
            {"objective": objective, "project_id": project_id, "title": title, "mode": mode}
        )
        return self.result

    async def persist(
        self,
        result: TutorialResult,
        *,
        project_id: str | None = None,
        title: str | None = None,
        source_type: str = "tutorial",
    ) -> _DocumentStub:
        self.persisted.append({"project_id": project_id, "title": title})
        return self.document


def _service(
    hits: list[SearchHit] | None = None,
    *,
    research: FakeResearch | None = None,
    memory: FakeMemory | None = None,
) -> tuple[
    LearnService, FakeRetrieval, FakeResearch | None, FakeTutorial, FakeMemory | None
]:
    retrieval = FakeRetrieval(hits)
    tutorials = FakeTutorial()
    service = LearnService(
        retrieval,  # type: ignore[arg-type]
        research,  # type: ignore[arg-type]
        tutorials,  # type: ignore[arg-type]
        memory,  # type: ignore[arg-type]
    )
    return service, retrieval, research, tutorials, memory


async def test_run_insufficient_knowledge_researches_and_persists_tutorial() -> None:
    service, retrieval, research, tutorials, _ = _service(
        hits=[], research=FakeResearch(), memory=FakeMemory()
    )

    result = await service.run("Docker para redes", title="Lab Docker")

    # Assess: empty hits -> insufficient knowledge.
    assert retrieval.calls[0] == {
        "query": "Docker para redes",
        "top_k": 5,
        "project_id": None,
    }
    assert result.needs_research is True
    # Research ran on demand.
    assert research is not None
    assert research.calls == [
        {
            "question": "Docker para redes",
            "project_id": None,
            "title": "Lab Docker",
            "max_sources": None,
        }
    ]
    assert result.research is not None
    assert result.research.document_id == "res-doc-1"
    assert result.research.file_path == "inbox/investigacion.md"
    # Tutorial generated with the requested mode and persisted.
    assert tutorials.generated == [
        {
            "objective": "Docker para redes",
            "project_id": None,
            "title": "Lab Docker",
            "mode": "learn",
        }
    ]
    assert tutorials.persisted == [{"project_id": None, "title": "Lab Docker"}]
    assert result.tutorial.document_id == "tut-doc-1"
    assert result.tutorial.file_path == "inbox/tutorial.md"
    assert result.tutorial.content == tutorials.result.content
    assert [(s.title, s.score) for s in result.tutorial.sources] == [("Nota A", 0.9)]
    # The result carries the loop metadata and the fixed reflect hint.
    assert result.goal == "Docker para redes"
    assert result.mode == "learn"
    assert result.reflect_hint == _REFLECT_HINT


async def test_run_low_score_below_threshold_still_researches() -> None:
    service, _, research, _, _ = _service(
        hits=[_hit(0, "Nota débil", 0.32)], research=FakeResearch(), memory=FakeMemory()
    )

    result = await service.run("VLANs", research_threshold=0.5)

    assert result.needs_research is True
    assert research is not None and len(research.calls) == 1


async def test_run_sufficient_knowledge_skips_research() -> None:
    service, _, research, _, _ = _service(
        hits=[_hit(0, "Nota fuerte", 0.88)], research=FakeResearch(), memory=FakeMemory()
    )

    result = await service.run("VLANs")

    assert result.needs_research is False
    assert research is not None and research.calls == []
    assert result.research is None


async def test_run_allow_research_false_skips_research_but_reports_gap() -> None:
    service, _, research, _, _ = _service(
        hits=[_hit(0, "Nota débil", 0.2)], research=FakeResearch(), memory=FakeMemory()
    )

    result = await service.run("VLANs", allow_research=False)

    assert result.needs_research is True
    assert research is not None and research.calls == []
    assert result.research is None


async def test_run_without_research_service_still_generates_tutorial() -> None:
    service, _, research, tutorials, _ = _service(hits=[], research=None)

    result = await service.run("VLANs")

    assert result.needs_research is True
    assert research is None
    assert result.research is None
    assert tutorials.persisted == [{"project_id": None, "title": None}]
    assert result.tutorial.document_id == "tut-doc-1"


async def test_run_passes_project_id_through_to_all_steps() -> None:
    service, retrieval, research, tutorials, _ = _service(
        hits=[],
        research=FakeResearch(),
        memory=FakeMemory(),
    )

    result = await service.run("VLANs", project_id="proj-7", mode="deep_learn")

    assert retrieval.calls[0]["project_id"] == "proj-7"
    assert research is not None
    assert research.calls[0]["project_id"] == "proj-7"
    assert tutorials.generated == [
        {
            "objective": "VLANs",
            "project_id": "proj-7",
            "title": None,
            "mode": "deep_learn",
        }
    ]
    assert tutorials.persisted == [{"project_id": "proj-7", "title": None}]
    assert result.mode == "deep_learn"


async def test_run_wraps_infrastructure_failures_in_learn_error() -> None:
    service = LearnService(
        BoomRetrieval(),  # type: ignore[arg-type]
        None,
        FakeTutorial(),  # type: ignore[arg-type]
        FakeMemory(),  # type: ignore[arg-type]
    )

    with pytest.raises(LearnError) as excinfo:
        await service.run("VLANs")

    assert "vector store down" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, RuntimeError)


async def test_reflect_builds_conversation_and_returns_candidates() -> None:
    service, _, _, _, memory = _service(memory=FakeMemory())

    candidates = await service.reflect("Docker", "aprendí a usar docker compose")

    assert memory is not None
    assert memory.extracted == [
        [
            ConversationTurn(role="user", content="Quiero aprender/hacer: Docker"),
            ConversationTurn(role="assistant", content="aprendí a usar docker compose"),
        ]
    ]
    assert len(candidates) == 1
    assert candidates[0].content == "aprendí docker compose"
    assert candidates[0].status == "candidate"


async def test_reflect_without_memory_service_raises_learn_error() -> None:
    service, _, _, _, _ = _service(memory=None)

    with pytest.raises(LearnError, match="reflection requires the memory service"):
        await service.reflect("Docker", "algo")


async def test_reflect_wraps_extractor_failures_in_learn_error() -> None:
    class BoomMemory:
        async def extract(self, conversation: list[ConversationTurn]) -> list[Memory]:
            raise RuntimeError("extractor offline")

    service = LearnService(
        FakeRetrieval(),  # type: ignore[arg-type]
        None,
        FakeTutorial(),  # type: ignore[arg-type]
        BoomMemory(),  # type: ignore[arg-type]
    )

    with pytest.raises(LearnError) as excinfo:
        await service.reflect("Docker", "algo")

    assert "extractor offline" in str(excinfo.value)


async def test_run_with_real_tutorial_stack_persists_into_vault(
    db_session, tmp_path: Path
) -> None:
    """The full loop with the real TutorialService: the tutorial lands on disk
    and in the index, and the refs echo the persisted document."""
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    ingestion, _, _, vault, documents, _ = build_stack(db_session, tmp_path)

    class RealLLM:
        name = "real-loop-llm"

        async def generate(
            self, messages, *, model: str | None = None, **kwargs
        ) -> LLMResult:
            return LLMResult(
                content="# Objetivo\n\nPasos.\n\n# Verificación\n\nOK.\n\n# Fuentes\n\n- [1] Nota\n",
                prompt_tokens=None,
                completion_tokens=None,
                provider="real-loop-llm",
                model="test-model",
            )

    retrieval = FakeRetrieval([_hit(0, "Nota débil", 0.3)])
    tutorials = TutorialService(  # type: ignore[arg-type]
        RealLLM(),
        retrieval,  # type: ignore[arg-type]
        memory=None,
        vault=vault,
        ingestion=ingestion,
        settings=settings,
    )
    research = FakeResearch()
    service = LearnService(
        retrieval,  # type: ignore[arg-type]
        research,  # type: ignore[arg-type]
        tutorials,
        FakeMemory(),  # type: ignore[arg-type]
    )

    result = await service.run("Lab Docker", title="Lab Docker")

    target = tmp_path / "vault" / "inbox" / "lab-docker.md"
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("# Objetivo")
    assert result.needs_research is True
    assert result.research is not None
    assert result.tutorial.file_path == "inbox/lab-docker.md"
    assert result.tutorial.document_id
    persisted = await documents.get(result.tutorial.document_id)
    assert persisted is not None
    assert persisted.file_path == "inbox/lab-docker.md"
    assert persisted.source_type == "tutorial"