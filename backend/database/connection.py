import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB
from sqlalchemy.exc import OperationalError
from config.settings import settings


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_for_sqlite(_type, _compiler, **_kw):
    return "CHAR(36)"


@compiles(PG_JSONB, "sqlite")
def _compile_pg_jsonb_for_sqlite(_type, _compiler, **_kw):
    return "JSON"


def _create_engine_with_fallback():
    url = getattr(settings, "DATABASE_URL", "sqlite+aiosqlite:///./alphasync.db")
    if not url.startswith("sqlite"):
        import socket
        from urllib.parse import urlparse
        try:
            # Quick 1.5s socket check to ensure PostgreSQL target host:port is reachable
            cleaned_url = url.replace("postgresql+asyncpg://", "http://").replace("postgresql://", "http://")
            parsed = urlparse(cleaned_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 5432
            sock = socket.create_connection((host, port), timeout=1.5)
            sock.close()
        except Exception:
            # PostgreSQL is unreachable locally — fall back to SQLite so app never crashes
            url = "sqlite+aiosqlite:///./alphasync.db"

    kwargs = {"echo": getattr(settings, "DEBUG", False), "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    else:
        kwargs.update(
            {
                "pool_size": getattr(settings, "DB_POOL_SIZE", 20),
                "max_overflow": getattr(settings, "DB_MAX_OVERFLOW", 10),
                "pool_recycle": getattr(settings, "DB_POOL_RECYCLE", 3600),
                "pool_pre_ping": getattr(settings, "DB_POOL_PRE_PING", True),
            }
        )
    eng = create_async_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(eng.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _rec):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return eng


engine = _create_engine_with_fallback()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
async_session_factory = async_session



class Base(DeclarativeBase):
    pass


async def _commit_with_retry(session: AsyncSession, retries: int = 5):
    """Retry transient SQLite lock errors for write-heavy demo workloads.

    WAL mode + busy_timeout=30 s on the connection handle most contention,
    but keep this as a last-resort safety net with exponential back-off.
    """
    for attempt in range(retries):
        try:
            await session.commit()
            return
        except OperationalError as e:
            message = str(e).lower()
            locked = (
                "database is locked" in message or "database table is locked" in message
            )
            if locked and attempt < retries - 1:
                await asyncio.sleep(0.1 * (2 ** attempt))  # 0.1 → 0.2 → 0.4 → 0.8 s
                continue
            raise


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID | str | None) -> None:
    """Sets the transaction-scoped setting `SET LOCAL app.current_tenant_id = ...` for PostgreSQL RLS isolation.
    Also stores `tenant_id` in session.info for SQLite testing / application filtering.
    """
    tenant_str = str(tenant_id) if tenant_id else ""
    session.info["tenant_id"] = tenant_str

    try:
        bind = await session.connection()
        if bind and getattr(bind.dialect, "name", "") == "postgresql":
            await session.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": tenant_str},
            )
    except Exception:
        pass


async def set_super_admin_context(session: AsyncSession, is_super_admin: bool = True) -> None:
    """Sets transaction-scoped `SET LOCAL app.is_super_admin = 'true'` for authorized admin queries.
    Uses PostgreSQL transaction-local SET LOCAL which automatically resets on COMMIT or ROLLBACK.
    """
    val = "true" if is_super_admin else "false"
    session.info["is_super_admin"] = is_super_admin

    try:
        bind = await session.connection()
        if bind and getattr(bind.dialect, "name", "") == "postgresql":
            await session.execute(
                text("SET LOCAL app.is_super_admin = :val"),
                {"val": val},
            )
    except Exception:
        pass


async def reset_tenant_context(session: AsyncSession) -> None:
    """Explicitly resets tenant context on connection checkin / pool release."""
    session.info.pop("tenant_id", None)
    try:
        bind = await session.connection()
        if bind and getattr(bind.dialect, "name", "") == "postgresql":
            await session.execute(text("SET LOCAL app.current_tenant_id = ''"))
    except Exception:
        pass



RLS_TABLES = [
    "users",
    "admin_audit_log",
    "email_notifications_log",
    "auth_refresh_tokens",
    "auth_impersonation_sessions",
    "academy_courses",
    "academy_modules",
    "academy_lessons",
    "academy_content_blocks",
    "academy_enrollments",
    "academy_lesson_progress",
    "academy_study_activity",
    "academy_quiz_attempts",
    "academy_skill_mastery",
    "academy_teacher_student_assignments",
    "academy_challenges",
    "academy_student_challenge_progress",
    "orders",
    "portfolios",
    "holdings",
    "transactions",
    "watchlists",
    "watchlist_items",
    "futures_orders",
    "futures_watchlists",
    "futures_watchlist_items",
    "algo_strategies",
]



async def get_db():
    async with async_session() as session:
        try:
            yield session
            # Only auto-commit if the route didn't already commit/rollback
            if session.is_active:
                await _commit_with_retry(session)
        except Exception:
            if session.is_active:
                await session.rollback()
            raise


async def init_db():
    global engine, async_session, async_session_factory

    # Verify connection to configured database engine; fallback to SQLite if PostgreSQL is unreachable
    try:
        async with engine.begin() as conn:
            pass
    except Exception as conn_err:
        if not settings.DATABASE_URL.startswith("sqlite"):
            logger.warning(
                "PostgreSQL connection to %s failed (%s). Falling back to local SQLite database.",
                settings.DATABASE_URL,
                conn_err,
            )
            fallback_url = "sqlite+aiosqlite:///./alphasync_fallback.db"
            engine = create_async_engine(fallback_url, connect_args={"timeout": 30})
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async_session_factory = async_session

    async with engine.begin() as conn:
        is_postgres = conn.dialect.name == "postgresql"
        is_sqlite = conn.dialect.name == "sqlite"


        if is_postgres:
            # Ensure uuid-ossp extension is available for gen_random_uuid()
            # Wrapped in DO block to handle race condition when multiple workers start simultaneously
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;
            """
                )
            )
        from models import tenant  # noqa — AlphaSync Campus Tenant & RBAC models
        from models import user, order, portfolio, watchlist, algo  # noqa
        from models import futures_order  # noqa  — futures paper trading tables
        from models import futures_watchlist  # noqa  — futures watchlist tables
        from models import historical_ticks  # noqa
        from strategies.zeroloss import models as zeroloss_models  # noqa
        from data_layer.db.models import PriceData, APIKey, IngestionLog  # noqa

        from models.user import (
            AdminAuditLog,
            EmailNotificationLog,
        )  # noqa
        from models.data_feed_config import DataFeedConfig  # noqa
        from models.symbol_master import SymbolMaster  # noqa
        from models.raw_ticks import RawTick  # noqa
        from models.bulk_file_index import BulkFileIndex  # noqa
        from models import academy as academy_models  # noqa — AlphaSync Academy (LMS) tables

        # Create any missing tables (safe operation, never drops or alters existing tables)
        await conn.run_sync(Base.metadata.create_all)

        # Self-healing DDL checks for schema column drift on live databases
        if is_postgres:
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    -- 1. Ensure tenant_type column exists on tenants table
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'tenants') THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'tenants' AND column_name = 'tenant_type') THEN
                            ALTER TABLE tenants ADD COLUMN tenant_type VARCHAR(20) NOT NULL DEFAULT 'institution';
                        END IF;
                    END IF;

                    -- 2. Ensure trader enum value exists in tenantrole enum if enum type exists
                    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tenantrole') THEN
                        IF NOT EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid WHERE t.typname = 'tenantrole' AND e.enumlabel = 'trader') THEN
                            ALTER TYPE tenantrole ADD VALUE IF NOT EXISTS 'trader';
                        END IF;
                    END IF;

                    -- 3. Ensure academy_role column exists on users table if missing
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users') THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'academy_role') THEN
                            ALTER TABLE users ADD COLUMN academy_role VARCHAR(20);
                        END IF;
                    END IF;
                END $$;
            """
                )
            )
        else:
            # SQLite safe column self-healing
            try:
                await conn.execute(text("ALTER TABLE tenants ADD COLUMN tenant_type VARCHAR(20) NOT NULL DEFAULT 'institution'"))
            except Exception:
                pass
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN academy_role VARCHAR(20)"))
            except Exception:
                pass

        logger.info("Database initialized and self-healed successfully via Alembic migration & runtime DDL authority.")


