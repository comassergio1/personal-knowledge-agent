"""Database engine and session management.

Alembic is the canonical schema manager; `init_db()` is a convenience for
tests and local development fallback (create_all).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.domain.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# SQLite WAL allows one writer with concurrent readers; busy_timeout makes a
# blocked writer wait instead of failing with "database is locked" when app
# sessions contend (observed live during the Phase 2 chat usage write).
SQLITE_BUSY_TIMEOUT_MS = 5000


def _sqlite_connect_args(database_url: str) -> dict[str, object]:
    """Connect args for sqlite URLs; empty for other backends."""
    if make_url(database_url).get_backend_name() != "sqlite":
        return {}
    return {"check_same_thread": False, "timeout": 30}


def _install_sqlite_pragmas(engine: AsyncEngine, database_url: str) -> None:
    """Enable WAL journal mode and busy_timeout on every sqlite connection."""
    if make_url(database_url).get_backend_name() != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()


def create_app_engine(database_url: str) -> AsyncEngine:
    """Build an async engine with the SQLite WAL/busy_timeout pragmas."""
    engine = create_async_engine(
        database_url, connect_args=_sqlite_connect_args(database_url)
    )
    _install_sqlite_pragmas(engine, database_url)
    return engine


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def engine() -> AsyncEngine:
    """Return the process-wide async engine, created lazily from settings."""
    global _engine
    if _engine is None:
        _ensure_sqlite_parent_dir(get_settings().database_url)
        _engine = create_app_engine(get_settings().database_url)
    return _engine


def async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the process-wide engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    """Create all tables if missing (dev/test fallback). Prefer Alembic."""
    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)