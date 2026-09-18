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

from fastapi import FastAPI
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
from app.api.routes.health import router as health_router
from app.api.routes.memories import router as memories_router
from app.api.routes.projects import router as projects_router
from app.api.routes.sync import router as sync_router
from app.api.routes.tutorials import router as tutorials_router
from app.api.routes.usage import router as usage_router
from app.core.config import Settings, get_settings
from app.core.logging import get_logger, setup_logging
from app.database import create_app_engine
from app.domain.models import Base
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.factory import EmbeddingProviderFactory
from app.providers.llm.base import LLMProvider, LLMResult
from app.providers.llm.factory import LLMProviderFactory
from app.repositories.document_repository import DocumentRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.usage_repository import UsageRepository
from app.services.chat_service import ChatService
from app.services.ingestion_service import IngestionService
from app.services.memory_extractor import MemoryExtractor
from app.services.memory_service import MemoryService
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

_logger = get_logger("application")


# Marker in the extractor's system prompt; the fake LLM answers extraction
# prompts with a canned candidate array so the testing app stays offline.
_EXTRACTOR_MARKER = "Output ONLY a JSON array"


class _FakeLLM(LLMProvider):
    """Canned-answer LLM used when ``testing=True`` (no network).

    Memory-extraction prompts get a canned candidate array (containing a
    secret, so redaction is exercised); everything else gets a canned chat
    answer.
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
        else:
            embeddings = EmbeddingProviderFactory.create(
                settings.embedding_provider, settings
            )
            vector_store = QdrantVectorStore(url=settings.qdrant_url)
            memory_store = QdrantVectorStore(
                url=settings.qdrant_url, collection=MEMORIES_COLLECTION
            )
            llm = LLMProviderFactory.create(settings.llm_provider, settings)

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

        _logger.info(
            "application started",
            extra={"env": settings.app_env, "testing": testing, "llm": llm.name},
        )
        try:
            yield
        finally:
            for resource in (vector_store, memory_store, llm, embeddings):
                await _close_resource(resource)
            await ingestion_session.close()
            await usage_session.close()
            await memory_session.close()
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
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(memories_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(sync_router, prefix="/api/v1")
    app.include_router(tutorials_router, prefix="/api/v1")
    app.include_router(usage_router, prefix="/api/v1")
    return app