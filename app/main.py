"""FastAPI application factory: wiring, lifespan, and router mounting.

The factory is the single place that constructs application components; it
owns their lifetime through the lifespan hook and stores them on
``app.state``. Routers receive everything through dependencies, so no module
leaks globals. When ``testing=True`` the network-touching components (LLM,
embeddings, vector store) are replaced by in-memory fakes so the app runs
fully offline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.api.routes.chat import router as chat_router
from app.api.routes.documents import router as documents_router
from app.api.routes.evals import router as evals_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.learn import router as learn_router
from app.api.routes.memories import router as memories_router
from app.api.routes.projects import router as projects_router
from app.api.routes.research import router as research_router
from app.api.routes.sync import router as sync_router
from app.api.routes.tutorials import router as tutorials_router
from app.api.routes.usage import router as usage_router
from app.api.routes.v1_compat import router as v1_compat_router
from app.core.config import Settings, get_settings
from app.core.logging import get_logger, setup_logging
from app.database import create_app_engine
from app.domain.models import Base
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.factory import EmbeddingProviderFactory
from app.providers.llm.base import LLMProvider, LLMResult
from app.providers.llm.factory import LLMProviderFactory
from app.providers.search.base import SearchHit as GatewaySearchHit
from app.providers.search.base import SearchProvider
from app.providers.search.factory import SearchProviderFactory
from app.repositories.document_repository import DocumentRepository
from app.repositories.eval_repository import EvalRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.usage_repository import UsageRepository
from app.services.chat_service import ChatService
from app.services.eval_metrics import JUDGE_PROMPT_MARKER
from app.services.eval_service import EvalService
from app.services.ingestion_service import IngestionService
from app.services.knowledge_map import KnowledgeMapService
from app.services.learn_service import LearnService
from app.services.memory_extractor import MemoryExtractor
from app.services.memory_service import MemoryService
from app.services.research_service import ResearchService
from app.services.retrieval_service import RetrievalService
from app.services.sync_service import SyncService
from app.services.tutorial_service import TutorialService
from app.services.vault_service import VaultService
from app.vector.collections import (
    CHUNK_ID_FIELD,
    CONTENT_FIELD,
    DOCUMENT_ID_FIELD,
    MEMORIES_COLLECTION,
    METADATA_FIELD,
    PROJECT_ID_FIELD,
    TITLE_FIELD,
)
from app.vector.qdrant import QdrantVectorStore, SearchHit, VectorPoint

APP_TITLE = "Personal Knowledge Agent"
APP_VERSION = "0.1.0"

# Own console (feature: own-console): the zero-dependency static SPA lives in
# the package and is served by the app itself — no build step, no CDN, so it
# works offline inside the LAN compose stack.
_STATIC_DIR = Path(__file__).resolve().parent / "static"

_console_router = APIRouter()


@_console_router.get("/", include_in_schema=False)
async def console_index() -> FileResponse:
    """Serve the own-console single-page app (feature: own-console)."""
    return FileResponse(_STATIC_DIR / "index.html")

_logger = get_logger("application")


# Marker in the extractor's system prompt; the fake LLM answers extraction
# prompts with a canned candidate array so the testing app stays offline.
_EXTRACTOR_MARKER = "Output ONLY a JSON array"

# Research markers (spec §21): distinguish the query-planner prompt from the
# report-writer prompt so the fake LLM can answer each with canned content.
_RESEARCH_INTERPRET_MARKER = "Spanish search queries"
_RESEARCH_SYNTHESIZE_MARKER = "research writer"

_CANNED_RESEARCH_INTERPRETATION = '["\u00bfqu\u00e9 es asyncio?", "tutorial de asyncio"]'

# The canned report omits the # Fuentes header on purpose so the post-check
# fires during integration tests, exercising the warnings path end to end.
_CANNED_RESEARCH_REPORT = (
    "# Objetivo\n\nResponder la pregunta.\n\n"
    "# Resumen\n\nResumen breve de los hallazgos.\n\n"
    "# Hallazgos\n\n1. Hallazgo principal [1].\n\n"
    "# Contradicciones detectadas\n\nNinguna.\n\n"
    "# Conclusi\u00f3n\n\nConclusi\u00f3n.\n"
)


class _FakeLLM(LLMProvider):
    """Canned-answer LLM used when ``testing=True`` (no network).

    Memory-extraction prompts get a canned candidate array (containing a
    secret, so redaction is exercised); research prompts get a canned
    interpretation and a canned Spanish report; judge prompts (eval) get a
    canned rubric JSON; everything else gets a canned chat answer.
    """

    name = "fake-llm"

    async def generate(
        self, messages: list, *, model: str | None = None, **kwargs
    ) -> LLMResult:
        joined = "\n".join(m.content for m in messages)
        if _EXTRACTOR_MARKER in joined:
            content = (
                '[{"type": "preference", "content": "User prefers concise '
                'answers (account password=hunter2)", "confidence": 0.9, '
                '"source": "conversation"}]'
            )
        elif _RESEARCH_INTERPRET_MARKER in joined:
            content = _CANNED_RESEARCH_INTERPRETATION
        elif _RESEARCH_SYNTHESIZE_MARKER in joined:
            content = _CANNED_RESEARCH_REPORT
        elif JUDGE_PROMPT_MARKER in joined:
            # One frozen rubric that clears the default thresholds for normal
            # cases AND adversarial ones (challenged_premise true), keeping
            # the offline eval flow green without per-case fake logic.
            content = (
                '{"correctness": 0.9, "relevance": 0.8, "groundedness": 0.8, '
                '"hallucination_claims": [], "challenged_premise": true}'
            )
        else:
            content = "This is a fake grounded answer."
        return LLMResult(
            content=content,
            prompt_tokens=0,
            completion_tokens=0,
            provider="fake-llm",
            model="fake",
        )

    async def close(self) -> None:
        return None


class _FakeEmbeddings(EmbeddingProvider):
    """Fixed-size embedding provider used when ``testing=True`` (no network)."""

    EMBEDDING_SIZE = 768

    def __init__(self, size: int) -> None:
        self.EMBEDDING_SIZE = size

    async def embed(self, text: str) -> list[float]:
        width = self.EMBEDDING_SIZE
        return [1.0 / width] * width

    async def close(self) -> None:
        return None


class _FakeVectorStore:
    """In-memory vector store used when ``testing=True`` (no network)."""

    def __init__(self) -> None:
        self._points: list[VectorPoint] = []
        self.deleted_documents: list[str] = []

    async def ensure_collection(self, size: int) -> None:
        return None

    async def upsert_chunks(self, points: list[VectorPoint]) -> None:
        self._points.extend(points)

    async def search(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        document_id: str | None = None,
        project_id: str | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        # Defensive ``.get()`` mirrors the real store, so memory points (which
        # carry memory payload fields, not chunk ones) never KeyError.
        hits: list[SearchHit] = []
        for point in self._points:
            payload = point.payload
            if document_id is not None and payload.get(DOCUMENT_ID_FIELD) != document_id:
                continue
            if project_id is not None and payload.get(PROJECT_ID_FIELD) != project_id:
                continue
            hits.append(
                SearchHit(
                    chunk_id=payload.get(CHUNK_ID_FIELD, str(point.id)),
                    document_id=payload.get(DOCUMENT_ID_FIELD, ""),
                    title=payload.get(TITLE_FIELD, ""),
                    content=payload.get(CONTENT_FIELD, ""),
                    score=0.9,
                    metadata=payload.get(METADATA_FIELD, {}) or {},
                )
            )
        return hits[:top_k]

    async def delete_by_field(self, field: str, value: str) -> None:
        self._points = [
            point
            for point in self._points
            if point.payload.get(field) != value
        ]

    async def delete_by_document(self, document_id: str) -> None:
        self.deleted_documents.append(document_id)
        self._points = [
            point
            for point in self._points
            if point.payload[DOCUMENT_ID_FIELD] != document_id
        ]

    async def close(self) -> None:
        return None


# Canned search hits with mixed-quality domains for the offline research
# endpoint: docs (tier 3), Stack Overflow + Medium (tier 2), Reddit (tier 1)
# so ranking is observable in tests without a real SearXNG instance.
_CANNED_SEARCH_HITS = [
    GatewaySearchHit(
        title="asyncio — Asynchronous I/O",
        url="https://docs.python.org/3/library/asyncio.html",
        snippet="Infrastructure for writing single-threaded concurrent code.",
        domain="docs.python.org",
    ),
    GatewaySearchHit(
        title="asyncio question on Stack Overflow",
        url="https://stackoverflow.com/questions/1234/asyncio",
        snippet="Top answer on asyncio internals.",
        domain="stackoverflow.com",
    ),
    GatewaySearchHit(
        title="Understanding asyncio",
        url="https://medium.com/@writer/asyncio-guide",
        snippet="A practical guide about asyncio.",
        domain="medium.com",
    ),
    GatewaySearchHit(
        title="asyncio discussion",
        url="https://www.reddit.com/r/Python/comments/abc/asyncio/",
        snippet="A reddit thread about asyncio.",
        domain="www.reddit.com",
    ),
]


class _FakeSearchProvider:
    """Canned search results used when ``testing=True`` (no network)."""

    name = "fake-search"

    async def ping(self) -> bool:
        """The fake instance always answers; tests swap it for the 503 case."""
        return True

    async def search(self, query: str, *, limit: int = 10) -> list[GatewaySearchHit]:
        return _CANNED_SEARCH_HITS[:limit]

    async def close(self) -> None:
        return None


def _fake_extract_page_text(
    url: str, *, client, timeout: float = 15.0, max_chars: int = 20_000
) -> str | None:
    """Offline stand-in for ``extract_page_text`` when ``testing=True``.

    Returns ``None`` so the research flow falls back to the canned search
    snippets — no network and no trafilatura in tests.
    """
    return None


def _build_engine(settings: Settings) -> AsyncEngine:
    """Build the app-scoped async engine, honoring in-memory SQLite tests."""
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
        return create_async_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    if url.get_backend_name() == "sqlite":
        Path(url.database or ".").expanduser().resolve().parent.mkdir(
            parents=True, exist_ok=True
        )
    return create_app_engine(settings.database_url)


async def _close_resource(resource: object) -> None:
    """Call ``async close()`` when the resource exposes it."""
    close = getattr(resource, "close", None)
    if close is not None:
        await close()


def _make_lifespan(
    settings: Settings, *, testing: bool
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = _build_engine(settings)
        session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )

        if testing:
            embeddings: EmbeddingProvider = _FakeEmbeddings(
                settings.embedding_dimensions
            )
            vector_store = _FakeVectorStore()
            # Memories get their own in-memory store so document points and
            # memory points never mix, mirroring the production split.
            memory_store = _FakeVectorStore()
            llm: LLMProvider = _FakeLLM()
            search_provider: SearchProvider = _FakeSearchProvider()
            # Page extraction is a module function, so the offline seam swaps
            # the binding itself (canned snippets become the fallback text).
            import app.services.research_service as research_service_module

            research_service_module.extract_page_text = _fake_extract_page_text
        else:
            embeddings = EmbeddingProviderFactory.create(
                settings.embedding_provider, settings
            )
            vector_store = QdrantVectorStore(url=settings.qdrant_url)
            memory_store = QdrantVectorStore(
                url=settings.qdrant_url, collection=MEMORIES_COLLECTION
            )
            llm = LLMProviderFactory.create(settings.llm_provider, settings)
            search_provider = SearchProviderFactory.create(
                settings.search_provider, settings
            )
        await vector_store.ensure_collection(settings.embedding_dimensions)
        await memory_store.ensure_collection(settings.embedding_dimensions)
        # Dev/test fallback; Alembic remains the canonical schema manager.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # The repository is bound to its own session for the app lifetime;
        # request-scoped sessions (``get_db``) cover route-level queries.
        vault_service = VaultService(settings.vault_path)
        ingestion_session = session_factory()
        document_repository = DocumentRepository(ingestion_session)
        project_repository = ProjectRepository(ingestion_session)
        usage_session = session_factory()
        usage_repository = UsageRepository(usage_session)
        memory_session = session_factory()
        memory_repository = MemoryRepository(memory_session)
        memory_extractor = MemoryExtractor(llm)
        memory_service = MemoryService(
            memory_repository,
            memory_store,
            embeddings,
            vault=vault_service,
            extractor=memory_extractor,
        )
        retrieval_service = RetrievalService(vector_store, embeddings)
        chat_service = ChatService(
            llm, retrieval_service, settings, usage_repository, memory=memory_service
        )

        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.vector_store = vector_store
        app.state.embeddings = embeddings
        app.state.llm = llm
        app.state.document_repository = document_repository
        app.state.vault_service = vault_service
        app.state.ingestion_service = IngestionService(
            document_repository,
            vector_store,
            embeddings,
            vault=vault_service,
            projects=project_repository,
        )
        app.state.sync_service = SyncService(
            vault_service,
            document_repository,
            project_repository,
            app.state.ingestion_service,
        )
        app.state.retrieval_service = retrieval_service
        app.state.chat_service = chat_service
        app.state.usage_repository = usage_repository
        app.state.memory_repository = memory_repository
        app.state.memory_store = memory_store
        app.state.memory_service = memory_service
        app.state.tutorial_service = TutorialService(
            llm,
            retrieval_service,
            memory=memory_service,
            vault=vault_service,
            ingestion=app.state.ingestion_service,
            settings=settings,
            projects=project_repository,
        )
        app.state.research_service = ResearchService(
            llm,
            search=search_provider,
            vault=vault_service,
            ingestion=app.state.ingestion_service,
            settings=settings,
            projects=project_repository,
        )
        app.state.search_provider = search_provider

        # Phase 7 learning services: the loop reuses the existing research and
        # tutorial instances (so the testing seam's fake search stays offline)
        # and the map layers over memory + retrieval + the LLM. Both only
        # reference shared components and own no resources to close.
        app.state.learn_service = LearnService(
            retrieval_service,
            app.state.research_service,
            app.state.tutorial_service,
            memory=memory_service,
        )
        app.state.knowledge_map_service = KnowledgeMapService(
            memory_service,
            retrieval_service,
            llm,
            settings,
        )

        # Eval runs their own app-lifetime session, mirroring the other
        # repositories; the judge reuses the shared LLM provider.
        eval_session = session_factory()
        app.state.eval_service = EvalService(
            chat_service,
            llm,
            EvalRepository(eval_session),
            settings,
            documents=document_repository,
        )

        _logger.info(
            "application started",
            extra={
                "env": settings.app_env,
                "testing": testing,
                "llm": llm.name,
                "search": search_provider.name,
            },
        )
        try:
            yield
        finally:
            for resource in (
                vector_store,
                memory_store,
                llm,
                embeddings,
                search_provider,
                app.state.research_service,
            ):
                await _close_resource(resource)
            await ingestion_session.close()
            await usage_session.close()
            await memory_session.close()
            await eval_session.close()
            await engine.dispose()
            _logger.info("application stopped", extra={"env": settings.app_env})

    return lifespan


def create_app(settings: Settings | None = None, *, testing: bool = False) -> FastAPI:
    """Build the FastAPI application with its full dependency wiring.

    ``settings`` defaults to the process-wide ``get_settings()``. When
    ``testing=True``, network-touching components are replaced by in-memory
    fakes (fixed-size embeddings, canned LLM answers, in-memory vector store)
    so the app runs offline for integration tests.
    """
    setup_logging()
    settings = settings or get_settings()

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        lifespan=_make_lifespan(settings, testing=testing),
    )
    app.include_router(v1_compat_router)
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(evals_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(learn_router, prefix="/api/v1")
    app.include_router(memories_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(research_router, prefix="/api/v1")
    app.include_router(sync_router, prefix="/api/v1")
    app.include_router(tutorials_router, prefix="/api/v1")
    app.include_router(usage_router, prefix="/api/v1")
    # Own console: the index route and the static mount are registered AFTER
    # every API router (and the /v1 OpenAI-compatible surface), so they can
    # never shadow /api/v1/* or /v1/*.
    app.include_router(_console_router)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    return app