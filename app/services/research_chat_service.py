"""Conversational web-research sessions: triggers, grounded chat, tutorials.

A research session ("Explorar" in the console) is a persisted thread. Each
user turn is handled two ways:

- **Explicit web trigger** — the message contains one of the curated
  ``RESEARCH_TRIGGERS`` (an explicit verb + location: "buscar en la web",
  "busca en internet", "buscá en internet", ...). The turn runs the full §21
  flow through ``ResearchService.run`` — the report is persisted into the
  vault by the service itself — and the assistant answers with a short
  Spanish summary of the report plus the vault ``file_path`` and sources
  (``kind="research"``, storing ``research_document_id``).
- **No trigger** — the turn is answered grounded in the vault, mirroring
  ``ChatService``'s prompt contract (``SYSTEM`` + ``MEMORY`` + ``KNOWLEDGE``
  + ``USER REQUEST``) but adding a ``HISTORY`` section with the session's
  prior turns so answers carry conversational context.

Trigger extraction rule
-----------------------
Matching mirrors ``research_intent``'s normalization: the message is
lowercased and every run of whitespace collapses to one space before the
substring match. ``detect_trigger`` returns the triggered phrase and
``extract_target`` removes its first occurrence and strips surrounding
separators (``:;,.!?·¿¡()[]"'—–-``) from the remainder.

False-positive risk (design, not a bug)
---------------------------------------
The triggers are **deliberately narrower** than ``research_intent``'s:
bare "en la web" / "en internet" or "buscá fuentes" (verb without an
explicit location) never fire here, so "¿qué dice mi nota en internet?"
stays grounded. Substring matching still has documented coarse corners: a
trigger inside a longer sentence fires and keeps the text around it as the
target (e.g. "¿podés buscar en la web y resumir la nota?" researches
"podés … y resumir la nota?"), and an imperative variant forms like
"busquemos en la web" are missed (no stemming), landing on the safe
grounded path. When the extracted target is empty the service falls back to
the session title, then to the last research topic seen in the thread.

The content language is Spanish (the user's product surface); code and
comments stay English (repo convention).
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Sequence

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.models.research_session import ResearchSession, ResearchTurn
from app.providers.llm.base import ChatMessage, LLMProvider
from app.providers.search.base import SearchProvider
from app.repositories.research_session_repository import ResearchSessionRepository
from app.repositories.usage_repository import UsageRepository
from app.services.chat_service import (
    _estimate_cost_usd,
)
from app.services.memory_service import MemoryService
from app.services.research_service import ResearchService
from app.services.retrieval_service import RetrievalService
from app.services.tutorial_service import TutorialResult, TutorialService
from app.vector.collections import CHUNK_INDEX_FIELD

# Curated, conservative web-research triggers: explicit verb + location only.
# Deliberately NOT the broad research_intent patterns ("en la web" alone,
# "buscá fuentes"): see the module docstring for the extraction rule and the
# documented false-positive risk. All copy below matches after the normalized
# lowercase/whitespace-collapsed message.
RESEARCH_TRIGGERS: tuple[str, ...] = (
    "buscar en la web",
    "busca en internet",
    "buscá en internet",
    "buscar en internet",
    "investigá en la web",
    "investiga en la web",
    "investigar en la web",
    "buscá en la web",
    "busca en la web",
)

# Any run of whitespace collapses to one space, so "buscá   en   la   web"
# matches "buscá en la web" after normalization (mirrors research_intent).
_WHITESPACE_RE = re.compile(r"\s+")

# Separators stripped from around an extracted target: whitespace plus common
# sentence punctuation and quotes, so "buscá en la web: asyncio?" → "asyncio".
_TARGET_STRIP_CHARS = " \t\n\r:;,.!?¿¡()[]\"'—–-"

_DEFAULT_SESSION_TITLE = "Sesión de investigación"
_EXCERPT_LENGTH = 200
_HISTORY_TURN_CHARS = 800
_GROUNDED_TOP_K = 5
_MEMORY_TOP_K = 3
_TUTORIAL_OBJECTIVE_FALLBACK = "Resumen de la sesión de investigación"

# Grounded-answer persona (spec §25 shape). The phrasing must not collide
# with the fake LLM's research markers in the offline testing app.
_SYSTEM_PROMPT = (
    "You are a research assistant inside a web-research session. Answer "
    "grounded in the provided knowledge. If the knowledge is insufficient, "
    "say so and never invent facts."
)


class SessionNotFoundError(Exception):
    """Raised when a research session id does not exist (route → 404)."""


class SearchUnavailableError(Exception):
    """Raised when the search provider cannot be reached (route → 503)."""


def detect_trigger(message: str) -> str | None:
    """Return the research trigger contained in ``message``, or None.

    The message is lowercased and whitespace-collapsed before the substring
    match; when several triggers match, the earliest occurrence wins (ties
    are impossible: no trigger is a prefix of another at the same position).
    """
    normalized = _WHITESPACE_RE.sub(" ", message).lower()
    best: tuple[int, int] | None = None
    best_trigger: str | None = None
    for trigger in RESEARCH_TRIGGERS:
        index = normalized.find(trigger)
        if index == -1:
            continue
        if best is None or (index, len(trigger)) < best:
            best = (index, len(trigger))
            best_trigger = trigger
    return best_trigger


def extract_target(message: str, trigger: str) -> str:
    """Return ``message`` with the ``trigger`` phrase removed.

    The first occurrence of the (normalized) trigger is removed and
    surrounding separators are stripped. Returns an empty string for a bare
    trigger ("buscá en la web" alone) — the service then falls back to the
    session's topic. Defensively returns "" when the trigger is absent.
    """
    normalized = _WHITESPACE_RE.sub(" ", message).lower()
    index = normalized.find(trigger)
    if index == -1:
        return ""
    # Removing the trigger can leave runs of whitespace around it ("contame,
    #  que..."), so the remainder is whitespace-collapsed again.
    remainder = _WHITESPACE_RE.sub(
        " ", normalized[:index] + normalized[index + len(trigger) :]
    )
    return remainder.strip(_TARGET_STRIP_CHARS)


def _summary_from_report(report: str, max_chars: int = 400) -> str:
    """Return a short summary for the assistant turn: the # Resumen section.

    When the report lacks a ``# Resumen`` heading the first non-heading
    paragraph becomes the summary, so the assistant always answers with
    something readable even for malformed LLM output.
    """
    lines = report.splitlines()
    summary: list[str] = []
    for index, line in enumerate(lines):
        if line.startswith("# Resumen"):
            for following in lines[index + 1 :]:
                if following.startswith("#"):
                    break
                if following.strip():
                    summary.append(following.strip())
            break
    text = " ".join(summary).strip()
    if not text:
        text = " ".join(
            line.strip()
            for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        )
    return text[:max_chars] if len(text) > max_chars else text


class ResearchChatService:
    """Orchestrates one research session: turns, research, and tutorials."""

    def __init__(
        self,
        llm: LLMProvider,
        retrieval: RetrievalService,
        research: ResearchService,
        tutorial: TutorialService,
        search: SearchProvider,
        settings: Settings,
        repository: ResearchSessionRepository,
        # Optional memory provider (spec §25); when set, approved memories are
        # injected as a MEMORY section ahead of the knowledge chunks, exactly
        # like ChatService. Optional usage logging too (spec §30).
        usage_repository: UsageRepository | None = None,
        memory: MemoryService | None = None,
    ) -> None:
        self._llm = llm
        self._retrieval = retrieval
        self._research = research
        self._tutorial = tutorial
        self._search = search
        self._settings = settings
        self._repository = repository
        self._usage_repository = usage_repository
        self._memory = memory
        self._logger = get_logger("research_chat_service")

    # -- session lifecycle ---------------------------------------------------

    async def create_session(self, title: str | None = None) -> ResearchSession:
        """Create a session; a missing/empty title gets the Spanish default."""
        resolved = (title or "").strip() or _DEFAULT_SESSION_TITLE
        return await self._repository.create_session(resolved)

    async def list_sessions(self) -> list[tuple[ResearchSession, int]]:
        """Return sessions (newest activity first) with their turn counts."""
        sessions = await self._repository.list()
        return [
            (session, await self._repository.count_turns(session.id))
            for session in sessions
        ]

    async def get_session(self, session_id: str) -> ResearchSession | None:
        """Return one session row or None."""
        return await self._repository.get_session(session_id)

    async def turns(self, session_id: str) -> Sequence[ResearchTurn]:
        """Return the session's turns in thread order."""
        return await self._repository.list_turns(session_id)

    # -- turn handling -------------------------------------------------------

    async def add_turn(self, session_id: str, message: str) -> ResearchTurn:
        """Persist the user message and answer it (research or grounded).

        Raises ``SessionNotFoundError`` for an unknown session,
        ``SearchUnavailableError`` when the search provider cannot be reached
        and ``ResearchError``/``LLMProviderError`` for infra failures.
        """
        session = await self._repository.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        await self._repository.add_turn(
            session_id, role="user", content=message, kind="answer"
        )
        trigger = detect_trigger(message)
        self._logger.info(
            "research session turn",
            extra={
                "session_id": session_id,
                "trigger": trigger,
                "research": trigger is not None,
            },
        )
        if trigger is None:
            return await self._grounded_turn(session_id, message)
        return await self._research_turn(session_id, trigger)

    async def _grounded_turn(self, session_id: str, message: str) -> ResearchTurn:
        """Answer from the vault: SYSTEM + MEMORY + KNOWLEDGE + HISTORY + USER.

        Mirrors ``ChatService.chat`` (retrieval, approved memories, usage
        logging, SourceRef-shaped sources) but adds the session's HISTORY.
        """
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        hits = await self._retrieval.retrieve(message, top_k=_GROUNDED_TOP_K)

        memories: list[str] = []
        if self._memory is not None:
            memories = await self._memory.search_approved(message, top_k=_MEMORY_TOP_K)

        memory_block = ""
        if memories:
            memory_block = (
                "MEMORY\n" + "\n".join(f"- {item}" for item in memories) + "\n\n"
            )
        history_block = self._history_block(await self._repository.list_turns(session_id))

        if hits:
            knowledge = "\n".join(
                f"[{index + 1}] ({hit.title}) {hit.content}"
                for index, hit in enumerate(hits)
            )
            user_content = (
                f"{memory_block}{history_block}KNOWLEDGE\n{knowledge}\n\n"
                f"USER REQUEST\n{message}"
            )
        else:
            user_content = f"{memory_block}{history_block}USER REQUEST\n{message}"

        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ]
        result = await self._llm.generate(messages=messages, model=None)
        answer = result.content

        sources = [
            {
                "document_id": hit.document_id,
                "title": hit.title,
                "chunk_index": int(hit.metadata.get(CHUNK_INDEX_FIELD, 0)),
                "score": hit.score,
                "excerpt": hit.content[:_EXCERPT_LENGTH],
            }
            for hit in hits
        ]

        if self._usage_repository is not None:
            await self._usage_repository.create(
                request_id=request_id,
                provider=result.provider,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                estimated_cost_usd=_estimate_cost_usd(
                    provider=result.provider,
                    settings=self._settings,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                ),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        self._logger.info(
            "research session grounded answer",
            extra={
                "session_id": session_id,
                "retrieved_chunks": len(hits),
                "memory_chunks": len(memories),
                "answer_length": len(answer),
            },
        )
        return await self._repository.add_turn(
            session_id,
            role="assistant",
            content=answer,
            kind="answer",
            sources=sources,
        )

    async def _research_turn(self, session_id: str, trigger: str) -> ResearchTurn:
        """Run the §21 flow and persist an assistant summary turn.

        The SearXNG instance is probed first (503 semantics), then the target
        resolves (message minus the trigger, else the session topic) and
        ``ResearchService.run`` persists the report into the vault.
        """
        if not await self._search.ping():
            raise SearchUnavailableError()
        target = await self._resolve_target(session_id, trigger)
        # A fresh session adopts its first real topic as the title, so later
        # bare triggers ("buscá en la web") fall back to a meaningful topic.
        session = await self._repository.get_session(session_id)
        if session is not None and session.title == _DEFAULT_SESSION_TITLE:
            await self._repository.update_title(session_id, target)

        result = await self._research.run(target, project_id=None, title=None)
        summary = _summary_from_report(result.report) or (
            "Se generó el informe de investigación; "
            "abrí el archivo en el vault para leerlo."
        )
        lines = [
            f"Resultado de la investigación sobre **{target}**:",
            "",
            summary,
            "",
            f"Informe completo guardado en el vault: `{result.file_path or '—'}`.",
            "",
            "Fuentes:",
        ]
        for index, source in enumerate(result.sources, start=1):
            lines.append(f"{index}. {source.title} — {source.url}")
        sources = [
            {"title": source.title, "url": source.url, "domain": source.domain}
            for source in result.sources
        ]
        return await self._repository.add_turn(
            session_id,
            role="assistant",
            content="\n".join(lines),
            kind="research",
            research_document_id=result.document_id,
            sources=sources,
        )

    async def _resolve_target(self, session_id: str, trigger: str) -> str:
        """Resolve the research target: message minus trigger, else the topic.

        An empty extracted target falls back to the session title when it is
        meaningful (a real topic, not the generic default), then to the last
        research topic seen in the thread; the last resort is the title text
        itself. ``trigger`` is passed in so callers only pay for one match.
        """
        message = (await self._repository.list_turns(session_id))[-1].content
        target = extract_target(message, trigger)
        if target:
            return target
        session = await self._repository.get_session(session_id)
        title = (session.title if session is not None else "").strip()
        if title and title != _DEFAULT_SESSION_TITLE:
            return title
        for turn in reversed(await self._repository.list_turns(session_id)):
            if turn.role != "user":
                continue
            prior_trigger = detect_trigger(turn.content)
            if prior_trigger is None:
                continue
            candidate = extract_target(turn.content, prior_trigger)
            if candidate:
                return candidate
        return title or _DEFAULT_SESSION_TITLE

    @staticmethod
    def _history_block(turns: Sequence[ResearchTurn]) -> str:
        """Render the HISTORY prompt section from the thread's prior turns.

        The last element is the just-persisted user message (it becomes the
        USER REQUEST), so it is excluded; each turn's content is truncated to
        bound the prompt size.
        """
        prior = list(turns)[:-1]
        if not prior:
            return ""
        lines = []
        for turn in prior:
            label = "User" if turn.role == "user" else "Assistant"
            lines.append(f"{label}: {turn.content[:_HISTORY_TURN_CHARS]}")
        return "HISTORY\n" + "\n".join(lines) + "\n\n"

    # -- tutorial ------------------------------------------------------------

    async def save_tutorial(self, session_id: str, mode: str) -> TutorialResult:
        """Generate and persist a tutorial over the session's topic.

        The tutorial objective is the session's topic (its title, which the
        first research turn adopts); retrieval already sees the persisted
        research reports because ``ResearchService.run`` ingests them, so the
        tutorial is grounded on the session's research. ``persist`` writes
        the markdown into the vault and indexes it immediately.
        """
        session = await self._repository.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        objective = (
            session.title.strip()
            if session.title.strip() and session.title != _DEFAULT_SESSION_TITLE
            else _TUTORIAL_OBJECTIVE_FALLBACK
        )
        result = await self._tutorial.generate(
            objective, project_id=None, title=None, mode=mode
        )
        await self._tutorial.persist(result, project_id=None, title=None)
        return result