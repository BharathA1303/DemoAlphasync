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

        await conn.run_sync(Base.metadata.create_all)

        # ── PostgreSQL Schema Migrations & Row-Level Security (RLS) Policies ──
        if is_postgres:
            # 1. First ensure tenants table exists so foreign keys can reference it
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS tenants (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name VARCHAR(200) NOT NULL,
                        slug VARCHAR(100) UNIQUE NOT NULL,
                        domain VARCHAR(255),
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        max_users INTEGER DEFAULT 1000,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            )

            # 2. Add tenant_id column to all existing PostgreSQL tables safely in PL/pgSQL
            await conn.execute(
                text(
                    """
                    DO $$ 
                    DECLARE
                        tbl text;
                        tables text[] := ARRAY[
                            'users', 'admin_audit_log', 'email_notifications_log', 'auth_refresh_tokens',
                            'auth_impersonation_sessions', 'academy_courses', 'academy_modules', 'academy_lessons',
                            'academy_content_blocks', 'academy_enrollments', 'academy_lesson_progress', 'academy_study_activity',
                            'academy_quiz_attempts', 'academy_skill_mastery', 'academy_teacher_student_assignments',
                            'academy_challenges', 'academy_student_challenge_progress', 'orders', 'portfolios',
                            'holdings', 'transactions', 'watchlists', 'watchlist_items', 'futures_orders',
                            'futures_watchlists', 'futures_watchlist_items', 'algo_strategies'
                        ];
                    BEGIN
                        FOREACH tbl IN ARRAY tables LOOP
                            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
                                EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;', tbl);
                            END IF;
                        END LOOP;
                    END $$;
                    """
                )
            )

            # 3. Idempotently add any missing user admin/status columns in PostgreSQL
            await conn.execute(
                text(
                    """
                    DO $$ BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users') THEN
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status VARCHAR(30) NOT NULL DEFAULT 'active';
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS access_expires_at TIMESTAMPTZ;
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS access_duration_days INTEGER;
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_by UUID;
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivation_reason VARCHAR(500);
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_level VARCHAR(20);
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_assigned_by UUID;
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_assigned_at TIMESTAMPTZ;
                            ALTER TABLE users ADD COLUMN IF NOT EXISTS academy_role VARCHAR(20) DEFAULT 'student';
                        END IF;
                    END $$;
                    """
                )
            )

            # 4. Enable RLS and create tenant isolation policy on existing tables
            await conn.execute(
                text(
                    """
                    DO $$ 
                    DECLARE
                        tbl text;
                        tables text[] := ARRAY[
                            'users', 'admin_audit_log', 'email_notifications_log', 'auth_refresh_tokens',
                            'auth_impersonation_sessions', 'academy_courses', 'academy_modules', 'academy_lessons',
                            'academy_content_blocks', 'academy_enrollments', 'academy_lesson_progress', 'academy_study_activity',
                            'academy_quiz_attempts', 'academy_skill_mastery', 'academy_teacher_student_assignments',
                            'academy_challenges', 'academy_student_challenge_progress', 'orders', 'portfolios',
                            'holdings', 'transactions', 'watchlists', 'watchlist_items', 'futures_orders',
                            'futures_watchlists', 'futures_watchlist_items', 'algo_strategies'
                        ];
                    BEGIN
                        FOREACH tbl IN ARRAY tables LOOP
                            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
                                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
                                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', tbl);
                                IF NOT EXISTS (
                                    SELECT 1 FROM pg_policies WHERE tablename = tbl AND policyname = 'tenant_isolation_policy'
                                ) THEN
                                    EXECUTE format('CREATE POLICY tenant_isolation_policy ON %I FOR ALL USING (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid);', tbl);
                                END IF;
                            END IF;
                        END LOOP;
                    END $$;
                    """
                )
            )




        # ── Lightweight, idempotent schema patch for SQLite (demo DB) ─────────
        if is_sqlite:

            async def _sqlite_columns(table_name: str) -> list[str]:
                res = await conn.execute(text(f"PRAGMA table_info({table_name});"))
                return [row[1] for row in res.fetchall()]

            # ── Fix ck_order_type constraint: rebuild if TAKE_PROFIT/BRACKET missing ──
            # SQLite cannot ALTER CHECK constraints, so we use the rename-recreate pattern.
            _ddl_result = await conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'")
            )
            _orders_ddl = _ddl_result.scalar() or ""
            if "'TAKE_PROFIT'" not in _orders_ddl:
                # First ensure new columns exist on the OLD table so the INSERT works
                async def _ensure_old_column(col: str, ddl: str):
                    _cols = await _sqlite_columns("orders")
                    if col not in _cols:
                        await conn.execute(text(f"ALTER TABLE orders ADD COLUMN {ddl};"))

                await _ensure_old_column("product_type", "product_type VARCHAR(10) NOT NULL DEFAULT 'CNC'")
                await _ensure_old_column("tag", "tag VARCHAR(30)")
                await _ensure_old_column("take_profit_price", "take_profit_price NUMERIC(14,2)")
                await _ensure_old_column("rejection_reason", "rejection_reason VARCHAR(500)")

                await conn.execute(text("DROP TABLE IF EXISTS orders_v2"))
                await conn.execute(text("""
                    CREATE TABLE orders_v2 (
                        id CHAR(36) PRIMARY KEY,
                        user_id CHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        symbol VARCHAR(30) NOT NULL,
                        exchange VARCHAR(10) NOT NULL DEFAULT 'NSE',
                        order_type VARCHAR(20) NOT NULL CHECK (
                            order_type IN ('MARKET','LIMIT','STOP_LOSS','TAKE_PROFIT','BRACKET','STOP_LOSS_LIMIT')
                        ),
                        side VARCHAR(4) NOT NULL CHECK (side IN ('BUY','SELL')),
                        product_type VARCHAR(10) NOT NULL DEFAULT 'CNC',
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        price NUMERIC(14,2),
                        trigger_price NUMERIC(14,2),
                        take_profit_price NUMERIC(14,2),
                        filled_quantity INTEGER NOT NULL DEFAULT 0,
                        filled_price NUMERIC(14,2),
                        status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (
                            status IN ('PENDING','OPEN','FILLED','PARTIALLY_FILLED','CANCELLED','REJECTED','EXPIRED')
                        ),
                        rejection_reason VARCHAR(500),
                        tag VARCHAR(30),
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        executed_at DATETIME
                    )
                """))
                await conn.execute(text("""
                    INSERT INTO orders_v2
                        (id, user_id, symbol, exchange, order_type, side, product_type,
                         quantity, price, trigger_price, take_profit_price, filled_quantity,
                         filled_price, status, rejection_reason, tag,
                         created_at, updated_at, executed_at)
                    SELECT
                        id, user_id, symbol, exchange, order_type, side,
                        COALESCE(product_type, 'CNC'),
                        quantity, price, trigger_price, take_profit_price,
                        COALESCE(filled_quantity, 0),
                        filled_price,
                        COALESCE(status, 'PENDING'),
                        rejection_reason, tag, created_at, updated_at, executed_at
                    FROM orders
                """))
                await conn.execute(text("DROP TABLE orders"))
                await conn.execute(text("ALTER TABLE orders_v2 RENAME TO orders"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_user_id ON orders (user_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_symbol ON orders (symbol)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_user_status ON orders (user_id, status)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_user_created ON orders (user_id, created_at)"))

            # Ensure orders table has columns added after initial create
            async def _ensure_sqlite_column(column_name: str, ddl: str):
                cols = await _sqlite_columns("orders")
                if column_name not in cols:
                    await conn.execute(text(f"ALTER TABLE orders ADD COLUMN {ddl};"))

            await _ensure_sqlite_column(
                "product_type", "product_type VARCHAR(10) NOT NULL DEFAULT 'CNC'"
            )
            await _ensure_sqlite_column("tag", "tag VARCHAR(30)")
            await _ensure_sqlite_column(
                "take_profit_price", "take_profit_price NUMERIC(14,2)"
            )
            await _ensure_sqlite_column(
                "rejection_reason", "rejection_reason VARCHAR(500)"
            )
            await _ensure_sqlite_column(
                "idempotency_key", "idempotency_key VARCHAR(100)"
            )
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_idempotency_key ON orders (idempotency_key)"))

            # Ensure holdings table has product_type column and updated unique index
            res_holdings = await conn.execute(text("PRAGMA table_info(holdings);"))
            holdings_cols = [row[1] for row in res_holdings.fetchall()]
            if "product_type" not in holdings_cols:
                await conn.execute(text("ALTER TABLE holdings ADD COLUMN product_type VARCHAR(10) NOT NULL DEFAULT 'CNC';"))
                await conn.execute(text("DROP INDEX IF EXISTS ix_holdings_portfolio_symbol;"))
                await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_holdings_portfolio_symbol_product ON holdings (portfolio_id, symbol, product_type);"))
            else:
                await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_holdings_portfolio_symbol_product ON holdings (portfolio_id, symbol, product_type);"))

            # ── Fix PENDING orders stuck from the broken should_fill_now bug ──
            # Any non-MARKET order left in PENDING was never properly transitioned
            # to OPEN by the trading engine. Move them to OPEN so the worker picks
            # them up, unless they were already filled/cancelled/expired.
            await conn.execute(text("""
                UPDATE orders
                SET status = 'OPEN', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'PENDING'
                  AND order_type IN ('LIMIT','BRACKET','STOP_LOSS','TAKE_PROFIT','STOP_LOSS_LIMIT')
            """))

            # Admin panel columns on users table
            async def _ensure_users_column(column_name: str, ddl: str):
                res = await conn.execute(text("PRAGMA table_info(users);"))
                cols = [row[1] for row in res.fetchall()]
                if column_name not in cols:
                    await conn.execute(text(f"ALTER TABLE users ADD COLUMN {ddl};"))

            # Ensure tenant_id column exists on all existing SQLite tables
            async def _ensure_table_column(table_name: str, column_name: str, ddl: str):
                try:
                    cols = await _sqlite_columns(table_name)
                    if column_name not in cols:
                        await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl};"))
                except Exception:
                    pass

            for tbl in RLS_TABLES:
                await _ensure_table_column(tbl, "tenant_id", "tenant_id CHAR(36)")

            await _ensure_users_column(
                "account_status", "account_status VARCHAR(30) NOT NULL DEFAULT 'active'"
            )
            await _ensure_users_column(
                "access_expires_at", "access_expires_at DATETIME"
            )
            await _ensure_users_column(
                "access_duration_days", "access_duration_days INTEGER"
            )
            await _ensure_users_column("approved_at", "approved_at DATETIME")
            await _ensure_users_column("approved_by", "approved_by CHAR(36)")
            await _ensure_users_column(
                "deactivation_reason", "deactivation_reason VARCHAR(500)"
            )
            # Admin hierarchy columns
            await _ensure_users_column("admin_level", "admin_level VARCHAR(20)")
            await _ensure_users_column(
                "admin_assigned_by", "admin_assigned_by CHAR(36)"
            )
            await _ensure_users_column(
                "admin_assigned_at", "admin_assigned_at DATETIME"
            )
            # AlphaSync Academy (LMS) role — see models/user.py's academy_role
            await _ensure_users_column(
                "academy_role", "academy_role VARCHAR(20) DEFAULT 'student'"
            )


            # AlphaSync Academy (LMS) — Course.instructor_id (Phase 2, Faculty
            # Dashboard), added after academy_courses already existed in prod.
            async def _ensure_academy_courses_column(column_name: str, ddl: str):
                res = await conn.execute(text("PRAGMA table_info(academy_courses);"))
                cols = [row[1] for row in res.fetchall()]
                if column_name not in cols:
                    await conn.execute(text(f"ALTER TABLE academy_courses ADD COLUMN {ddl};"))

            await _ensure_academy_courses_column(
                "instructor_id", "instructor_id CHAR(36)"
            )

            # ZeroLoss strategy columns for per-user isolation
            async def _ensure_zeroloss_signal_column(column_name: str, ddl: str):
                cols = await _sqlite_columns("zeroloss_signals")
                if column_name not in cols:
                    await conn.execute(
                        text(f"ALTER TABLE zeroloss_signals ADD COLUMN {ddl};")
                    )

            async def _ensure_zeroloss_perf_column(column_name: str, ddl: str):
                cols = await _sqlite_columns("zeroloss_performance")
                if column_name not in cols:
                    await conn.execute(
                        text(f"ALTER TABLE zeroloss_performance ADD COLUMN {ddl};")
                    )

            await _ensure_zeroloss_signal_column("user_id", "user_id CHAR(36)")
            await _ensure_zeroloss_signal_column(
                "pnl", "pnl NUMERIC(16,2) NOT NULL DEFAULT 0"
            )
            await _ensure_zeroloss_perf_column("user_id", "user_id CHAR(36)")

            # Drop the legacy broker_accounts table now that broker
            # integrations are fully removed (see alembic 010).
            await conn.execute(text("DROP TABLE IF EXISTS broker_accounts;"))

            # ── data_feed_configs: separate oauth_base_url from the legacy
            # shared base_url column, and repoint any rows still pointing at
            # the docs-site host (zebumyntapi.web.app is documentation only,
            # not an API host — see zebu_client.py) or the old localhost
            # placeholder at the real Zebu MYNT API host, go.mynt.in.
            dfc_cols = await _sqlite_columns("data_feed_configs")
            if "oauth_base_url" not in dfc_cols:
                await conn.execute(text(
                    "ALTER TABLE data_feed_configs ADD COLUMN oauth_base_url VARCHAR(500) "
                    "DEFAULT 'https://go.mynt.in';"
                ))
            if "broker_last_import_rows" not in dfc_cols:
                await conn.execute(text("ALTER TABLE data_feed_configs ADD COLUMN broker_last_import_rows INTEGER;"))
                await conn.execute(text("ALTER TABLE data_feed_configs ADD COLUMN broker_last_import_symbols_found INTEGER;"))
                await conn.execute(text("ALTER TABLE data_feed_configs ADD COLUMN broker_last_import_symbols_total INTEGER;"))
                await conn.execute(text("ALTER TABLE data_feed_configs ADD COLUMN broker_import_progress_done INTEGER;"))
                await conn.execute(text("ALTER TABLE data_feed_configs ADD COLUMN broker_import_progress_total INTEGER;"))
            await conn.execute(text("""
                UPDATE data_feed_configs
                SET base_url = 'https://go.mynt.in/NorenWClientTP'
                WHERE base_url IN ('http://localhost:8000', 'https://zebumyntapi.web.app/Base', 'https://mynt.in/NorenClientTP')
                   OR base_url IS NULL
            """))
            await conn.execute(text("""
                UPDATE data_feed_configs
                SET oauth_base_url = 'https://go.mynt.in'
                WHERE oauth_base_url IN ('https://zebumyntapi.web.app/Base', 'https://mynt.in/NorenClientTP')
                   OR oauth_base_url IS NULL
            """))

            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_zeroloss_signals_user_ts "
                    "ON zeroloss_signals (user_id, timestamp DESC);"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_zeroloss_perf_user_date "
                    "ON zeroloss_performance (user_id, date DESC);"
                )
            )

        if is_postgres:
            # ── Add missing auth-related columns for fresh/legacy DBs ───────
            # create_all doesn't ALTER existing tables — add columns manually
            # if they're missing (idempotent). firebase_uid is kept (unused)
            # for backward compatibility with any pre-migration rows; new
            # users are created with auth_provider='local' (see routes/auth.py).
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    -- Add firebase_uid column if missing (legacy, unused)
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'firebase_uid'
                    ) THEN
                        ALTER TABLE users ADD COLUMN firebase_uid VARCHAR(128) UNIQUE;
                        CREATE INDEX IF NOT EXISTS ix_users_firebase_uid ON users (firebase_uid);
                    END IF;

                    -- Add auth_provider column if missing
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'auth_provider'
                    ) THEN
                        ALTER TABLE users ADD COLUMN auth_provider VARCHAR(30) NOT NULL DEFAULT 'local';
                    END IF;

                    -- Keep password_hash nullable (legacy rows may lack one)
                    ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
                EXCEPTION WHEN others THEN
                    RAISE NOTICE 'Migration note: %', SQLERRM;
                END $$;
            """
                )
            )

            # ── Add admin panel columns to users table ──────────────────
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'account_status'
                    ) THEN
                        ALTER TABLE users ADD COLUMN account_status VARCHAR(30) NOT NULL DEFAULT 'active';
                        CREATE INDEX IF NOT EXISTS ix_users_account_status ON users (account_status);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'access_expires_at'
                    ) THEN
                        ALTER TABLE users ADD COLUMN access_expires_at TIMESTAMPTZ;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'access_duration_days'
                    ) THEN
                        ALTER TABLE users ADD COLUMN access_duration_days INTEGER;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'approved_at'
                    ) THEN
                        ALTER TABLE users ADD COLUMN approved_at TIMESTAMPTZ;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'approved_by'
                    ) THEN
                        ALTER TABLE users ADD COLUMN approved_by UUID REFERENCES users(id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'deactivation_reason'
                    ) THEN
                        ALTER TABLE users ADD COLUMN deactivation_reason VARCHAR(500);
                    END IF;

                    -- Admin hierarchy columns
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'admin_level'
                    ) THEN
                        ALTER TABLE users ADD COLUMN admin_level VARCHAR(20);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'admin_assigned_by'
                    ) THEN
                        ALTER TABLE users ADD COLUMN admin_assigned_by UUID REFERENCES users(id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'admin_assigned_at'
                    ) THEN
                        ALTER TABLE users ADD COLUMN admin_assigned_at TIMESTAMPTZ;
                    END IF;

                    -- AlphaSync Academy (LMS) role — see models/user.py's academy_role
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'academy_role'
                    ) THEN
                        ALTER TABLE users ADD COLUMN academy_role VARCHAR(20) DEFAULT 'student';
                    END IF;

                    -- AlphaSync Academy (LMS) — Course.instructor_id (Phase 2)
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'academy_courses' AND column_name = 'instructor_id'
                    ) THEN
                        ALTER TABLE academy_courses ADD COLUMN instructor_id UUID REFERENCES users(id) ON DELETE SET NULL;
                    END IF;
                EXCEPTION WHEN others THEN
                    RAISE NOTICE 'Admin migration note: %', SQLERRM;
                END $$;
            """
                )
            )

            # ── ZeroLoss per-user columns (signals/performance) ──────────────
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'zeroloss_signals' AND column_name = 'user_id'
                    ) THEN
                        ALTER TABLE zeroloss_signals ADD COLUMN user_id UUID;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'zeroloss_signals' AND column_name = 'pnl'
                    ) THEN
                        ALTER TABLE zeroloss_signals ADD COLUMN pnl NUMERIC(16,2) NOT NULL DEFAULT 0;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'zeroloss_performance' AND column_name = 'user_id'
                    ) THEN
                        ALTER TABLE zeroloss_performance ADD COLUMN user_id UUID;
                    END IF;

                    BEGIN
                        ALTER TABLE zeroloss_signals
                            ADD CONSTRAINT fk_zeroloss_signals_user
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                    EXCEPTION WHEN duplicate_object THEN NULL;
                    END;

                    BEGIN
                        ALTER TABLE zeroloss_performance
                            ADD CONSTRAINT fk_zeroloss_performance_user
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                    EXCEPTION WHEN duplicate_object THEN NULL;
                    END;

                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'zeroloss_performance_date_key'
                    ) THEN
                        ALTER TABLE zeroloss_performance
                            DROP CONSTRAINT zeroloss_performance_date_key;
                    END IF;

                    CREATE INDEX IF NOT EXISTS ix_zeroloss_signals_user_ts
                        ON zeroloss_signals (user_id, timestamp DESC);
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_zeroloss_perf_user_date
                        ON zeroloss_performance (user_id, date);
                EXCEPTION WHEN others THEN
                    RAISE NOTICE 'ZeroLoss migration note: %', SQLERRM;
                END $$;
            """
                )
            )

            # ── Drop legacy broker_accounts table (broker integrations removed) ──
            await conn.execute(text("DROP TABLE IF EXISTS broker_accounts;"))

            # ── Add missing columns to orders table ──────────────────────────
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'orders' AND column_name = 'product_type'
                    ) THEN
                        ALTER TABLE orders ADD COLUMN product_type VARCHAR(10) NOT NULL DEFAULT 'CNC';
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'orders' AND column_name = 'tag'
                    ) THEN
                        ALTER TABLE orders ADD COLUMN tag VARCHAR(30);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'orders' AND column_name = 'take_profit_price'
                    ) THEN
                        ALTER TABLE orders ADD COLUMN take_profit_price NUMERIC(14,2);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'orders' AND column_name = 'rejection_reason'
                    ) THEN
                        ALTER TABLE orders ADD COLUMN rejection_reason VARCHAR(500);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'orders' AND column_name = 'idempotency_key'
                    ) THEN
                        ALTER TABLE orders ADD COLUMN idempotency_key VARCHAR(100);
                        CREATE INDEX IF NOT EXISTS ix_orders_idempotency_key ON orders (idempotency_key);
                    END IF;

                    -- Ensure holdings table has product_type column and updated unique index
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'holdings' AND column_name = 'product_type'
                    ) THEN
                        ALTER TABLE holdings ADD COLUMN product_type VARCHAR(10) NOT NULL DEFAULT 'CNC';
                    END IF;

                    DROP INDEX IF EXISTS ix_holdings_portfolio_symbol;
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_holdings_portfolio_symbol_product ON holdings (portfolio_id, symbol, product_type);

                    -- Expand order_type constraint to include BRACKET and TAKE_PROFIT
                    BEGIN
                        ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_order_type;
                    EXCEPTION WHEN others THEN NULL;
                    END;
                    BEGIN
                        ALTER TABLE orders ADD CONSTRAINT ck_order_type CHECK (
                            order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS', 'TAKE_PROFIT', 'BRACKET', 'STOP_LOSS_LIMIT')
                        );
                    EXCEPTION WHEN duplicate_object THEN NULL;
                    END;
                EXCEPTION WHEN others THEN
                    RAISE NOTICE 'Orders migration note: %', SQLERRM;
                END $$;
            """
                )
            )

            # ── Add seed_generation to data_feed_configs (tracks which mock
            # EOD generator version last seeded PriceData, so a code change
            # to symbol coverage/anchors can trigger one re-seed) ──────────
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'data_feed_configs' AND column_name = 'seed_generation'
                    ) THEN
                        ALTER TABLE data_feed_configs ADD COLUMN seed_generation INTEGER;
                    END IF;
                END $$;
            """
                )
            )

            # ── Add optional real-broker (Zebu) historical-import columns
            # to data_feed_configs ───────────────────────────────────────
            for col_sql in [
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker VARCHAR(20);",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_client_code VARCHAR(100);",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_password_enc TEXT;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_totp_secret_enc TEXT;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_vendor_code VARCHAR(100);",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_last_import_at TIMESTAMPTZ;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_last_import_status VARCHAR(50);",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_last_import_error TEXT;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_last_import_rows INTEGER;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_last_import_symbols_found INTEGER;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_last_import_symbols_total INTEGER;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_import_progress_done INTEGER;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_import_progress_total INTEGER;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_client_id VARCHAR(100);",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_secret_key_enc TEXT;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_redirect_url VARCHAR(500);",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_access_token_enc TEXT;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_refresh_token_enc TEXT;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_token_expires_at TIMESTAMPTZ;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_connection_status VARCHAR(50) DEFAULT 'disconnected';",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_last_error TEXT;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS feed_delay_seconds INTEGER DEFAULT 300;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS redis_active_market_hours_only BOOLEAN DEFAULT true;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS broker_live_feed_enabled BOOLEAN DEFAULT false;",
                "ALTER TABLE data_feed_configs ADD COLUMN IF NOT EXISTS oauth_base_url VARCHAR(500) DEFAULT 'https://go.mynt.in';",
            ]:
                try:
                    await conn.execute(text(col_sql))
                except Exception as e:
                    logger.debug(f"Column add skipped ({col_sql}): {e}")

            try:
                await conn.execute(
                    text(
                        """
                    UPDATE data_feed_configs
                        SET base_url = 'https://go.mynt.in/NorenWClientTP'
                        WHERE base_url IN ('http://localhost:8000', 'https://zebumyntapi.web.app/Base', 'https://mynt.in/NorenClientTP')
                           OR base_url IS NULL;
                    UPDATE data_feed_configs
                        SET oauth_base_url = 'https://go.mynt.in'
                        WHERE oauth_base_url IN ('https://zebumyntapi.web.app/Base', 'https://mynt.in/NorenClientTP')
                           OR oauth_base_url IS NULL;
                """
                    )
                )
            except Exception:
                pass

