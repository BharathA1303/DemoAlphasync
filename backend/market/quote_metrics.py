"""
Lightweight quote pipeline observability (logging + in-memory counters).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class QuoteMetrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._last_log: dict[str, float] = {}

    def incr(self, name: str, n: int = 1) -> None:
        self._counters[name] += n

    def log(
        self,
        tag: str,
        message: str,
        *,
        level: int = logging.DEBUG,
        throttle_sec: float = 5.0,
    ) -> None:
        now = time.time()
        if throttle_sec > 0:
            last = self._last_log.get(tag, 0.0)
            if now - last < throttle_sec:
                return
            self._last_log[tag] = now
        logger.log(level, f"[{tag}] {message}")

    def record_latency(self, symbol: str, source: str, latency_ms: float) -> None:
        self.incr("quote_ingest_total")
        if latency_ms > 300:
            self.log(
                "QUOTE_LATENCY",
                f"{symbol} source={source} latency_ms={latency_ms:.0f}",
                level=logging.INFO,
                throttle_sec=10.0,
            )

    def record_stale(self, symbol: str, age_sec: float, tier: str) -> None:
        self.incr("symbol_stale_total")
        self.log(
            "SYMBOL_STALE",
            f"{symbol} tier={tier} stale_age={age_sec:.1f}s",
            level=logging.WARNING,
            throttle_sec=15.0,
        )

    def record_recovery(self, symbol: str, reason: str) -> None:
        self.incr("quote_recovery_total")
        self.log(
            "QUOTE_RECOVERY",
            f"{symbol} reason={reason}",
            level=logging.INFO,
            throttle_sec=5.0,
        )

    def record_queue_depth(self, depth: int) -> None:
        self.incr("queue_depth_samples")
        if depth >= 150:
            self.log(
                "QUEUE_DEPTH",
                f"depth={depth}",
                level=logging.WARNING,
                throttle_sec=3.0,
            )

    def record_shed(self, symbol: str, tier: str) -> None:
        self.incr("ws_backpressure_shed")
        self.log(
            "WS_BACKPRESSURE",
            f"shed emit symbol={symbol} tier={tier}",
            level=logging.DEBUG,
            throttle_sec=10.0,
        )

    def record_hot(self, symbol: str) -> None:
        self.incr("hot_symbol_updates")

    def snapshot(self) -> dict[str, Any]:
        return dict(self._counters)


quote_metrics = QuoteMetrics()
