from pydantic_settings import BaseSettings
from typing import Optional
import os
import secrets


class Settings(BaseSettings):
    APP_NAME: str = "AlphaSync"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    # Database (PostgreSQL — required for production)
    DATABASE_URL: str = (
        "postgresql+asyncpg://alphasync:alphasync@localhost:5432/alphasync"
    )
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    # Local username/email/password authentication (JWT sessions)
    # Set JWT_SECRET_KEY explicitly in production — the random default
    # changes on every process restart, invalidating all sessions.
    JWT_SECRET_KEY: str = secrets.token_urlsafe(48)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_DAYS: int = 30

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    CORS_ORIGIN_REGEX: str = r"https?://(localhost|127\.0\.0\.1):\d+"

    # Virtual Capital
    DEFAULT_VIRTUAL_CAPITAL: float = 1000000.0  # 10 Lakh INR

    # Market Data
    MARKET_DATA_CACHE_SECONDS: int = 15
    PRICE_STREAM_INTERVAL: float = 3.0

    # Redis (shared live price cache across all user sessions)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Internal simulation engine settings are admin-configured via the Admin
    # Panel (see models/data_feed_config.py, routes/admin.py
    # "/settings/data-feed") and stored in the database, not read from
    # environment variables.
    INTERNAL_SIM_DEFAULT_BASE_URL: str = "http://localhost:8000"

    # Data Feed Secret Encryption (AES-256-GCM)
    # Legacy: encrypts the legacy client-secret field at rest in the database
    # (kept for backward compatibility with older rows; unused by the
    # in-process simulation engine). Generate with:
    # python -c "import secrets; print(secrets.token_urlsafe(48))"
    DATA_FEED_ENCRYPTION_KEY: str = (
        "alphasync-default-data-feed-key-change-in-production-1234"
    )

    # ── New Architecture Settings ───────────────────────────────────

    # Worker intervals (seconds)
    WORKER_MARKET_DATA_INTERVAL: float = 0.5
    WORKER_ORDER_EXECUTION_INTERVAL: float = 5.0
    WORKER_ALGO_STRATEGY_INTERVAL: float = 30.0

    # Risk Engine defaults
    RISK_MAX_POSITION_SIZE: int = 500
    RISK_MAX_CAPITAL_PER_TRADE: float = 200000.0
    RISK_MAX_PORTFOLIO_EXPOSURE: float = 0.80
    RISK_MAX_DAILY_LOSS: float = 50000.0
    RISK_MAX_OPEN_ORDERS: int = 20

    # Simulation mode enables demo data fallback when the internal simulation
    # engine is not configured/enabled. It does NOT bypass market-hour order
    # restrictions.
    SIMULATION_MODE: bool = True

    # When True, the EOD auto-backfill (see services/data_feed_session.py)
    # tries the real free NSE/BSE bhavcopy archives first for each day and
    # only falls back to synthetic mock data if the real source is
    # unreachable/blocked, so charts replay genuine historical prices
    # whenever the exchange is reachable. Set False to always use mock data
    # (e.g. offline dev, or to avoid NSE's anti-bot rate limiting).
    BACKFILL_TRY_REAL_DATA_FIRST: bool = False

    # ── Progressive hydration feature flags (Phase 1A) ─────────────
    # Keep disabled by default; enables snapshot-first responses per page.
    ENABLE_PROGRESSIVE_OPTIONS: bool = False
    ENABLE_PROGRESSIVE_FUTURES: bool = False
    ENABLE_PROGRESSIVE_COMMODITIES: bool = False

    # Dev override only. Keep False in normal environments.
    # When True, orders/algos can run outside market hours.
    ALLOW_AFTER_HOURS_TRADING: bool = False

    # ── Admin Panel ──────────────────────────────────────────────────
    # Temporary bootstrap admin allowlist. Override in env for production.
    ADMIN_EMAIL_ALLOWLIST: list[str] = ["ashok.j2346@gmail.com"]
    # Root admin email — has unrestricted access and can create/manage other admins.
    ROOT_ADMIN_EMAIL: str = "ashok.j2346@gmail.com"

    # ── Scheduled Jobs ──────────────────────────────────────────────
    # Master kill-switch. Set ENABLE_SCHEDULER=false in dev/staging if needed.
    ENABLE_SCHEDULER: bool = True
    # Rolling window for price_data: rows older than this many days are deleted
    # by the nightly cleanup job. 200 days covers all chart timeframes (1h
    # charts look back 190 days max). Increase if you want deeper history.
    PRICE_DATA_RETENTION_DAYS: int = 200
    # How long to keep superseded (NSE-corrected) rows before they are purged.
    # 7 days gives an audit/debug window while keeping the table lean.
    SUPERSEDED_RETENTION_DAYS: int = 7


    # ── SMS (OTP delivery for phone verification via Twilio) ─────────
    # Twilio sends from an international number — no Indian DLT registration needed.
    # Sign up at https://www.twilio.com/try-twilio (free trial credit included).
    # Leave blank to fall back to email OTP delivery.
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""  # e.g. +12025551234 — your Twilio number

    # SMTP for email notifications (Gmail)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "ashok.j2346@gmail.com"
    SMTP_PASSWORD: str = "qcneuqilbxhnppau"
    SMTP_FROM_EMAIL: str = "ashok.j2346@gmail.com"
    SMTP_FROM_NAME: str = "AlphaSync"
    SMTP_USE_TLS: bool = False

    # ── AI Mentor (Grok API) ─────────────────────────────────────
    # GROK_API_KEY is read from environment variables (GitHub Actions secrets).
    # Set via: export GROK_API_KEY="your-grok-api-key"
    # The grok_config.py module reads this automatically.

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
