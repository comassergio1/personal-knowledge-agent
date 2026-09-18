"""FastAPI dependencies resolving application singletons from ``app.state``.

Every dependency reads from ``request.app.state`` so the app factory owns the
construction/lifetime of services and routes never build them directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.repositories.memory_repository import MemoryRepository
from app.repositories.usage_repository import UsageRepository
from app.services.chat_service import ChatService
from app.services.ingestion_service import IngestionService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.services.sync_service import SyncService
from app.services.vault_service import VaultService
from app.vector.qdrant import QdrantVectorStore


def get_settings(request: Request) -> Settings:
    """Return the settings the application was built with."""
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one fresh :class:`AsyncSession` per request."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_ingestion_service(request: Request) -> IngestionService:
    """Return the shared ingestion service from ``app.state``."""
    return request.app.state.ingestion_service


def get_retrieval_service(request: Request) -> RetrievalService:
    """Return the shared retrieval service from ``app.state``."""
    return request.app.state.retrieval_service


def get_chat_service(request: Request) -> ChatService:
    """Return the shared chat service from ``app.state``."""
    return request.app.state.chat_service


def get_vector_store(request: Request) -> QdrantVectorStore:
    """Return the shared vector store from ``app.state``."""
    return request.app.state.vector_store


def get_embeddings(request: Request) -> EmbeddingProvider:
    """Return the shared embedding provider from ``app.state``."""
    return request.app.state.embeddings


def get_llm(request: Request) -> LLMProvider:
    """Return the shared LLM provider from ``app.state``."""
    return request.app.state.llm


def get_usage_repository(request: Request) -> UsageRepository:
    """Return the app-scoped usage repository from ``app.state``."""
    return request.app.state.usage_repository


def get_memory_repository(request: Request) -> MemoryRepository:
    """Return the app-scoped memory repository from ``app.state``."""
    return request.app.state.memory_repository


def get_memory_service(request: Request) -> MemoryService:
    """Return the shared memory service from ``app.state``."""
    return request.app.state.memory_service


def get_vault_service(request: Request) -> VaultService:
    """Return the shared vault service from ``app.state``."""
    return request.app.state.vault_service


def get_sync_service(request: Request) -> SyncService:
    """Return the shared vault sync service from ``app.state``."""
    return request.app.state.sync_service