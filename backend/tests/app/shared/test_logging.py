import json
import logging

from app.shared.logging.logger import ContextLogger, JSONFormatter, configure_logging


class TestContextLogger:
    def teardown_method(self) -> None:
        ContextLogger.clear_context()

    def test_set_then_get_context_round_trips(self) -> None:
        ContextLogger.set_context(correlation_id="corr_1", session_id="ses_1")
        context = ContextLogger.get_context()
        assert context == {"correlation_id": "corr_1", "session_id": "ses_1"}

    def test_set_context_without_session_id_leaves_it_unset(self) -> None:
        ContextLogger.clear_context()
        ContextLogger.set_context(correlation_id="corr_1")
        assert ContextLogger.get_context()["session_id"] is None

    def test_clear_context_resets_both_fields(self) -> None:
        ContextLogger.set_context(correlation_id="corr_1", session_id="ses_1")
        ContextLogger.clear_context()
        assert ContextLogger.get_context() == {"correlation_id": None, "session_id": None}

    def test_get_context_before_any_set_is_all_none(self) -> None:
        ContextLogger.clear_context()
        assert ContextLogger.get_context() == {"correlation_id": None, "session_id": None}


class TestJSONFormatter:
    def teardown_method(self) -> None:
        ContextLogger.clear_context()

    def test_format_produces_valid_json_with_expected_fields(self) -> None:
        ContextLogger.set_context(correlation_id="corr_1", session_id="ses_1")
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )

        formatted = formatter.format(record)
        payload = json.loads(formatted)

        assert payload["message"] == "hello world"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "test.logger"
        assert payload["correlation_id"] == "corr_1"
        assert payload["session_id"] == "ses_1"

    def test_format_includes_exception_when_present(self) -> None:
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failed",
                args=(),
                exc_info=sys.exc_info(),
            )
            payload = json.loads(formatter.format(record))
            assert "exception" in payload
            assert "ValueError" in payload["exception"]

    def test_format_without_exception_omits_the_field(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="ok",
            args=(),
            exc_info=None,
        )
        payload = json.loads(formatter.format(record))
        assert "exception" not in payload


class TestConfigureLogging:
    def teardown_method(self) -> None:
        # Restore a clean root logger so this test doesn't leak handlers
        # into other tests' output.
        root_logger = logging.getLogger()
        root_logger.handlers = []
        root_logger.setLevel(logging.WARNING)

    def test_installs_a_single_json_formatted_stream_handler(self) -> None:
        configure_logging(level=logging.DEBUG)
        root_logger = logging.getLogger()

        assert root_logger.level == logging.DEBUG
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0], logging.StreamHandler)
        assert isinstance(root_logger.handlers[0].formatter, JSONFormatter)

    def test_default_level_is_info(self) -> None:
        configure_logging()
        assert logging.getLogger().level == logging.INFO

    def test_replaces_any_previously_configured_handlers(self) -> None:
        root_logger = logging.getLogger()
        root_logger.addHandler(logging.NullHandler())
        configure_logging()
        assert len(root_logger.handlers) == 1
