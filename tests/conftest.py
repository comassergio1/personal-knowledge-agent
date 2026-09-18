"""Shared test fixtures.

Unit tests use in-memory SQLite (aiosqlite + StaticPool): fast, isolated,
and free of external services. The ``test_app`` fixture builds the full
FastAPI app through ``create_app(settings=..., testing=True)`` so the LLM,
embedding, and vector-store components are in-memory fakes — no daemons.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.domain.models import (  # noqa: F401  (register tables on Base.metadata)
    Base,
    document,
    memory,
    project,
    usage,
)
from app.main import create_app


@pytest_asyncio.fixture
async def db_session():
    """Yield a fresh AsyncSession over a throwaway in-memory database."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


def _test_settings(vault_path: Path | None = None) -> Settings:
    """Settings for the offline integration tests (in-memory DB)."""
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        # The vault root is relocated into the per-test tmp dir so tests never
        # write into the repository's real ``data/vault``.
        vault_path=vault_path,
        # Dead endpoint so the health probe is hermetic: it reports False even
        # when a real Ollama daemon is running on this machine.
        ollama_base_url="http://127.0.0.1:59999",
    )


@pytest.fixture
def test_app(tmp_path: Path) -> TestClient:
    """A running app with fake providers; the context manager runs lifespan."""
    app = create_app(settings=_test_settings(vault_path=tmp_path / "vault"), testing=True)
    with TestClient(app) as client:
        yield client