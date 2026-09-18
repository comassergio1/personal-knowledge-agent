"""Unit tests for the Phase 7 tutorial depth modes (captured prompts, offline).

Each test captures the SYSTEM prompt the service sends to a fake LLM and
asserts the mode block selected by ``generate(..., mode=...)``: ``do`` stays
minimal (no per-step rationale, no exercises), ``learn`` adds prerequisites
and the '¿Por qué hacemos esto?' rationale, and ``deep_learn`` adds exercises,
a summary, and theory emphasis. The default mode is ``do``, keeping the
pre-Phase-7 contract.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.providers.llm.base import LLMResult
from app.schemas.tutorial import TutorialRead, TutorialRequest
from app.services.tutorial_service import TutorialService
from app.vector.qdrant import SearchHit

_RATIONALE = "¿Por qué hacemos esto?"
_EXERCISES = "# Ejercicios"

_CANNED_TUTORIAL = "# Objetivo\n\nCrear.\n\n# Verificación\n\nComprobar.\n\n# Fuentes\n\n- [1] Nota A\n"


class FakeLLM:
    """Records the prompt messages and returns a canned tutorial."""

    name = "fake-modes-llm"

    def __init__(self) -> None:
        self.system_content: str | None = None

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        self.system_content = messages[0].content
        return LLMResult(
            content=_CANNED_TUTORIAL,
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-modes-llm",
            model="test-model",
        )


class EmptyRetrieval:
    """Returns no hits; asserts nothing beyond the service contract."""

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_id: str | None = None,
        project_id: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        return []


def _service() -> tuple[TutorialService, FakeLLM]:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    llm = FakeLLM()
    service = TutorialService(  # type: ignore[arg-type]
        llm,
        EmptyRetrieval(),  # type: ignore[arg-type]
        memory=None,
        vault=None,
        ingestion=None,
        settings=settings,
    )
    return service, llm


async def test_do_mode_prompt_is_minimal_and_defaults_to_do() -> None:
    service, llm = _service()

    result = await service.generate("Configura una VLAN")

    assert result.mode == "do"
    assert llm.system_content is not None
    # Base §20 persona text stays; the mode block is appended.
    assert "# Objetivo" in llm.system_content
    assert "# Fuentes" in llm.system_content
    # Depth-1 structure only: no rationale, no exercises, no theory sections.
    assert _RATIONALE not in llm.system_content
    assert _EXERCISES not in llm.system_content
    assert "# Conceptos previos" not in llm.system_content
    assert "# Materiales" in llm.system_content
    assert "# Rollback" in llm.system_content


async def test_omitted_mode_uses_the_same_prompt_as_explicit_do() -> None:
    explicit, llm_explicit = _service()
    implicit, llm_implicit = _service()

    await explicit.generate("algo", mode="do")
    await implicit.generate("algo")

    assert llm_implicit.system_content == llm_explicit.system_content


async def test_learn_mode_prompt_adds_prerequisites_and_per_step_rationale() -> None:
    service, llm = _service()

    result = await service.generate("Configura una VLAN", mode="learn")

    assert result.mode == "learn"
    assert llm.system_content is not None
    assert "# Conceptos previos" in llm.system_content
    assert "# Preparación" in llm.system_content
    assert _RATIONALE in llm.system_content
    # Exercises belong to deep_learn only.
    assert _EXERCISES not in llm.system_content


async def test_deep_learn_mode_prompt_has_exercises_summary_and_theory_emphasis() -> None:
    service, llm = _service()

    result = await service.generate("Redes", mode="deep_learn")

    assert result.mode == "deep_learn"
    assert llm.system_content is not None
    assert _EXERCISES in llm.system_content
    assert "# Resumen" in llm.system_content
    # The deep mode must explain foundational concepts (e.g. 802.1Q,
    # tagging, trunk/access) before the steps.
    assert "foundational concepts" in llm.system_content
    assert "802.1Q" in llm.system_content
    assert "trunk/access" in llm.system_content
    assert "# Conceptos previos" in llm.system_content
    assert _RATIONALE in llm.system_content


async def test_unknown_mode_is_rejected_before_any_llm_call() -> None:
    service, llm = _service()

    with pytest.raises(ValueError, match="unknown tutorial mode"):
        await service.generate("algo", mode="meta_aprender")

    assert llm.system_content is None


async def test_result_mode_round_trips_through_tutorial_read() -> None:
    service, _ = _service()

    for mode in ("do", "learn", "deep_learn"):
        result = await service.generate("algo", mode=mode)
        read = TutorialRead(  # type: ignore[call-arg]
            document_id=None,
            title="algo",
            file_path=None,
            content=result.content,
            mode=result.mode,
        )
        assert read.mode == mode


async def test_deep_learn_generated_tutorial_still_post_checks_objetivo_fuentes() -> None:
    # The §20 post-check is mode-independent: it warns (never raises) when the
    # LLM output skips # Objetivo or # Fuentes, even in deep_learn mode.
    service, _llm = _service()
    result = await service.generate("algo", mode="deep_learn")

    assert result.warnings is None  # _CANNED_TUTORIAL carries both headers


def test_request_schema_defaults_to_do_and_validates_modes() -> None:
    assert TutorialRequest(objective="algo").mode == "do"
    assert TutorialRequest(objective="algo", mode="learn").mode == "learn"
    with pytest.raises(ValidationError):
        TutorialRequest(objective="algo", mode="guess")  # type: ignore[arg-type]