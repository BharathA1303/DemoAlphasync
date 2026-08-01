"""Correlation ID propagation across process boundaries (HTTP -> CommandBus
-> EventBus -> logs).

This module owns the *transport* concern (extracting/injecting the
correlation id at a boundary, e.g. an HTTP header); `shared.logging`
already owns the *context* concern (making the id available to the log
formatter via contextvars). Keeping them separate follows the spec's
directory split between `logging/` and `observability/`.
"""
from app.kernel.ids.generator import default_id_generator
from app.shared.logging.logger import ContextLogger

CORRELATION_ID_HEADER = "X-Correlation-Id"


def extract_or_create_correlation_id(header_value: str | None) -> str:
    """Return `header_value` if a caller supplied one (so a request can be
    traced end-to-end across an external boundary), otherwise mint a new
    correlation id for this request."""
    if header_value and header_value.strip():
        return header_value.strip()
    return default_id_generator.generate("corr")


def bind_correlation_id(correlation_id: str, session_id: str | None = None) -> None:
    """Bind the correlation id (and optional session id) to the current
    execution context so every log line emitted during this request/task
    carries it automatically."""
    ContextLogger.set_context(correlation_id=correlation_id, session_id=session_id)
