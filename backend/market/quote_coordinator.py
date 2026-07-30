"""
Central quote authority — single ingress for live equity quotes (Phase 2).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from core.event_bus import Event, EventType, event_bus
from market.freshness_engine import enrich_quote_metadata
from market.quote_metrics import quote_metrics
from market.quote_router import normalize_for_storage, should_accept_overwrite
from market.symbol_priority_engine import PriorityTier, symbol_priority_engine

logger = logging.getLogger(__name__)

QUEUE_WARN = 150
QUEUE_SHED = 250


def _market_open() -> bool:
    try:
        from engines.market_session import market_session, MarketState

        return market_session.get_current_state() == MarketState.OPEN
    except Exception:
        return True


class QuoteCoordinator:
    """
    Authoritative in-process quote registry + safe Redis/EventBus egress.
    Does not replace alphasync:price:* keys — augments with meta hashes.
    """

    def __init__(self) -> None:
        self._authority: dict[str, dict] = {}
        self._sequences: dict[str, int] = {}
        self._last_tick_at: dict[str, float] = {}
        self._last_emit_at: dict[str, float] = {}
        self._last_redis_write: dict[str, float] = {}
        self._recovery_handlers: list = []
        self._started_at = time.time()

    def get_authority_quotes(self) -> dict[str, dict]:
        return dict(self._authority)

    def get_last_tick_at(self, symbol: str) -> Optional[float]:
        return self._last_tick_at.get(str(symbol or "").strip().upper())

    def register_hot(self, symbol: str) -> None:
        symbol_priority_engine.register(symbol, PriorityTier.HOT)

    def register_warm(self, symbol: str) -> None:
        symbol_priority_engine.register(symbol, PriorityTier.WARM)

    def register_recovery_handler(self, handler) -> None:
        self._recovery_handlers.append(handler)

    async def ingest_equity_quote(
        self,
        symbol: str,
        quote: dict,
        *,
        source: str = "live_ws",
        changed: bool = True,
        mirror_symbols: Optional[list[str]] = None,
        write_redis: bool = True,
        emit_event: bool = True,
    ) -> bool:
        """
        Ingest one equity quote. Returns True if authority updated.
        Futures NFO ticks should continue using FUTURES_QUOTE path separately.
        """
        sym = str(symbol or quote.get("symbol") or "").strip().upper()
        if not sym:
            return False

        market_open = _market_open()
        existing = self._authority.get(sym)
        seq = self._sequences.get(sym, 0) + 1

        candidate = normalize_for_storage({**quote, "symbol": sym})
        if not should_accept_overwrite(existing, candidate, source=source, market_open=market_open):
            quote_metrics.incr("quote_overwrite_rejected")
            return False

        now = time.time()
        enriched = enrich_quote_metadata(
            sym,
            candidate,
            source=source,
            sequence=seq,
            market_open=market_open,
            last_tick_at=now,
        )
        self._sequences[sym] = seq
        self._authority[sym] = enriched
        self._last_tick_at[sym] = now
        symbol_priority_engine.touch(sym)

        tier = symbol_priority_engine.get_tier(sym)
        if tier == PriorityTier.HOT:
            quote_metrics.record_hot(sym)

        if write_redis:
            await self._write_redis(sym, enriched, mirror_symbols or [])

        if emit_event and changed:
            await self._maybe_emit(sym, enriched, tier)

        # Build intraday OHLCV buffers for charts (indices need tick-built bar volume).
        try:
            from workers.market_worker import market_data_worker

            market_data_worker._update_candles(sym, enriched)
        except Exception:
            pass

        # Mirror aliases share authority entries
        for alias in mirror_symbols or []:
            if not alias or alias == sym:
                continue
            alias_upper = str(alias).strip().upper()
            alias_quote = {**enriched, "symbol": alias_upper}
            if should_accept_overwrite(
                self._authority.get(alias_upper),
                alias_quote,
                source=source,
                market_open=market_open,
            ):
                self._authority[alias_upper] = alias_quote
                self._last_tick_at[alias_upper] = now

        quote_metrics.record_latency(sym, source, (time.time() - now) * 1000)
        return True

    async def _write_redis(self, symbol: str, quote: dict, mirrors: list[str]) -> None:
        try:
            from cache.redis_client import get_redis

            cache = await get_redis()
            if not cache.is_connected:
                return

            t0 = time.time()
            if mirrors:
                await cache.set_prices_mirrored(symbol, quote, mirrors)
            else:
                await cache.set_price(symbol, quote)

            meta = {
                "freshness": quote.get("freshness_state"),
                "source": quote.get("source"),
                "seq": str(quote.get("sequence", 0)),
                "priority": quote.get("priority_tier"),
                "last_ws_emit": str(self._last_emit_at.get(symbol, 0)),
                "stale_age": "0",
            }
            await cache.set_quote_meta(symbol, meta)
            for alias in mirrors:
                if alias and alias != symbol:
                    await cache.set_quote_meta(alias, meta)

            self._last_redis_write[symbol] = time.time()
            latency_ms = (time.time() - t0) * 1000
            if latency_ms > 50:
                quote_metrics.log(
                    "REDIS_WRITE_LATENCY",
                    f"{symbol} {latency_ms:.0f}ms",
                    throttle_sec=20.0,
                )
        except Exception as e:
            logger.debug(f"Coordinator Redis write failed for {symbol}: {e}")

    def _should_throttle_emit(self, symbol: str, tier: PriorityTier) -> bool:
        interval = symbol_priority_engine.emit_interval_sec(tier)
        if interval <= 0:
            return False
        last = self._last_emit_at.get(symbol, 0.0)
        return (time.time() - last) < interval

    async def _maybe_emit(self, symbol: str, quote: dict, tier: PriorityTier) -> None:
        qs = event_bus.get_stats().get("queue_size", 0)
        quote_metrics.record_queue_depth(qs)

        if qs >= QUEUE_SHED and tier == PriorityTier.COLD:
            quote_metrics.record_shed(symbol, tier.value)
            return

        if self._should_throttle_emit(symbol, tier):
            return

        self._last_emit_at[symbol] = time.time()
        try:
            from market.quote_metrics import quote_metrics as m

            m.incr("price_updated_emits")
        except Exception:
            pass

        await event_bus.emit(
            Event(
                type=EventType.PRICE_UPDATED,
                data={"symbol": symbol, "quote": quote},
                source=str(quote.get("source") or "coordinator"),
            )
        )

        # Update meta last emit
        try:
            from cache.redis_client import get_redis

            cache = await get_redis()
            if cache.is_connected:
                await cache.set_quote_meta(
                    symbol,
                    {
                        "last_ws_emit": str(self._last_emit_at[symbol]),
                        "freshness": quote.get("freshness_state"),
                    },
                )
        except Exception:
            pass

    def get_tracked_symbols(self) -> set[str]:
        """Symbols with in-memory quote authority (for EOD reconciliation)."""
        return set(self._authority.keys())

    async def recover_symbol(self, symbol: str, reason: str) -> None:
        """Stale recovery — refresh provider subscription + optional REST."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return

        for handler in self._recovery_handlers:
            try:
                result = handler(sym, reason)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.debug(f"Recovery handler error for {sym}: {e}")

        try:
            from services.market_data import get_system_quote_safe

            refreshed = await get_system_quote_safe(sym)
            if refreshed:
                await self.ingest_equity_quote(
                    sym,
                    refreshed,
                    source="poll",
                    changed=True,
                    emit_event=True,
                )
        except Exception as e:
            logger.debug(f"Coordinator REST recovery failed for {sym}: {e}")


quote_coordinator = QuoteCoordinator()
