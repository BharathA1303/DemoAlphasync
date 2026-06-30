import asyncio
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


engine_kwargs = {
    "echo": settings.DEBUG,
    "future": True,
}

if settings.DATABASE_URL.startswith("sqlite"):
    # 30-second busy timeout so concurrent writers wait instead of immediately
    # raising "database is locked".
    engine_kwargs["connect_args"] = {"timeout": 30}
else:
    engine_kwargs.update(
        {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
        }
    )

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

if settings.DATABASE_URL.startswith("sqlite"):
    # Enable WAL mode so readers never block writers and vice-versa.
    # NORMAL synchronous is safe for demo workloads and far less contended.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Alias for background workers that need direct session access
# (not via FastAPI's Depends(get_db) dependency injection)
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
        from models import user, order, portfolio, watchlist, algo  # noqa
        from models import broker as broker_model  # noqa
        from models import futures_order  # noqa  — futures paper trading tables
        from models import futures_watchlist  # noqa  — futures watchlist tables
        from models import historical_ticks  # noqa
        from strategies.zeroloss import models as zeroloss_models  # noqa

        # Ensure admin panel models (TwoFactorAuth, AdminSession, etc.) are loaded
        from models.user import (
            TwoFactorAuth,
            AdminSession,
            AdminAuditLog,
            EmailNotificationLog,
        )  # noqa

        await conn.run_sync(Base.metadata.create_all)

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

            # Broker app credentials column (per-user API key/secret, encrypted)
            async def _ensure_broker_account_column(column_name: str, ddl: str):
                cols = await _sqlite_columns("broker_accounts")
                if column_name not in cols:
                    await conn.execute(
                        text(f"ALTER TABLE broker_accounts ADD COLUMN {ddl};")
                    )

            await _ensure_broker_account_column("credentials_enc", "credentials_enc TEXT")
            await _ensure_broker_account_column("display_name", "display_name VARCHAR(100)")

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
            # ── Add missing columns for Firebase auth migration ─────────────
            # create_all doesn't ALTER existing tables — add columns manually
            # if they're missing (idempotent).
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    -- Add firebase_uid column if missing
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
                        ALTER TABLE users ADD COLUMN auth_provider VARCHAR(30) NOT NULL DEFAULT 'firebase';
                    END IF;

                    -- Make password_hash nullable (Firebase users have no password)
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

            # ── Add broker app-credentials column (per-user, encrypted) ──────
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'broker_accounts' AND column_name = 'credentials_enc'
                    ) THEN
                        ALTER TABLE broker_accounts ADD COLUMN credentials_enc TEXT;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'broker_accounts' AND column_name = 'display_name'
                    ) THEN
                        ALTER TABLE broker_accounts ADD COLUMN display_name VARCHAR(100);
                    END IF;
                EXCEPTION WHEN others THEN
                    RAISE NOTICE 'Broker credentials migration note: %', SQLERRM;
                END $$;
            """
                )
            )

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

            # ── One-time: clear stale saved broker credentials (MYNT migration) ─
            await conn.execute(
                text(
                    """
                DO $$ BEGIN
                    CREATE TABLE IF NOT EXISTS _alphasync_migrations (
                        name VARCHAR(100) PRIMARY KEY,
                        applied_at TIMESTAMPTZ DEFAULT now()
                    );

                    IF NOT EXISTS (
                        SELECT 1 FROM _alphasync_migrations
                        WHERE name = '009_clear_broker_credentials'
                    ) THEN
                        UPDATE broker_accounts
                        SET
                            credentials_enc = NULL,
                            broker_user_id = NULL,
                            display_name = NULL,
                            access_token_enc = NULL,
                            refresh_token_enc = NULL,
                            extra_data_enc = NULL,
                            is_active = false,
                            token_expiry = NULL,
                            last_used_at = NULL
                        WHERE credentials_enc IS NOT NULL
                           OR access_token_enc IS NOT NULL
                           OR broker_user_id IS NOT NULL;

                        INSERT INTO _alphasync_migrations (name)
                        VALUES ('009_clear_broker_credentials');
                    END IF;
                EXCEPTION WHEN others THEN
                    RAISE NOTICE 'Broker credential reset note: %', SQLERRM;
                END $$;
            """
                )
            )
