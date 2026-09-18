"""Unit tests for ResearchService: the full §21 flow with offline fakes.

No network: the LLM, the search provider, and page extraction are all fakes
(``extract_page_text`` is monkeypatched at the service module), and persistence
runs against the shared in-memory SQLite + tmp vault stack from ``fakes.py``.
"""

from __future__ import annotations

from datetime import UTC

import pytest

from app.core.config import Settings
from app.providers.llm.base import LLMProviderError, LLMResult
from app.providers.search.base import SearchError, SearchHit, domain_of_url
from app.services.research_service import ResearchError, ResearchService
from tests.unit.fakes import build_stack

_CANNED_REPORT = (
    "# Objetivo\n\nResponder qué es asyncio.\n\n"
    "# Resumen\n\nResumen breve de los hallazgos.\n\n"
    "# Hallazgos\n\n1. Hallazgo principal [1].\n"
    "2. Segundo hallazgo [2].\n\n"
    "# Contradicciones detectadas\n\nNinguna contradicción entre fuentes.\n\n"
    "# Conclusión\n\nConclusión final.\n\n"
    "# Fuentes\n\n1. Python docs — https://docs.python.org/3/ (consultado 2026-09-18)\n"
)

EXTRACTED = "Contenido extraído de la página con trafilatura."

DOCS = SearchHit(
    title="Python docs",
    url="https://docs.python.org/3/library/asyncio.html",
    snippet="snippet docs",
    domain=domain_of_url("https://docs.python.org/3/library/asyncio.html"),
)
STACK = SearchHit(
    title="Stack Overflow",
    url="https://stackoverflow.com/questions/1/asyncio",
    snippet="snippet stack",
    domain=domain_of_url("https://stackoverflow.com/questions/1/asyncio"),
)
MEDIUM = SearchHit(
    title="Medium post",
    url="https://medium.com/@writer/asyncio",
    snippet="snippet medium",
    domain=domain_of_url("https://medium.com/@writer/asyncio"),
)
REDDIT = SearchHit(
    title="Reddit thread",
    url="https://www.reddit.com/r/Python/comments/x/",
    snippet="snippet reddit",
    domain=domain_of_url("https://www.reddit.com/r/Python/comments/x/"),
)
UNKNOWN = SearchHit(
    title="Example org",
    url="https://example.org/page",
    snippet="snippet unknown",
    domain=domain_of_url("https://example.org/page"),
)
BAD_JS = SearchHit(
    title="Bad JS url", url="javascript:alert(1)", snippet="x", domain=""
)
BAD_NO_SCHEME = SearchHit(
    title="No scheme", url="not a url", snippet="x", domain=""
)


class FakeLLM:
    """Canned query-planning and report-writing LLM; records every call."""

    name = "fake-research-llm"

    def __init__(
        self,
        *,
        queries: str = '["consulta uno", "consulta dos"]',
        report: str = _CANNED_REPORT,
        raise_interpret: bool = False,
        raise_synthesize: bool = False,
    ) -> None:
        self.queries = queries
        self.report = report
        self.raise_interpret = raise_interpret
        self.raise_synthesize = raise_synthesize
        self.calls: list[list] = []

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        system = messages[0].content
        if self.raise_interpret and "Spanish search queries" in system:
            raise LLMProviderError("llm timeout during interpretation")
        if self.raise_synthesize and "research writer" in system:
            raise LLMProviderError("llm timeout during synthesis")
        self.calls.append(list(messages))
        if "Spanish search queries" in system:
            content = self.queries
        else:
            content = self.report
        return LLMResult(
            content=content,
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-research-llm",
            model="test-model",
        )


class FakeSearch:
    """Canned hits keyed by query; records the queries and limits."""

    name = "fake-search"

    def __init__(self, hits_by_query: dict[str, list[SearchHit]], *, fail_on: str | None = None) -> None:
        self.hits_by_query = hits_by_query
        self.fail_on = fail_on
        self.queries: list[str] = []
        self.limits: list[int] = []

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        self.queries.append(query)
        self.limits.append(limit)
        if self.fail_on is not None and query == self.fail_on:
            raise SearchError("SearXNG request failed: connection refused")
        return self.hits_by_query.get(query, [])

    async def ping(self) -> bool:
        return True


def _patch_extract(monkeypatch, by_url: dict[str, str | None]) -> None:
    """Replace ``extract_page_text`` with a canned url -> text mapping."""

    async def fake_extract(url: str, *, client, **kwargs) -> str | None:
        return by_url.get(url)

    monkeypatch.setattr("app.services.research_service.extract_page_text", fake_extract)


def _make_service(
    db_session,
    tmp_path,
    *,
    llm: FakeLLM,
    search: FakeSearch,
    max_sources: int | None = None,
):
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, llm_model="test-model"
    )
    if max_sources is not None:
        settings = settings.model_copy(update={"research_max_sources": max_sources})
    ingestion, _, _, vault, documents, projects = build_stack(db_session, tmp_path)
    service = ResearchService(  # type: ignore[arg-type]
        llm,
        search,  # type: ignore[arg-type]
        vault=vault,
        ingestion=ingestion,
        settings=settings,
        projects=projects,
    )
    return service, documents, projects


def _service_without_stack(llm: FakeLLM, search: FakeSearch) -> ResearchService:
    """A service with no vault/ingestion: run() skips persistence."""
    return ResearchService(  # type: ignore[arg-type]
        llm,
        search,  # type: ignore[arg-type]
        vault=None,
        ingestion=None,
        settings=Settings(_env_file=None, llm_model="test-model"),  # type: ignore[call-arg]
    )


def _hits_for_two_queries() -> dict[str, list[SearchHit]]:
    # q2 re-delivers STACK (dedupe must keep the first occurrence) and adds
    # MEDIUM; bad URLs must be dropped, UNKNOWN stays (tier 0, ranked last).
    return {
        "consulta uno": [DOCS, STACK, REDDIT, BAD_JS, BAD_NO_SCHEME, UNKNOWN],
        "consulta dos": [STACK, MEDIUM],
    }


async def test_run_full_flow_and_persist(db_session, tmp_path, monkeypatch) -> None:
    llm = FakeLLM()
    search = FakeSearch(_hits_for_two_queries())
    _patch_extract(
        monkeypatch,
        {
            DOCS.url: EXTRACTED,
            STACK.url: EXTRACTED,
            MEDIUM.url: EXTRACTED,
            REDDIT.url: EXTRACTED,
            UNKNOWN.url: EXTRACTED,
        },
    )
    service, documents, _ = _make_service(db_session, tmp_path, llm=llm, search=search)

    result = await service.run("¿Qué es asyncio?", title="Informe asyncio")

    # interpret: one LLM call with the planner persona and the question.
    assert len(llm.calls) == 2
    assert llm.calls[0][0].role == "system"
    assert "Spanish search queries" in llm.calls[0][0].content
    assert llm.calls[0][1].content == "PREGUNTA\n¿Qué es asyncio?"

    # synthesize: research-writer persona + FUENTES/PREGUNTA block.
    assert "research writer" in llm.calls[1][0].content
    user = llm.calls[1][1].content
    assert user.startswith(
        f"FUENTES\n[1] Python docs | {DOCS.url}\n contenido: {EXTRACTED}"
    )
    assert f"[2] Stack Overflow | {STACK.url}\n contenido: {EXTRACTED}" in user
    assert "PREGUNTA\n¿Qué es asyncio?" in user

    # every query searched with limit 10.
    assert search.queries == ["consulta uno", "consulta dos"]
    assert search.limits == [10, 10]

    # dedupe (STACK once, first query wins), bad URLs dropped, rank order by
    # tier (docs 3, stack+medium 2, reddit 1, unknown 0) keeping ties stable.
    assert [s.url for s in result.sources] == [
        DOCS.url,
        STACK.url,
        MEDIUM.url,
        REDDIT.url,
        UNKNOWN.url,
    ]
    assert len(result.sources) == 5
    assert result.sources[0].retrieved_at.tzinfo is not None
    assert result.sources[0].retrieved_at.tzinfo == UTC

    assert result.title == "Informe asyncio"
    assert result.report == _CANNED_REPORT
    assert result.warnings is None

    # persist: report on disk under inbox + a document row, immediately.
    target = tmp_path / "vault" / "inbox" / "informe-asyncio.md"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == _CANNED_REPORT
    assert result.file_path == "inbox/informe-asyncio.md"
    assert result.document_id is not None
    persisted = await documents.get(result.document_id)
    assert persisted is not None
    assert persisted.content == _CANNED_REPORT
    assert persisted.source_type == "research"
    assert persisted.file_path == "inbox/informe-asyncio.md"


async def test_run_dedupes_by_url_first_wins(db_session, tmp_path, monkeypatch) -> None:
    # The same URL returns with a different title on the second query; the
    # first occurrence (query 1) must win.
    duplicate = SearchHit(
        title="Stack Overflow (second query)",
        url=STACK.url,
        snippet="other snippet",
        domain="stackoverflow.com",
    )
    search = FakeSearch(
        {"q1": [STACK], "q2": [duplicate, DOCS]},
    )
    _patch_extract(monkeypatch, {STACK.url: EXTRACTED, DOCS.url: EXTRACTED})
    llm = FakeLLM(queries='["q1", "q2"]')
    service, _, _ = _make_service(db_session, tmp_path, llm=llm, search=search)

    result = await service.run("p", title="t")

    # docs outranks stack overflow; the STACK URL appears once and keeps the
    # first-occurrence title (not the duplicate from query two).
    assert [s.url for s in result.sources] == [DOCS.url, STACK.url]
    assert result.sources[1].title == "Stack Overflow"


async def test_run_ranked_order_and_max_sources_param(db_session, tmp_path, monkeypatch) -> None:
    llm = FakeLLM()
    search = FakeSearch(_hits_for_two_queries())
    _patch_extract(
        monkeypatch,
        {DOCS.url: EXTRACTED, STACK.url: EXTRACTED, MEDIUM.url: EXTRACTED},
    )
    service, _, _ = _make_service(db_session, tmp_path, llm=llm, search=search)

    result = await service.run("¿Qué es asyncio?", title="Informe", max_sources=2)

    assert [s.url for s in result.sources] == [DOCS.url, STACK.url]


async def test_run_uses_settings_research_max_sources_by_default(
    db_session, tmp_path, monkeypatch
) -> None:
    llm = FakeLLM()
    search = FakeSearch(_hits_for_two_queries())
    _patch_extract(monkeypatch, {DOCS.url: EXTRACTED, STACK.url: EXTRACTED})
    service, _, _ = _make_service(
        db_session, tmp_path, llm=llm, search=search, max_sources=2
    )

    result = await service.run("p", title="t")

    assert [s.url for s in result.sources] == [DOCS.url, STACK.url]


async def test_snippet_fallback_when_extraction_fails(
    db_session, tmp_path, monkeypatch
) -> None:
    llm = FakeLLM(queries='["q"]')
    search = FakeSearch({"q": [DOCS, STACK]})
    # DOCS extracts fine; STACK fails -> its snippet feeds the report prompt.
    _patch_extract(monkeypatch, {DOCS.url: EXTRACTED})
    service, _, _ = _make_service(db_session, tmp_path, llm=llm, search=search)

    result = await service.run("p", title="t")

    user = llm.calls[1][1].content
    assert f" contenido: {EXTRACTED}" in user
    assert f" contenido: {STACK.snippet}" in user
    assert result.sources[1].snippet == STACK.snippet
    # The fallback does not raise and the run still persists.
    assert result.document_id is not None


async def test_missing_fuentes_warns_without_raising(
    db_session, tmp_path, monkeypatch
) -> None:
    report_without_fuentes = _CANNED_REPORT.split("# Fuentes")[0].strip() + "\n"
    llm = FakeLLM(queries='["q"]', report=report_without_fuentes)
    search = FakeSearch({"q": [DOCS]})
    _patch_extract(monkeypatch, {DOCS.url: EXTRACTED})
    service, _, _ = _make_service(db_session, tmp_path, llm=llm, search=search)

    result = await service.run("p", title="t")

    assert result.report == report_without_fuentes
    assert result.warnings == ["# Fuentes"]
    assert result.document_id is not None  # still persisted


async def test_run_persists_into_project_folder(db_session, tmp_path, monkeypatch) -> None:
    llm = FakeLLM(queries='["q"]')
    search = FakeSearch({"q": [DOCS]})
    _patch_extract(monkeypatch, {DOCS.url: EXTRACTED})
    service, _, projects = _make_service(db_session, tmp_path, llm=llm, search=search)
    project = await projects.create(name="Cloud Notes")

    result = await service.run("p", title="Informe final", project_id=project.id)

    target = tmp_path / "vault" / "cloud-notes" / "informe-final.md"
    assert target.exists()
    assert result.file_path == "cloud-notes/informe-final.md"
    assert result.document_id is not None


async def test_run_without_ingestion_returns_document_free(monkeypatch) -> None:
    llm = FakeLLM(queries='["q"]')
    search = FakeSearch({"q": [DOCS]})
    _patch_extract(monkeypatch, {DOCS.url: EXTRACTED})
    service = _service_without_stack(llm, search)

    result = await service.run("p", title="solo")

    assert result.document_id is None
    assert result.file_path is None
    assert result.report == _CANNED_REPORT
    assert result.warnings is None


async def test_interpret_parses_fenced_json() -> None:
    llm = FakeLLM(queries='```json\n["primera", "segunda"]\n```')
    search = FakeSearch({})
    service = _service_without_stack(llm, search)

    await service.run("p")

    assert search.queries == ["primera", "segunda"]


@pytest.mark.parametrize("raw", ["no tengo idea de qué devolver", "[]", '{"a": 1}'])
async def test_interpret_falls_back_to_the_question(raw: str) -> None:
    llm = FakeLLM(queries=raw)
    search = FakeSearch({})
    service = _service_without_stack(llm, search)

    await service.run("la pregunta clave")

    assert search.queries == ["la pregunta clave"]


async def test_search_error_raises_research_error() -> None:
    search = FakeSearch({}, fail_on="q")
    llm = FakeLLM(queries='["q"]')
    service = _service_without_stack(llm, search)

    with pytest.raises(ResearchError) as exc_info:
        await service.run("p")

    # The provider message is chained into ResearchError; no stack trace.
    assert "search failed" in str(exc_info.value)
    assert "connection refused" in str(exc_info.value)
    assert "Traceback" not in str(exc_info.value)


async def test_llm_interpret_error_raises_research_error() -> None:
    llm = FakeLLM(queries='["q"]', raise_interpret=True)
    search = FakeSearch({})
    service = _service_without_stack(llm, search)

    with pytest.raises(ResearchError) as exc_info:
        await service.run("p")

    assert "query interpretation failed" in str(exc_info.value)
    assert "llm timeout during interpretation" in str(exc_info.value)
    assert "Traceback" not in str(exc_info.value)


async def test_llm_synthesize_error_raises_research_error(monkeypatch) -> None:
    llm = FakeLLM(queries='["q"]', raise_synthesize=True)
    search = FakeSearch({"q": [DOCS]})
    _patch_extract(monkeypatch, {DOCS.url: EXTRACTED})
    service = _service_without_stack(llm, search)

    with pytest.raises(ResearchError) as exc_info:
        await service.run("p")

    assert "report synthesis failed" in str(exc_info.value)
    assert "llm timeout during synthesis" in str(exc_info.value)
    assert "Traceback" not in str(exc_info.value)


def test_default_title_equals_the_question_truncated() -> None:
    from app.services.research_service import _default_title

    assert _default_title("pregunta corta") == "pregunta corta"
    long_question = "una pregunta muy larga " * 6
    truncated = _default_title(long_question)
    assert len(truncated) <= 60
    assert truncated.endswith("…")