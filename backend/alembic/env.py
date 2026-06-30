"""
Alembic environment configuration for AlphaSync.

Uses async PostgreSQL engine matching the app's database/connection.py setup.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from config.settings import settings
from database.connection import Base

# Import ALL models so Base.metadata is populated
from models.user import User, TwoFactorAuth, UserSession  # noqa: F401
from models.broker import BrokerAccount  # noqa: F401
from models.order import Order  # noqa: F401
from models.portfolio import Portfolio, Holding, Transaction  # noqa: F401
from models.watchlist import Watchlist, WatchlistItem  # noqa: F401
from models.algo import AlgoStrategy, AlgoTrade, AlgoLog  # noqa: F401
from strategies.zeroloss.models import ZeroLossSignal, ZeroLossPerformance  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL to stdout."""
    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    configuration = {
        "sqlalchemy.url": settings.DATABASE_URL,
        "sqlalchemy.pool_size": 5,
        "sqlalchemy.max_overflow": 0,
    }
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entrypoint for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
