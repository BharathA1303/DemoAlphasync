"""
Periodic compressed live snapshot for fast frontend hydration after reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Optional

from market.symbol_priority_engine import PriorityTier, symbol_priority_engine

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = "alphasync:quote:snapshot:live"
SNAPSHOT_INTERVAL_SEC = 5.0
SNAPSHOT_TTL_SEC = 30


class QuoteSnapshotEngine:
    def __init__(self) -> None:
        self._running = False
        self._get_quotes: Optional[Callable[[], dict]] = None

    def configure(self, *, get_authority_quotes: Callable[[], dict]) -> None:
        self._get_quotes = get_authority_quotes

    async def run(self) -> None:
        self._running = True
        logger.info("QuoteSnapshotEngine started")
        while self._running:
            try:
                await self._persist_snapshot()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"QuoteSnapshotEngine error: {e}")
            await asyncio.sleep(SNAPSHOT_INTERVAL_SEC)
        logger.info("QuoteSnapshotEngine stopped")

    async def stop(self) -> None:
        self._running = False

    async def _persist_snapshot(self) -> None:
        if not self._get_quotes:
            return
        authority = self._get_quotes() or {}
        if not authority:
            return

        payload = {}
        for sym, quote in authority.items():
            tier = symbol_priority_engine.get_tier(sym)
            if tier == PriorityTier.COLD and len(payload) > 400:
                continue
            payload[sym] = {
                "price": quote.get("price") or quote.get("ltp"),
                "change": quote.get("change"),
                "change_percent": quote.get("change_percent"),
                "freshness_state": quote.get("freshness_state"),
                "source": quote.get("source"),
                "sequence": quote.get("sequence"),
                "timestamp": quote.get("timestamp"),
            }

        try:
            from cache.redis_client import get_redis

            cache = await get_redis()
            if cache.is_connected and cache._redis:
                await cache._redis.setex(
                    SNAPSHOT_KEY,
                    SNAPSHOT_TTL_SEC,
                    json.dumps(
                        {"ts": time.time(), "quotes": payload},
                        separators=(",", ":"),
                    ),
                )
        except Exception as e:
            logger.debug(f"Snapshot persist failed: {e}")


quote_snapshot_engine = QuoteSnapshotEngine()
