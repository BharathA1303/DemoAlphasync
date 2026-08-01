"""Latency measurement against the non-functional requirement thresholds
(API < 50ms, paper order < 10ms). This module only measures and logs a
breach — it does not alter behavior — so it is safe to wrap any code path
without changing its semantics.
"""
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LatencyBudget:
    """A named latency threshold in milliseconds."""

    name: str
    max_milliseconds: float


API_LATENCY_BUDGET = LatencyBudget(name="api_request", max_milliseconds=50.0)
PAPER_ORDER_LATENCY_BUDGET = LatencyBudget(name="paper_order", max_milliseconds=10.0)


@contextmanager
def measure_latency(budget: LatencyBudget) -> Iterator[None]:
    """Context manager that logs a WARNING if the wrapped block exceeds
    `budget.max_milliseconds`. Always logs the observed latency at DEBUG
    regardless of outcome, so budgets can be tuned from real data."""
    started_at = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if elapsed_ms > budget.max_milliseconds:
            logger.warning(
                f"Latency budget exceeded for '{budget.name}': "
                f"{elapsed_ms:.3f}ms > {budget.max_milliseconds:.3f}ms"
            )
        else:
            logger.debug(f"Latency for '{budget.name}': {elapsed_ms:.3f}ms")
