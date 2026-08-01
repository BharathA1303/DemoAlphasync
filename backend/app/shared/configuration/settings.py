"""Typed application configuration.

No global mutable settings object is exported from this module — callers
construct an `AppSettings` explicitly (typically once, at process startup,
via `load_settings()`) and pass it through the dependency injection
container. This keeps configuration testable and avoids the "no global
state" rule being violated by an import-time singleton.
"""
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALPHASYNC_DB_", extra="ignore")

    dsn: PostgresDsn = Field(..., description="Async PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host/db")
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    echo: bool = Field(default=False)

    @field_validator("dsn")
    @classmethod
    def _require_asyncpg_driver(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme != "postgresql+asyncpg":
            raise ValueError(
                f"Database DSN must use the 'postgresql+asyncpg' driver for async SQLAlchemy 2, got '{value.scheme}'"
            )
        return value


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALPHASYNC_REDIS_", extra="ignore")

    dsn: RedisDsn = Field(..., description="Redis DSN, e.g. redis://host:6379/0")
    socket_timeout_seconds: float = Field(default=5.0, gt=0)


class DataProviderSettings(BaseSettings):
    """Configuration for the Zebu MYNT data provider — the sole source of
    real market data (see external_adapters/data_provider/mynt)."""

    model_config = SettingsConfigDict(env_prefix="ALPHASYNC_MYNT_", extra="ignore")

    rest_base_url: str = Field(default="https://go.mynt.in/NorenWClientTP")
    ws_url: str = Field(default="wss://go.mynt.in/NorenWSTP/")
    client_code: str = Field(default="")
    vendor_code: str = Field(default="")
    api_key: str = Field(default="")
    request_timeout_seconds: float = Field(default=15.0, gt=0)


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALPHASYNC_OBSERVABILITY_", extra="ignore")

    log_level: str = Field(default="INFO")
    json_logs: bool = Field(default=True)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got '{value}'")
        return upper


class AppSettings(BaseSettings):
    """Root application settings, composed of section-specific settings.

    Environment variables are read once at construction time (via each
    sub-settings' own pydantic-settings env loading) — nothing here re-reads
    the environment after startup.
    """

    model_config = SettingsConfigDict(extra="ignore")

    environment: str = Field(default="development", alias="ALPHASYNC_ENVIRONMENT")
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    data_provider: DataProviderSettings = Field(default_factory=DataProviderSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    """Construct (and memoize within this process) the application settings.

    Using `lru_cache` here is a deliberate, singular exception to "no
    global state": configuration is immutable for the lifetime of the
    process, read once from the environment, and never mutated — it is not
    a service locator or shared mutable object. Tests that need different
    settings should construct `AppSettings(...)` directly rather than
    going through this cache.
    """
    return AppSettings()
