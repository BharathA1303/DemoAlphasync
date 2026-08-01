import contextvars
import json
import logging
from typing import Any

_correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
_session_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)


class ContextLogger:
    """Correlation Context Manager for tracing logs across execution boundaries."""

    @staticmethod
    def set_context(correlation_id: str, session_id: str | None = None) -> None:
        _correlation_id_ctx.set(correlation_id)
        if session_id:
            _session_id_ctx.set(session_id)

    @staticmethod
    def get_context() -> dict[str, str | None]:
        return {
            "correlation_id": _correlation_id_ctx.get(),
            "session_id": _session_id_ctx.get(),
        }

    @staticmethod
    def clear_context() -> None:
        _correlation_id_ctx.set(None)
        _session_id_ctx.set(None)


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter including mandatory correlation_id and session_id context."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = ContextLogger.get_context()
        log_payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": ctx["correlation_id"],
            "session_id": ctx["session_id"],
        }
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]
