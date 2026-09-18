"""Learning-loop orchestration: assess → research on demand → tutorial (Phase 7).

The learning loop ("La idea central" of the new spec) reuses the existing
retrieval, research, tutorial, and memory services; it adds no new providers
or dependencies and never writes outside those services. ``run`` first
measures how much the vault already knows about the goal (retrieval score vs
``research_threshold``), optionally fills the gap with the research agent, and
then generates a mode-aware tutorial. ``reflect`` turns a "¿qué aprendí?"
exchange into candidate memories through the standard memory extractor.

Both methods are pure orchestration: every side effect happens inside the
delegated services (research report, tutorial vault write, and memory
candidates), and failures surface as ``LearnError`` with message chaining —
never raw stack traces.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.domain.models.memory import Memory
from app.schemas.memory import ConversationTurn
from app.services.memory_service import MemoryService
from app.services.research_service import ResearchService
from app.services.retrieval_service import RetrievalService
from app.services.tutorial_service import TutorialService, TutorialSource

_MAX_TITLE_LENGTH = 60

# Fixed hint returned with every LearnResult; the API routes (unit 5) only
# echo it. Spanish because it is user-facing copy.
_REFLECT_HINT = (
    "Respondé con lo que aprendiste/hiciste para guardarlo como memoria "
    "(POST /learn/reflect)."
)


class LearnError(Exception):
    """Raised when a learning-loop step fails (routes map to 502)."""


@dataclass
class ResearchRef:
    """The research report persisted during the loop, when one ran."""

    document_id: str | None
    file_path: str | None


@dataclass
class TutorialRef:
    """The persisted tutorial: vault document ref plus its markdown content."""

    document_id: str | None
    file_path: str | None
    content: str
    sources: list[TutorialSource]


@dataclass
class LearnResult:
    """Outcome of a learning-loop run."""

    goal: str
    mode: str
    needs_research: bool
    research: ResearchRef | None
    tutorial: TutorialRef
    reflect_hint: str = _REFLECT_HINT


class LearnService:
    """Coordinates retrieval, research, tutorials, and memory for the loop."""

    def __init__(
        self,
        retrieval: RetrievalService,
        research: ResearchService | None,
        tutorials: TutorialService,
        memory: MemoryService | None,
    ) -> None:
        self._retrieval = retrieval
        self._research = research
        self._tutorials = tutorials
        self._memory = memory
        self._logger = get_logger("learn_service")

    async def run(
        self,
        goal: str,
        *,
        mode: str = "learn",
        project_id: str | None = None,
        title: str | None = None,
        allow_research: bool = True,
        research_threshold: float = 0.5,
        top_k: int = 5,
    ) -> LearnResult:
        """Run assess → research on demand → generate, returning the tutorial.

        ``needs_research`` is True when retrieval returns no hits or its best
        score is below ``research_threshold``. When the knowledge is
        insufficient, ``allow_research`` is true and a research service is
        configured, the research agent runs first. Note that
        ``ResearchService.run`` already persists its report into the vault and
        the index, so the tutorial generation's own retrieval will see it (no
        extra steps); retrieval is expected to be re-run inside
        ``tutorials.generate`` anyway. When research is unavailable or
        disabled, ``research`` stays None and the tutorial is still generated
        from whatever the vault already knows.
        """
        try:
            hits = await self._retrieval.retrieve(
                goal, top_k=top_k, project_id=project_id
            )
            needs_research = (not hits) or (
                max(hit.score for hit in hits) < research_threshold
            )

            research_ref: ResearchRef | None = None
            if needs_research and allow_research and self._research is not None:
                research = await self._research.run(
                    goal,
                    project_id=project_id,
                    title=(title or goal)[:_MAX_TITLE_LENGTH],
                )
                research_ref = ResearchRef(
                    document_id=research.document_id,
                    file_path=research.file_path,
                )

            result = await self._tutorials.generate(
                goal, mode=mode, project_id=project_id, title=title
            )
            tutorial_doc = await self._tutorials.persist(
                result, project_id=project_id, title=title
            )
            tutorial_ref = TutorialRef(
                document_id=tutorial_doc.id,
                file_path=tutorial_doc.file_path,
                content=result.content,
                sources=[
                    TutorialSource(title=source.title, score=source.score)
                    for source in result.sources
                ],
            )
        except LearnError:
            raise
        except Exception as exc:
            raise LearnError(f"learning loop failed: {exc}") from exc

        self._logger.info(
            "learning loop completed",
            extra={
                "goal": goal,
                "mode": mode,
                "needs_research": needs_research,
                "research": research_ref is not None,
                "tutorial_document": tutorial_ref.document_id,
            },
        )
        return LearnResult(
            goal=goal,
            mode=mode,
            needs_research=needs_research,
            research=research_ref,
            tutorial=tutorial_ref,
        )

    async def reflect(
        self,
        goal: str,
        what_i_learned: str,
        *,
        project_id: str | None = None,
    ) -> list[Memory]:
        """Turn a "qué aprendí?" exchange into candidate memories.

        A short user/assistant conversation is built and handed to the memory
        extractor through ``MemoryService.extract``, which persists the
        candidates (redacted, status candidate). ``project_id`` is accepted
        for API symmetry but the extractor is project-agnostic, so it is not
        forwarded. Reflection requires the memory service; without it (for
        example in a minimal deployment) this raises ``LearnError``.
        """
        if self._memory is None:
            raise LearnError("reflection requires the memory service")
        conversation = [
            ConversationTurn(role="user", content=f"Quiero aprender/hacer: {goal}"),
            ConversationTurn(role="assistant", content=what_i_learned),
        ]
        try:
            return await self._memory.extract(conversation)
        except LearnError:
            raise
        except Exception as exc:
            raise LearnError(f"memory reflection failed: {exc}") from exc
