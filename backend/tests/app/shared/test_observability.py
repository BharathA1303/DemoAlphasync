import logging
import time

from app.shared.logging.logger import ContextLogger
from app.shared.observability import (
    API_LATENCY_BUDGET,
    PAPER_ORDER_LATENCY_BUDGET,
    LatencyBudget,
    bind_correlation_id,
    extract_or_create_correlation_id,
    measure_latency,
)


class TestExtractOrCreateCorrelationId:
    def test_returns_the_supplied_header_value(self) -> None:
        assert extract_or_create_correlation_id("corr_from_caller") == "corr_from_caller"

    def test_strips_whitespace_from_supplied_header(self) -> None:
        assert extract_or_create_correlation_id("  corr_from_caller  ") == "corr_from_caller"

    def test_mints_a_new_id_when_header_is_none(self) -> None:
        generated = extract_or_create_correlation_id(None)
        assert generated.startswith("corr_")

    def test_mints_a_new_id_when_header_is_blank(self) -> None:
        generated = extract_or_create_correlation_id("   ")
        assert generated.startswith("corr_")

    def test_two_calls_without_a_header_produce_different_ids(self) -> None:
        assert extract_or_create_correlation_id(None) != extract_or_create_correlation_id(None)


class TestBindCorrelationId:
    def teardown_method(self) -> None:
        ContextLogger.clear_context()

    def test_binds_correlation_id_into_context_logger(self) -> None:
        bind_correlation_id("corr_1")
        assert ContextLogger.get_context()["correlation_id"] == "corr_1"

    def test_binds_optional_session_id(self) -> None:
        bind_correlation_id("corr_1", session_id="ses_1")
        assert ContextLogger.get_context()["session_id"] == "ses_1"


class TestLatencyBudgets:
    def test_api_budget_is_50ms(self) -> None:
        assert API_LATENCY_BUDGET.max_milliseconds == 50.0

    def test_paper_order_budget_is_10ms(self) -> None:
        assert PAPER_ORDER_LATENCY_BUDGET.max_milliseconds == 10.0


class TestMeasureLatency:
    def test_fast_block_does_not_log_a_warning(self) -> None:
        records: list[logging.LogRecord] = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.getLogger("app.shared.observability.latency")
        handler = _CapturingHandler()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            budget = LatencyBudget(name="fast_op", max_milliseconds=1000.0)
            with measure_latency(budget):
                pass  # near-instant, well under the 1000ms budget
        finally:
            logger.removeHandler(handler)

        warnings = [r for r in records if r.levelno == logging.WARNING]
        assert warnings == []

    def test_slow_block_logs_a_warning(self) -> None:
        records: list[logging.LogRecord] = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.getLogger("app.shared.observability.latency")
        handler = _CapturingHandler()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            budget = LatencyBudget(name="slow_op", max_milliseconds=1.0)
            with measure_latency(budget):
                time.sleep(0.005)
        finally:
            logger.removeHandler(handler)

        warnings = [r for r in records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "slow_op" in warnings[0].getMessage()

    def test_exception_inside_block_still_propagates(self) -> None:
        import pytest

        budget = LatencyBudget(name="failing_op", max_milliseconds=1000.0)
        with pytest.raises(ValueError), measure_latency(budget):
            raise ValueError("boom")
