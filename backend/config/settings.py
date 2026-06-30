from pydantic_settings import BaseSettings
from typing import Optional
import os


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

    # Firebase Authentication
    FIREBASE_CREDENTIALS_JSON: str = ""  # JSON string of service account key
    FIREBASE_CREDENTIALS_PATH: str = ""  # Path to service account JSON file

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    CORS_ORIGIN_REGEX: str = r"https?://(localhost|127\.0\.0\.1):\d+"

    # Virtual Capital
    DEFAULT_VIRTUAL_CAPITAL: float = 1000000.0  # 10 Lakh INR

    # Market Data
    MARKET_DATA_CACHE_SECONDS: int = 15
    PRICE_STREAM_INTERVAL: float = 3.0
    STRICT_ZEBU_MARKET_DATA: bool = True

    # Redis (shared live price cache across all user sessions)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Zebu / MYNT Market Data Feed (per-user sessions via BrokerSessionManager)
    # Zebu rebranded to MYNT; go.mynt.in is the current production host.
    ZEBU_WS_URL: str = "wss://go.mynt.in/NorenWSTP/"
    ZEBU_API_KEY: str = ""  # legacy — use ZEBU_API_SECRET instead
    ZEBU_API_SECRET: str = ""  # "App Key" from MYNT portal → Client Code → API Key

    # Zebu Broker OAuth / API Integration
    ZEBU_API_URL: str = "https://go.mynt.in/NorenWClientTP"
    ZEBU_AUTH_URL: str = "https://go.mynt.in/OAuthlogin/authorize/oauth"
    ZEBU_VENDOR_CODE: str = ""
    # OAuth client_id from MYNT portal (defaults to {ZEBU_VENDOR_CODE}_U in code)
    ZEBU_OAUTH_CLIENT_ID: str = ""
    ZEBU_REDIRECT_URI: str = "http://localhost:5173/broker/callback"

    # ── Master Zebu Account (DISABLED — users must connect own broker) ─
    # Kept for backward compat but no longer used at startup.
    ZEBU_MASTER_USER_ID: str = ""
    ZEBU_MASTER_PASSWORD: str = ""
    ZEBU_MASTER_DOB: str = ""

    # ── Alice Blue (ANT OpenAPI v2) ───────────────────────────────
    # Official docs: https://v2api.aliceblueonline.com/
    ALICE_BLUE_APP_ID: str = ""       # app_id from Alice Blue developer portal
    ALICE_BLUE_APP_SECRET: str = ""   # app_secret / client_secret

    # v2 REST API base — ALL API calls (history, session, etc.) go here
    # Docs: https://v2api.aliceblueonline.com/Historical%20Data/
    ALICE_BLUE_API_BASE: str = "https://a3.aliceblueonline.com/open-api"

    # Legacy ANT API (kept for backwards compat — NOT used for historical data)
    ALICE_BLUE_API_URL: str = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api"

    # App code / OAuth URLs
    ALICE_BLUE_APPCODE_AUTH_URL: str = "https://ant.aliceblueonline.com/"

    # WS session creation: POST /od/v1/profile/createWsSess (docs: Websocket page)
    ALICE_BLUE_SESSION_URL: str = (
        "https://ant.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails"
    )

    # Historical data: POST /od/ChartAPIService/api/chart/history
    # Docs: https://v2api.aliceblueonline.com/Historical%20Data/
    ALICE_BLUE_HISTORY_URL: str = (
        "https://a3.aliceblueonline.com/open-api/od/ChartAPIService/api/chart/history"
    )

    ALICE_BLUE_AUTH_URL: str = "https://ant.aliceblueonline.com/oauth2/auth"
    ALICE_BLUE_TOKEN_URL: str = "https://ant.aliceblueonline.com/oauth2/token"

    # WebSocket URL per official docs: https://v2api.aliceblueonline.com/Websocket/
    # "Create Connection to Web Socket using the following URL: wss://ws1.aliceblueonline.com/NorenWS"
    ALICE_BLUE_WS_URL: str = "wss://ws1.aliceblueonline.com/NorenWS"
    ALICE_BLUE_REDIRECT_URI: str = "http://localhost:5173/broker/callback"

    # ── Zerodha (Kite Connect) ───────────────────────────────────────
    ZERODHA_API_KEY: str = ""         # API key from Kite Connect developer portal
    ZERODHA_API_SECRET: str = ""      # API secret from Kite Connect
    ZERODHA_API_URL: str = "https://api.kite.trade"
    ZERODHA_AUTH_URL: str = "https://kite.trade/connect/login"
    ZERODHA_WS_URL: str = "wss://ws.kite.trade"
    ZERODHA_REDIRECT_URI: str = "http://localhost:5173/broker/callback?broker=zerodha"

    # Broker Token Encryption (AES-256-GCM)
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    BROKER_ENCRYPTION_KEY: str = (
        "alphasync-default-broker-key-change-in-production-1234"
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

    # Simulation mode enables demo data fallback when no Zebu session is configured.
    # It does NOT bypass market-hour order restrictions.
    SIMULATION_MODE: bool = True

    # ── Progressive hydration feature flags (Phase 1A) ─────────────
    # Keep disabled by default; enables snapshot-first responses per page.
    ENABLE_PROGRESSIVE_OPTIONS: bool = False
    ENABLE_PROGRESSIVE_FUTURES: bool = False
    ENABLE_PROGRESSIVE_COMMODITIES: bool = False

    # Dev override only. Keep False in normal environments.
    # When True, orders/algos can run outside market hours.
    ALLOW_AFTER_HOURS_TRADING: bool = False

    # ── Admin Panel ──────────────────────────────────────────────────
    ADMIN_SESSION_EXPIRY_MINUTES: int = 30
    TOTP_ISSUER_NAME: str = "AlphaSync Admin"
    # Temporary bootstrap admin allowlist. Override in env for production.
    ADMIN_EMAIL_ALLOWLIST: list[str] = ["ashok.j2346@gmail.com"]
    # Root admin email — has unrestricted access and can create/manage other admins.
    ROOT_ADMIN_EMAIL: str = "ashok.j2346@gmail.com"

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
