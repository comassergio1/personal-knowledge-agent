"""Web research orchestration: interpret, search, rank, extract, synthesize (spec §21).

``ResearchService.run`` drives the full §21 flow: the LLM turns the question
into 2–4 Spanish search queries, every query goes through the configured
``SearchProvider`` (SearXNG today), hits are deduped by URL and ranked by a
source-quality heuristic, the top sources are fetched and stripped of chrome
with ``trafilatura`` (snippet fallback), and the LLM writes a Spanish markdown
report following the §21 structure. The report is then persisted into the
vault and ingested immediately, mirroring ``TutorialService.persist``.

The report content language is Spanish (the user's knowledge and spec §21);
code and comments stay English. Search, LLM, and ingestion infrastructure
failures surface as ``ResearchError`` with message chaining — never raw stack
traces — so routes can answer 502 while the app stays healthy.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.models.document import Document
from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError
from app.providers.search.base import SearchError, SearchHit, SearchProvider
from app.repositories.project_repository import ProjectRepository
from app.services.ingestion_service import INBOX, IngestionService
from app.services.research_extraction import extract_page_text
from app.services.vault_service import VaultService

_MAX_TITLE_LENGTH = 60
_FETCH_DELAY_SECONDS = 0.3
_CONTENT_CHARS = 3_000

# Search-query planner persona: the question becomes 2-4 independent Spanish
# queries (the SearXNG instance is configured for Spanish, spec §21).
_INTERPRET_SYSTEM_PROMPT = (
    "You are a research assistant that plans web searches. Turn the user's "
    "research question into 2 to 4 short, independent Spanish search queries, "
    "even when the question is in another language. Return ONLY a JSON array "
    "of strings with the queries, e.g. [\"consulta 1\", \"consulta 2\"]; "
    "never add any other text."
)

# Research-writer persona: the §21 report structure, emitted verbatim in
# Spanish. Every claim must cite its source as [n] against the # Fuentes list.
_SYNTHESIZE_SYSTEM_PROMPT = (
    "You are a rigorous research writer. Write a markdown research report in "
    "SPANISH that follows exactly these headers: # Objetivo, # Resumen, "
    "# Hallazgos, # Contradicciones detectadas, # Conclusión, # Fuentes. In "
    "# Hallazgos number each finding and cite the source for EVERY claim as "
    "[n], where n is the position of the source in the # Fuentes list. In "
    "# Contradicciones detectadas explicitly flag when two sources disagree. "
    "In # Fuentes list every consulted source as a numbered list with the "
    "format: title — URL (consultado <date>). Never invent facts or sources; "
    "when the provided material is insufficient to answer, say so inside the "
    "report."
)

# Strips ```json ... ``` fences (with or without the language tag); the same
# lenient pattern the memory extractor uses for LLM JSON.
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass
class ResearchSource:
    """One source consulted for a research report (search hit + retrieval time)."""

    title: str
    url: str
    domain: str
    snippet: str
    retrieved_at: datetime


@dataclass
class ResearchResult:
    """A completed research report plus its consulted sources and document refs."""

    document_id: str | None
    title: str
    file_path: str | None
    report: str
    sources: list[ResearchSource]
    warnings: list[str] | None = None


class ResearchError(Exception):
    """Raised when search, LLM, or ingestion infrastructure fails (§21, 502)."""


def source_quality(url: str) -> int:
    """Return a heuristic quality tier for ``url``: 3 best, 0 worst.

    Official documentation sites score 3 (docs./learn./developers. hosts,
    GitHub, ReadTheDocs, W3C, Mozilla, kernel.org, Wikipedia); mainstream
    technology media score 2 (Stack Overflow, dev.to, Medium, Blogger,
    Wired, Ars Technica, The Verge, How-To Geek, and a few common peers);
    community/forums score 1 (Reddit, forums.*, Quora, Stack Exchange);
    anything else scores 0. Malformed or non-http(s) URLs score 0, which the
    ranking step uses to drop them outright.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return 0
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return 0
    host = parsed.hostname.lower()
    if _is_official_docs(host):
        return 3
    if _is_mainstream_tech(host):
        return 2
    if _is_community(host):
        return 1
    return 0


def _host_matches(host: str, *, exact: tuple[str, ...] = (), suffix: tuple[str, ...] = ()) -> bool:
    """Match ``host`` against exact hosts and/or ``.<domain>`` suffixes."""
    return host in exact or any(host.endswith(f".{domain}") for domain in suffix)


def _is_official_docs(host: str) -> bool:
    return (
        host.startswith(("docs.", "learn.", "developers."))
        or _host_matches(
            host,
            exact=(
                "github.com",
                "wikipedia.org",
                "readthedocs.io",
                "w3.org",
                "mozilla.org",
                "kernel.org",
            ),
            suffix=("github.com", "readthedocs.io", "w3.org", "mozilla.org", "kernel.org", "wikipedia.org"),
        )
    )


def _is_mainstream_tech(host: str) -> bool:
    return (
        "blogspot" in host
        or _host_matches(
            host,
            exact=(
                "stackoverflow.com",
                "dev.to",
                "medium.com",
                "wired.com",
                "arstechnica.com",
                "theverge.com",
                "howtogeek.com",
                "realpython.com",
                "geeksforgeeks.org",
                "freecodecamp.org",
                "digitalocean.com",
                "towardsdatascience.com",
            ),
            suffix=(
                "stackoverflow.com",
                "dev.to",
                "medium.com",
                "wired.com",
                "arstechnica.com",
                "theverge.com",
                "howtogeek.com",
                "realpython.com",
                "geeksforgeeks.org",
                "freecodecamp.org",
                "digitalocean.com",
                "towardsdatascience.com",
            ),
        )
    )


def _is_community(host: str) -> bool:
    return (
        host.startswith("forums.")
        or _host_matches(
            host,
            exact=("reddit.com", "quora.com", "stackexchange.com"),
            suffix=("reddit.com", "quora.com", "stackexchange.com"),
        )
    )


def _is_usable_url(url: str) -> bool:
    """True when ``url`` is an http(s) URL with a host (usable for fetching)."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def _parse_queries(raw: str, fallback: str) -> list[str]:
    """Leniently parse the LLM reply into a non-empty list of query strings.

    Code fences are stripped and the first ``[``/last ``]`` pair is parsed;
    when anything fails the caller falls back to the whole question as a
    single query — LLM JSON output is unreliable, exactly like the memory
    extractor's parsing.
    """
    text = _FENCE_RE.sub("", raw).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        values = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    queries = [item.strip() for item in values if isinstance(item, str) and item.strip()]
    return queries


class ResearchService:
    """Runs the §21 research flow and persists the report into knowledge."""

    def __init__(
        self,
        llm: LLMProvider,
        search: SearchProvider,
        vault: VaultService | None,
        ingestion: IngestionService | None,
        settings: Settings,
        # Required to resolve the vault folder for a ``project_id`` (project
        # name, else ``inbox``), mirroring ``IngestionService``.
        projects: ProjectRepository | None = None,
    ) -> None:
        self._llm = llm
        self._search = search
        self._vault = vault
        self._ingestion = ingestion
        self._settings = settings
        self._projects = projects
        self._client = httpx.AsyncClient()  # page fetches for extraction
        self._logger = get_logger("research_service")

    async def close(self) -> None:
        """Close the extraction client and the search provider."""
        await self._client.aclose()
        await self._search.close()

    async def run(
        self,
        question: str,
        *,
        project_id: str | None = None,
        title: str | None = None,
        max_sources: int | None = None,
    ) -> ResearchResult:
        """Run interpret → search → dedupe → rank → extract → synthesize → persist.

        Returns the report metadata; the report itself is written into the
        vault (when configured) and ingested immediately (when an ingestion
        service is available), so it becomes searchable and Obsidian-visible
        without a manual sync. Without an ingestion service the result is
        returned file-less and document-free.
        """
        queries = await self._interpret(question)
        self._logger.info(
            "research flow started",
            extra={"queries": queries, "llm": self._llm.name},
        )
        hits = await self._search_all(queries)
        limit = (
            max_sources if max_sources is not None else self._settings.research_max_sources
        )
        ranked = self._rank(hits, limit=limit)
        extracted = await self._extract(ranked)
        markdown, warnings = await self._synthesize(question, extracted)

        result = ResearchResult(
            document_id=None,
            title=title or _default_title(question),
            file_path=None,
            report=markdown,
            sources=[source for source, _content in extracted],
            warnings=warnings or None,
        )
        if self._ingestion is not None:
            try:
                await self.persist(result, project_id=project_id, title=title)
            except Exception as exc:  # infra failures chain into ResearchError
                raise ResearchError(f"research report persistence failed: {exc}") from exc
        return result

    async def persist(
        self,
        result: ResearchResult,
        *,
        project_id: str | None = None,
        title: str | None = None,
        source_type: str = "research",
    ) -> Document:
        """Write the report into the vault and index it immediately.

        Mirrors ``TutorialService.persist``: the markdown lands under the
        project folder (``inbox`` without a project) and the resulting
        ``file_path`` is passed to ``ingest`` so the row records it and a
        later ``POST /vault/sync`` sees no change. Without a vault the report
        is ingested file-less. The returned document's id/path are stored
        back on ``result``.
        """
        if self._ingestion is None:
            raise ValueError("an IngestionService is required to persist a research report")

        resolved_title = title or result.title
        file_path: str | None = None
        if self._vault is not None:
            project_name = await self._project_name(project_id)
            target = self._vault.markdown_path(project_name, resolved_title)
            self._vault.write_text(target, result.report)
            file_path = self._vault.relative_path(target)

        document = await self._ingestion.ingest(
            title=resolved_title,
            content=result.report,
            mime_type="text/markdown",
            source_type=source_type,
            project_id=project_id,
            file_path=file_path,
        )
        result.document_id = document.id
        result.file_path = document.file_path
        return document

    async def _interpret(self, question: str) -> list[str]:
        """Ask the LLM for 2–4 Spanish search queries; fall back to the question."""
        messages = [
            ChatMessage(role="system", content=_INTERPRET_SYSTEM_PROMPT),
            ChatMessage(role="user", content=f"PREGUNTA\n{question}"),
        ]
        try:
            result = await self._llm.generate(messages=messages, model=None)
        except LLMProviderError as exc:
            raise ResearchError(f"query interpretation failed: {exc}") from exc
        return _parse_queries(result.content, fallback=question) or [question]

    async def _search_all(self, queries: list[str]) -> list[SearchHit]:
        """Search every query, deduping hits by URL (first occurrence wins)."""
        deduped: list[SearchHit] = []
        seen: set[str] = set()
        for query in queries:
            try:
                hits = await self._search.search(query, limit=10)
            except SearchError as exc:
                raise ResearchError(f"search failed: {exc}") from exc
            for hit in hits:
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                deduped.append(hit)
        return deduped

    def _rank(self, hits: list[SearchHit], *, limit: int) -> list[SearchHit]:
        """Drop unusable URLs, order by quality tier, keep the top ``limit``.

        Unknown-but-valid http(s) sites keep tier 0 and participate (they just
        rank last); only URLs with no scheme or a non-http(s) scheme are
        dropped outright. ``list.sort`` is stable, so ties keep their original
        search order.
        """
        candidates = [hit for hit in hits if _is_usable_url(hit.url)]
        candidates.sort(key=lambda hit: source_quality(hit.url), reverse=True)
        return candidates[:limit]

    async def _extract(self, hits: list[SearchHit]) -> list[tuple[ResearchSource, str]]:
        """Fetch each ranked hit (0.3s between fetches), snippet as fallback.

        Extraction is best-effort by design: any failure yields the search
        snippet, never a raised error, so a single dead page cannot sink an
        entire research run.
        """
        extracted: list[tuple[ResearchSource, str]] = []
        for index, hit in enumerate(hits):
            if index > 0:
                await asyncio.sleep(_FETCH_DELAY_SECONDS)
            text = await self._extract_text(hit.url)
            extracted.append(
                (
                    ResearchSource(
                        title=hit.title,
                        url=hit.url,
                        domain=hit.domain,
                        snippet=hit.snippet,
                        retrieved_at=datetime.now(UTC),
                    ),
                    text or hit.snippet,
                )
            )
        return extracted

    async def _extract_text(self, url: str) -> str | None:
        """Return the page's main text; None on any failure (snippet fallback)."""
        try:
            return await extract_page_text(url, client=self._client)
        except Exception as exc:  # noqa: BLE001  best-effort extraction never raises
            self._logger.debug("page extraction failed for %s: %s", url, exc)
            return None

    async def _synthesize(self, question: str, extracted) -> tuple[str, list[str]]:
        """Ask the LLM for the §21 Spanish report; post-check # Fuentes."""
        user = self._sources_block(extracted, question)
        messages = [
            ChatMessage(role="system", content=_SYNTHESIZE_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user),
        ]
        try:
            result = await self._llm.generate(messages=messages, model=None)
        except LLMProviderError as exc:
            raise ResearchError(f"report synthesis failed: {exc}") from exc

        markdown = result.content
        warnings = ["# Fuentes"] if "# Fuentes" not in markdown else []
        if warnings:
            self._logger.warning(
                "research report is missing a required header",
                extra={"header": warnings[0], "question": question},
            )
        return markdown, warnings

    @staticmethod
    def _sources_block(extracted, question: str) -> str:
        """Render the FUENTES … PREGUNTA prompt block (each source ≤ 3000 chars)."""
        lines = ["FUENTES"]
        for index, (source, content) in enumerate(extracted, start=1):
            lines.append(f"[{index}] {source.title} | {source.url}")
            lines.append(f" contenido: {content[:_CONTENT_CHARS]}")
        lines.append("")
        lines.append("PREGUNTA")
        lines.append(question)
        return "\n".join(lines)

    async def _project_name(self, project_id: str | None) -> str:
        """Return the project's name, or ``INBOX`` when there is no project."""
        if project_id is None or self._projects is None:
            return INBOX
        project = await self._projects.get_by_id(project_id)
        return project.name if project is not None else INBOX


def _default_title(question: str) -> str:
    """Return ``question`` as the default report title, truncated."""
    if len(question) <= _MAX_TITLE_LENGTH:
        return question
    return question[: _MAX_TITLE_LENGTH - 1].rstrip() + "…"