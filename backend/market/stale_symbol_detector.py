"""
Detect stale HOT symbols during open market and trigger safe recovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, List, Optional

from market.quote_metrics import quote_metrics
from market.symbol_priority_engine import PriorityTier, symbol_priority_engine

logger = logging.getLogger(__name__)

# Batched: one call per scan cycle covering every stale symbol found, not
# one call per symbol. With ~100+ HOT-tier symbols and a 1s scan interval,
# a per-symbol callback meant up to ~100 individual resubscribe round-trips
# (each doing its own DB SELECT + session-state read/write) every second -
# real load competing with the actual tick-publishing path for the same
# event loop/DB pool, which starved live tick delivery to the UI even
# though the backend logs looked "busy".
RecoveryCallback = Callable[[List[str], str], Awaitable[None]]


class StaleSymbolDetector:
    # The internal sim's tick clock (SimulatorManager.run_loop) advances and
    # publishes for every subscribed symbol once per second under normal
    # load - a 2.0s staleness threshold left almost no margin, so any
    # transient delay (a heavy batch of active sessions, GC pause, or the
    # resubscribe traffic this detector itself generates) tripped "stale"
    # for much of the HOT tier at once, triggering more resubscribes that
    # further starved the tick loop. 6s gives real margin above the ~1s
    # normal cadence while still catching genuine delivery failures.
    HOT_STALE_SEC = 6.0
    CHECK_INTERVAL_SEC = 1.0
    RECOVERY_COOLDOWN_SEC = 10.0

    def __init__(self) -> None:
        self._running = False
        self._recovery_cb: Optional[RecoveryCallback] = None
        self._last_recovery: dict[str, float] = {}
        self._get_last_tick = None
        self._is_market_open = None

    def configure(
        self,
        *,
        recovery_callback: RecoveryCallback,
        get_last_tick_at,
        is_market_open,
    ) -> None:
        self._recovery_cb = recovery_callback
        self._get_last_tick = get_last_tick_at
        self._is_market_open = is_market_open

    async def run(self) -> None:
        self._running = True
        logger.info("StaleSymbolDetector started")
        while self._running:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"StaleSymbolDetector scan error: {e}")
            await asyncio.sleep(self.CHECK_INTERVAL_SEC)
        logger.info("StaleSymbolDetector stopped")

    async def stop(self) -> None:
        self._running = False

    async def _scan_once(self) -> None:
        if not self._is_market_open or not self._is_market_open():
            return
        if not self._get_last_tick:
            return

        now = time.time()
        stale_symbols: List[str] = []
        max_age = 0.0
        for symbol in symbol_priority_engine.list_by_tier(PriorityTier.HOT):
            last = self._get_last_tick(symbol)
            if last is None:
                continue
            age = now - last
            if age <= self.HOT_STALE_SEC:
                continue

            quote_metrics.record_stale(symbol, age, PriorityTier.HOT.value)

            cooldown_key = symbol
            if now - self._last_recovery.get(cooldown_key, 0.0) < self.RECOVERY_COOLDOWN_SEC:
                continue
            self._last_recovery[cooldown_key] = now
            stale_symbols.append(symbol)
            max_age = max(max_age, age)

        if not stale_symbols or not self._recovery_cb:
            return

        try:
            await self._recovery_cb(stale_symbols, f"stale_{max_age:.1f}s")
            for symbol in stale_symbols:
                quote_metrics.record_recovery(symbol, "stale_detector")
        except Exception as e:
            logger.debug(f"Batched recovery failed for {len(stale_symbols)} symbols: {e}")


stale_symbol_detector = StaleSymbolDetector()
