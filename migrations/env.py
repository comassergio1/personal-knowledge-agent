"""Alembic environment, wired for async SQLAlchemy.

The database URL comes from `app.core.config.Settings` (env + `.env`);
the sqlite file lives under data/ and its parent directory is created on
demand when needed.
"""

import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import make_url, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import Settings
from app.domain.models import Base  # noqa: F401  (registers all tables)
import app.domain.models.document  # noqa: F401  (ensure models are imported)
import app.domain.models.eval  # noqa: F401  (ensure eval model is imported)
import app.domain.models.memory  # noqa: F401  (ensure memory model is imported)
import app.domain.models.project  # noqa: F401  (ensure project model is imported)
import app.domain.models.usage  # noqa: F401  (ensure usage model is imported)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
database_url = settings.database_url

# Create the parent directory of a file-based SQLite database on demand.
_url = make_url(database_url)
if _url.get_backend_name() == "sqlite" and _url.database not in (None, "", ":memory:"):
    Path(_url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

config.set_section_option(config.config_ini_section, "sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against the async engine (online mode)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()