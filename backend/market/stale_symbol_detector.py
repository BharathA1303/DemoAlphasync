"""
Detect stale HOT symbols during open market and trigger safe recovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from market.quote_metrics import quote_metrics
from market.symbol_priority_engine import PriorityTier, symbol_priority_engine

logger = logging.getLogger(__name__)

RecoveryCallback = Callable[[str, str], Awaitable[None]]


class StaleSymbolDetector:
    HOT_STALE_SEC = 2.0
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

            if self._recovery_cb:
                try:
                    await self._recovery_cb(symbol, f"stale_{age:.1f}s")
                    quote_metrics.record_recovery(symbol, "stale_detector")
                except Exception as e:
                    logger.debug(f"Recovery failed for {symbol}: {e}")


stale_symbol_detector = StaleSymbolDetector()
