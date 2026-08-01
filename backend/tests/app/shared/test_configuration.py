import pytest

from app.shared.configuration.settings import (
    AppSettings,
    DatabaseSettings,
    DataProviderSettings,
    ObservabilitySettings,
    RedisSettings,
    load_settings,
)


@pytest.fixture
def db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASYNC_DB_DSN", "postgresql+asyncpg://user:pass@localhost/alphasync")


@pytest.fixture
def redis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASYNC_REDIS_DSN", "redis://localhost:6379/0")


class TestDatabaseSettings:
    def test_valid_asyncpg_dsn_is_accepted(self, db_env: None) -> None:
        settings = DatabaseSettings()
        assert settings.dsn.scheme == "postgresql+asyncpg"

    def test_non_asyncpg_dsn_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPHASYNC_DB_DSN", "postgresql://user:pass@localhost/alphasync")
        with pytest.raises(ValueError, match="postgresql\\+asyncpg"):
            DatabaseSettings()

    def test_default_pool_size(self, db_env: None) -> None:
        assert DatabaseSettings().pool_size == 10

    def test_pool_size_out_of_range_rejected(self, monkeypatch: pytest.MonkeyPatch, db_env: None) -> None:
        monkeypatch.setenv("ALPHASYNC_DB_POOL_SIZE", "0")
        with pytest.raises(ValueError):
            DatabaseSettings()

    def test_missing_dsn_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALPHASYNC_DB_DSN", raising=False)
        with pytest.raises(ValueError):
            DatabaseSettings()


class TestRedisSettings:
    def test_valid_dsn_is_accepted(self, redis_env: None) -> None:
        settings = RedisSettings()
        assert settings.dsn.scheme == "redis"

    def test_default_socket_timeout(self, redis_env: None) -> None:
        assert RedisSettings().socket_timeout_seconds == 5.0


class TestDataProviderSettings:
    def test_defaults_point_at_zebu_mynt_host(self) -> None:
        settings = DataProviderSettings()
        assert "mynt.in" in settings.rest_base_url
        assert settings.ws_url.startswith("wss://")

    def test_client_code_defaults_to_empty_string_not_none(self) -> None:
        """Must be an empty string (not None) so downstream code can treat
        'not configured yet' uniformly without an extra None check."""
        assert DataProviderSettings().client_code == ""


class TestObservabilitySettings:
    def test_default_log_level_is_info(self) -> None:
        assert ObservabilitySettings().log_level == "INFO"

    def test_log_level_is_uppercased(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPHASYNC_OBSERVABILITY_LOG_LEVEL", "debug")
        assert ObservabilitySettings().log_level == "DEBUG"

    def test_invalid_log_level_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALPHASYNC_OBSERVABILITY_LOG_LEVEL", "NOT_A_LEVEL")
        with pytest.raises(ValueError):
            ObservabilitySettings()


class TestAppSettings:
    def test_composes_all_sections(self, db_env: None, redis_env: None) -> None:
        settings = AppSettings()
        assert settings.database.dsn.scheme == "postgresql+asyncpg"
        assert settings.redis.dsn.scheme == "redis"
        assert settings.data_provider.rest_base_url
        assert settings.observability.log_level == "INFO"

    def test_default_environment_is_development(self, db_env: None, redis_env: None) -> None:
        assert AppSettings().environment == "development"

    def test_environment_env_var_is_respected(
        self, monkeypatch: pytest.MonkeyPatch, db_env: None, redis_env: None
    ) -> None:
        monkeypatch.setenv("ALPHASYNC_ENVIRONMENT", "production")
        assert AppSettings().environment == "production"


class TestLoadSettings:
    def test_returns_the_same_instance_when_called_twice(self, db_env: None, redis_env: None) -> None:
        load_settings.cache_clear()
        first = load_settings()
        second = load_settings()
        assert first is second
        load_settings.cache_clear()
