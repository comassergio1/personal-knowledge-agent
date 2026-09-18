"""Tutorial generation: grounded Spanish tutorials with the spec §20 structure.

The service mirrors ``ChatService``'s prompt contract (spec §25: ``SYSTEM`` +
``MEMORY`` + ``KNOWLEDGE`` + ``USER REQUEST``) but for LLM-authored
tutorials: the objective is embedded to retrieve top-k knowledge chunks and
approved memories, and the LLM writes a markdown tutorial following the §20
header structure. The content language is Spanish because the user's
knowledge and tutorials are Spanish; code and comments stay English.

``generate`` is pure (never writes to the vault or the index); ``persist``
writes the markdown into the vault and ingests it immediately, so the
tutorial is searchable (and visible in Obsidian) without a manual sync.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.models.document import Document
from app.providers.llm.base import ChatMessage, LLMProvider
from app.repositories.project_repository import ProjectRepository
from app.services.ingestion_service import INBOX, IngestionService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.services.vault_service import VaultService

_MAX_TITLE_LENGTH = 60
_MEMORY_TOP_K = 5

# Tutorial-writer persona and the §20 structure contract. All headers are
# emitted verbatim in Spanish, the tutorial's content language.
_SYSTEM_PROMPT = (
    "You are a technical tutorial writer. Write a step-by-step tutorial in "
    "SPANISH that follows exactly these markdown headers: # Objetivo, "
    "# Prerrequisitos, # Materiales, # Paso 1, # Paso 2, ..., # Verificación, "
    "# Troubleshooting, # Errores comunes, # Rollback, # Fuentes. Base the "
    "tutorial ONLY on the provided knowledge and memories; when the provided "
    "knowledge is insufficient, say so inside the tutorial and never invent "
    "facts. Adapt the style to the user preferences described in the MEMORY "
    "section."
)


@dataclass
class TutorialSource:
    """One source the tutorial was grounded in."""

    title: str
    score: float


@dataclass
class TutorialResult:
    """A generated tutorial plus the sources it was grounded in."""

    document_id: str | None
    title: str
    file_path: str | None
    content: str
    sources: list[TutorialSource]
    warnings: list[str] | None = None


class TutorialService:
    """Generates grounded tutorials and persists them to the vault + index."""

    def __init__(
        self,
        llm: LLMProvider,
        retrieval: RetrievalService,
        memory: MemoryService | None,
        vault: VaultService | None,
        ingestion: IngestionService | None,
        settings: Settings,
        # Required to resolve the vault folder for a ``project_id`` the same
        # way ``IngestionService`` does (project name, else ``inbox``).
        projects: ProjectRepository | None = None,
    ) -> None:
        self._llm = llm
        self._retrieval = retrieval
        self._memory = memory
        self._vault = vault
        self._ingestion = ingestion
        self._settings = settings
        self._projects = projects
        self._logger = get_logger("tutorial_service")

    async def generate(
        self,
        objective: str,
        *,
        project_id: str | None = None,
        title: str | None = None,
        top_k: int = 6,
    ) -> TutorialResult:
        """Generate a grounded Spanish tutorial for ``objective``.

        The objective is embedded and searched against the top-k knowledge
        chunks (scoped to ``project_id`` when given) plus the top approved
        memories. The prompt follows the spec §25 pattern with a SYSTEM
        tutorial-writer persona, OPTIONAL MEMORY and KNOWLEDGE sections (each
        included only when non-empty), and the USER REQUEST. A light post-check
        warns — never raises — when ``# Objetivo`` or ``# Fuentes`` is missing
        from the LLM output.

        This method is pure: call :meth:`persist` to write the tutorial into
        the vault and the index.
        """
        hits = await self._retrieval.retrieve(
            objective, top_k=top_k, project_id=project_id
        )

        memories: list[str] = []
        if self._memory is not None:
            memories = await self._memory.search_approved(objective, top_k=_MEMORY_TOP_K)

        memory_block = ""
        if memories:
            memory_block = (
                "MEMORY\n" + "\n".join(f"- {item}" for item in memories) + "\n\n"
            )

        knowledge_block = ""
        if hits:
            knowledge = "\n".join(
                f"[{index + 1}] ({hit.title}) {hit.content}"
                for index, hit in enumerate(hits)
            )
            knowledge_block = f"KNOWLEDGE\n{knowledge}\n\n"

        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=f"{memory_block}{knowledge_block}USER REQUEST\n{objective}",
            ),
        ]
        result = await self._llm.generate(messages=messages, model=None)
        markdown = result.content

        # Light post-check: warn (never fail) when the LLM skipped a required
        # §20 section; the tutorial is still returned unfiltered.
        warnings = [
            header
            for header in ("# Objetivo", "# Fuentes")
            if header not in markdown
        ]
        for header in warnings:
            self._logger.warning(
                "tutorial output is missing a required header",
                extra={"header": header, "objective": objective},
            )
        self._logger.info(
            "tutorial generated",
            extra={
                "provider": self._llm.name,
                "model": self._settings.llm_model,
                "retrieved_chunks": len(hits),
                "memory_chunks": len(memories),
                "content_length": len(markdown),
                "warnings": warnings,
            },
        )

        return TutorialResult(
            document_id=None,
            title=title or _default_title(objective),
            file_path=None,
            content=markdown,
            sources=[TutorialSource(title=hit.title, score=hit.score) for hit in hits],
            warnings=warnings or None,
        )

    async def persist(
        self,
        result: TutorialResult,
        *,
        project_id: str | None = None,
        title: str | None = None,
        source_type: str = "tutorial",
    ) -> Document:
        """Write the tutorial into the vault and index it immediately.

        When a vault is configured the markdown is written under the project
        folder (``inbox`` when there is no project, matching ingestion's
        folder semantics) and the resulting ``file_path`` is passed to
        ``ingest`` so the row records it: a later ``POST /vault/sync`` sees no
        change. Without a vault the tutorial is ingested file-less. The
        returned document's id/path are also stored back on ``result``.
        """
        if self._ingestion is None:
            raise ValueError("an IngestionService is required to persist a tutorial")

        resolved_title = title or result.title
        file_path: str | None = None
        if self._vault is not None:
            project_name = await self._project_name(project_id)
            target = self._vault.markdown_path(project_name, resolved_title)
            self._vault.write_text(target, result.content)
            file_path = self._vault.relative_path(target)

        document = await self._ingestion.ingest(
            title=resolved_title,
            content=result.content,
            mime_type="text/markdown",
            source_type=source_type,
            project_id=project_id,
            file_path=file_path,
        )
        result.document_id = document.id
        result.file_path = document.file_path
        return document

    async def _project_name(self, project_id: str | None) -> str:
        """Return the project's name, or ``INBOX`` when there is no project."""
        if project_id is None or self._projects is None:
            return INBOX
        project = await self._projects.get_by_id(project_id)
        return project.name if project is not None else INBOX


def _default_title(objective: str) -> str:
    """Return ``objective`` as the default tutorial title, truncated."""
    if len(objective) <= _MAX_TITLE_LENGTH:
        return objective
    return objective[: _MAX_TITLE_LENGTH - 1].rstrip() + "…"