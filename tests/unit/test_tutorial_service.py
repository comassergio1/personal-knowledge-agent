"""Unit tests for TutorialService.generate (fakes, no network)."""

from __future__ import annotations

from app.core.config import Settings
from app.providers.llm.base import LLMResult
from app.services.tutorial_service import TutorialService
from app.vector.qdrant import SearchHit

_CANNED_TUTORIAL = """# Objetivo

Crear un tutorial.

# Prerrequisitos

Ninguno.

# Materiales

Ordenador.

# Paso 1

Abrir.

# Verificación

Comprobar.

# Troubleshooting

Reiniciar.

# Errores comunes

Saltarse el paso 1.

# Rollback

Deshacer.

# Fuentes

- [1] Nota A
"""


class FakeLLM:
    """Records the messages passed to ``generate`` and returns a canned tutorial."""

    name = "fake-tutorial-llm"

    def __init__(self, content: str | None = None) -> None:
        self.messages: list | None = None
        self.content = content if content is not None else _CANNED_TUTORIAL

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        self.messages = list(messages)
        return LLMResult(
            content=self.content,
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-tutorial-llm",
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
    """Returns canned approved-memory contents and records queries."""

    def __init__(self, memories: list[str] | None = None) -> None:
        self.memories = memories if memories is not None else []
        self.queries: list[str] = []

    async def search_approved(self, query: str, top_k: int = 3) -> list[str]:
        self.queries.append(query)
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
    memory: FakeMemory | None = None,
    *,
    memories: list[str] | None = None,
) -> tuple[TutorialService, FakeLLM, FakeRetrieval, FakeMemory | None]:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    fake_llm = llm if llm is not None else FakeLLM()
    retrieval = FakeRetrieval(hits)
    fake_memory = memory if memory is not None else FakeMemory(memories or [])
    service = TutorialService(
        fake_llm,  # type: ignore[arg-type]
        retrieval,  # type: ignore[arg-type]
        fake_memory,  # type: ignore[arg-type]
        vault=None,
        ingestion=None,
        settings=settings,
    )
    return service, fake_llm, retrieval, fake_memory


async def test_generate_builds_prompt_with_memory_and_knowledge_and_returns_sources() -> None:
    hits = [
        _hit(0, "Nota A", "contenido alpha", 0.91),
        _hit(3, "Nota B", "contenido beta", 0.77),
    ]
    service, llm, retrieval, memory = _service(hits=hits, memories=["Preferencia: pasos cortos"])

    result = await service.generate("Escribe un tutorial", top_k=6)

    assert retrieval.calls == [
        {
            "query": "Escribe un tutorial",
            "top_k": 6,
            "document_id": None,
            "project_id": None,
            "score_threshold": None,
        }
    ]
    assert memory.queries == ["Escribe un tutorial"]
    assert llm.messages is not None
    assert len(llm.messages) == 2
    system, user = llm.messages
    assert system.role == "system"
    assert "SPANISH" in system.content
    assert "# Objetivo" in system.content
    assert "# Fuentes" in system.content
    assert user.role == "user"
    assert "MEMORY\n- Preferencia: pasos cortos\n\nKNOWLEDGE" in user.content
    assert "[1] (Nota A) contenido alpha" in user.content
    assert "[2] (Nota B) contenido beta" in user.content
    assert "USER REQUEST\nEscribe un tutorial" in user.content

    assert result.content == _CANNED_TUTORIAL
    assert result.title == "Escribe un tutorial"
    assert result.document_id is None
    assert result.file_path is None
    assert result.warnings is None
    assert [(s.title, s.score) for s in result.sources] == [
        ("Nota A", 0.91),
        ("Nota B", 0.77),
    ]


async def test_generate_passes_project_id_to_retrieval() -> None:
    service, _, retrieval, _ = _service(hits=[])

    await service.generate("solo mi proyecto", project_id="proj-7")

    assert retrieval.calls[0]["project_id"] == "proj-7"


async def test_generate_omits_memory_section_when_memory_service_is_none() -> None:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    llm = FakeLLM()
    retrieval = FakeRetrieval([_hit(0, "Nota A", "contenido alpha", 0.9)])
    service = TutorialService(  # type: ignore[arg-type]
        llm, retrieval, memory=None, vault=None, ingestion=None, settings=settings
    )

    result = await service.generate("algo")

    assert llm.messages is not None
    user = llm.messages[1]
    assert "MEMORY" not in user.content
    assert "KNOWLEDGE" in user.content
    assert result.warnings is None


async def test_generate_omits_memory_section_when_search_returns_empty() -> None:
    service, llm, _, _ = _service(hits=[_hit(0, "Nota A", "x", 0.9)], memories=[])

    await service.generate("algo")

    assert llm.messages is not None
    user = llm.messages[1]
    assert "MEMORY" not in user.content
    assert "KNOWLEDGE" in user.content


async def test_generate_keeps_memory_when_there_are_no_knowledge_hits() -> None:
    service, llm, _, _ = _service(hits=[], memories=["Prefiere ejemplos"])

    await service.generate("algo")

    assert llm.messages is not None
    user = llm.messages[1]
    assert "MEMORY\n- Prefiere ejemplos\n\nUSER REQUEST\nalgo" in user.content
    assert "KNOWLEDGE" not in user.content


async def test_generate_with_no_memory_and_no_hits_is_plain_user_request() -> None:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    llm = FakeLLM()
    service = TutorialService(  # type: ignore[arg-type]
        llm, FakeRetrieval([]), memory=None, vault=None, ingestion=None, settings=settings
    )

    await service.generate("algo")

    assert llm.messages is not None
    user = llm.messages[1]
    assert user.content == "USER REQUEST\nalgo"
    assert "MEMORY" not in user.content
    assert "KNOWLEDGE" not in user.content


async def test_generate_warns_without_raising_when_fuentes_missing() -> None:
    no_fuentes = _CANNED_TUTORIAL.split("# Fuentes")[0].strip() + "\n"
    service, _, _, _ = _service(llm=FakeLLM(content=no_fuentes), hits=[])

    result = await service.generate("algo")

    assert result.content == no_fuentes
    assert result.warnings == ["# Fuentes"]


async def test_generate_warns_for_both_missing_headers_without_raising() -> None:
    service, _, _, _ = _service(
        llm=FakeLLM(content="# Rollback\n\nDeshacer.\n"), hits=[]
    )

    result = await service.generate("algo")

    assert result.warnings == ["# Objetivo", "# Fuentes"]


async def test_generate_default_title_is_the_objective_truncated() -> None:
    short = "Escribe un tutorial"
    service, _, _, _ = _service(hits=[])
    assert (await service.generate(short)).title == short

    long_objective = "un objetivo largo " * 6  # 102 chars
    service, _, _, _ = _service(hits=[])
    truncated = (await service.generate(long_objective)).title
    assert len(truncated) <= 60
    assert truncated.startswith(long_objective[:20])
    assert truncated.endswith("…")


async def test_generate_explicit_title_beats_the_default() -> None:
    service, _, _, _ = _service(hits=[])

    result = await service.generate("algo", title="Mi tutorial")

    assert result.title == "Mi tutorial"