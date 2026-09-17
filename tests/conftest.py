"""Shared test fixtures.

Tests use in-memory SQLite (aiosqlite + StaticPool): fast, isolated, and
free of external services. Alembic remains the canonical schema source.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.domain.models.document  # noqa: F401  (register tables on Base.metadata)
from app.domain.models import Base


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