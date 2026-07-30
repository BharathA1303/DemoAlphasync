from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.connection import engine as async_engine, async_session as AsyncSessionLocal, get_db
from config.settings import settings

# Convert asyncpg URL to standard sync postgres URL for seeder
sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "").replace("+psycopg2", "")

_sync_engine = None
_SessionLocal = None

def __getattr__(name):
    global _sync_engine, _SessionLocal
    if name == "sync_engine":
        if _sync_engine is None:
            _sync_engine = create_engine(
                sync_db_url,
                echo=False,
                pool_pre_ping=True,
            )
        return _sync_engine
    elif name == "SessionLocal":
        if _SessionLocal is None:
            engine = __getattr__("sync_engine")
            _SessionLocal = sessionmaker(
                bind=engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
        return _SessionLocal
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

@asynccontextmanager
async def get_async_db_context() -> AsyncGenerator[AsyncSessionLocal, None]:
    """Async context manager to get a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """Sync context manager for CLI/scripts that run outside async loop."""
    local_sessionmaker = __getattr__("SessionLocal")
    session = local_sessionmaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
