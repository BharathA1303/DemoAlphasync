# market_publisher.py - Dispatch ticks to QuoteCoordinator and EventBus
import logging
import asyncio
from typing import Dict, Any

from core.event_bus import event_bus, Event, EventType

logger = logging.getLogger(__name__)

class MarketPublisher:
    """
    Normalizes ticks into the canonical Quote format and publishes them.
    Funnels equity and commodity ticks to QuoteCoordinator,
    and derivative ticks directly to the EventBus.
    """

    def __init__(self):
        self._price_cache: Dict[str, dict] = {}
        self._prev_close_cache: Dict[str, float] = {}
        self._redis = None

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    async def _get_prev_close(self, canonical: str, exchange: str, lp: float) -> float:
        """Resolve and cache the real previous-trading-day close for a
        symbol, used as the reference price for change/change_percent.

        Without this, the FIRST tick for a symbol had no prior entry in
        `_price_cache`, so `prev_cache.get("close", lp)` fell back to the
        tick's own current price — making every symbol's displayed change
        exactly 0.00 (0.00%) on first tick, and (since that bogus "close"
        was then cached and reused as the reference for every later tick)
        every subsequent update showed only the last single tick's delta
        instead of a real day-over-day change. Looked up once per symbol
        per process lifetime, not per tick.
        """
        cached = self._prev_close_cache.get(canonical)
        if cached is not None:
            return cached

        prev_close = lp  # Fallback if no prior EOD row exists (e.g. brand-new symbol).
        try:
            from sqlalchemy import select
            from database.connection import async_session
            from data_layer.db.models import PriceData

            base_symbol = canonical.split(".")[0].upper()
            async with async_session() as db:
                # The most recent PriceData row for this symbol IS the
                # session's own replay day (its EOD close is what the
                # Brownian-bridge path was generated from) - that's the
                # day currently ticking, not the "previous" day. Skip it
                # (OFFSET 1) to get the real prior trading day's close, the
                # correct reference for change/change_percent.
                stmt = (
                    select(PriceData.close)
                    .where(
                        PriceData.exchange == exchange.upper(),
                        PriceData.symbol == base_symbol,
                        PriceData.superseded_at.is_(None),
                    )
                    .order_by(PriceData.market_timestamp.desc())
                    .offset(1)
                    .limit(1)
                )
                result = await db.execute(stmt)
                row = result.scalar_one_or_none()
                if row is not None:
                    prev_close = float(row)
                else:
                    # Only one EOD row exists for this symbol (e.g. a
                    # freshly seeded symbol with no history yet) - fall
                    # back to that single row's close rather than the
                    # live tick price, since it's still a real anchor.
                    stmt_only = (
                        select(PriceData.close)
                        .where(
                            PriceData.exchange == exchange.upper(),
                            PriceData.symbol == base_symbol,
                            PriceData.superseded_at.is_(None),
                        )
                        .order_by(PriceData.market_timestamp.desc())
                        .limit(1)
                    )
                    only_result = await db.execute(stmt_only)
                    only_row = only_result.scalar_one_or_none()
                    if only_row is not None:
                        prev_close = float(only_row)
        except Exception as e:
            logger.debug(f"MarketPublisher: prev_close lookup failed for {canonical}: {e}")

        self._prev_close_cache[canonical] = prev_close
        return prev_close

    async def publish_tick(self, tick: dict) -> None:
        """
        Normalize and publish a single tick.
        """
        canonical = tick["symbol"]
        exchange = tick.get("exchange", "NSE")
        lp = tick["price"]

        # Check if price or volume changed
        prev_cache = self._price_cache.get(canonical, {})
        _changed = prev_cache.get("price") != lp or prev_cache.get("volume") != tick.get("volume", 0)

        prev_close = await self._get_prev_close(canonical, exchange, lp)

        # Build canonical quote dictionary
        quote = {
            "symbol": canonical,
            "instrument_token": canonical,
            "name": canonical,
            "price": lp,
            "change": round(lp - prev_close, 2),
            "change_percent": round(((lp - prev_close) / prev_close * 100.0) if prev_close else 0.0, 2),
            "open": prev_cache.get("open", lp),
            "high": max(lp, prev_cache.get("high", lp)),
            "low": min(lp, prev_cache.get("low", lp)),
            "close": prev_close,
            "prev_close": prev_close,
            "volume": tick.get("volume", 0),
            "bid_price": tick.get("bid_price") or lp,
            "ask_price": tick.get("ask_price") or lp,
            "bid_qty": tick.get("bid_qty") or 0,
            "ask_qty": tick.get("ask_qty") or 0,
            "oi": tick.get("oi") or 0,
            "market_cap": 0,
            "exchange": exchange,
            "timestamp": tick["timestamp"],  # Matches the simulation clock
            "last_trade_time": tick["timestamp"],
            "source": "live_ws",  # Disguise as live_ws for downstream pipelines
        }

        # Update local cache
        self._price_cache[canonical] = quote

        # Dispatch based on asset class
        if exchange in ("NFO", "BFO"):
            # Derivative contract tick -> Emit FUTURES_QUOTE on the EventBus
            if _changed:
                try:
                    futures_quote = {
                        "contract_symbol": canonical,
                        "exchange": exchange,
                        "token": canonical,
                        "ltp": lp,
                        "bid": quote["bid_price"],
                        "ask": quote["ask_price"],
                        "spread": round(quote["ask_price"] - quote["bid_price"], 2),
                        "volume": quote["volume"],
                        "oi": quote["oi"],
                        "open": quote["open"],
                        "high": quote["high"],
                        "low": quote["low"],
                        "close": quote["close"],
                        "change": quote["change"],
                        "percent_change": quote["change_percent"],
                        "avg_price": lp,
                        "bid_qty": quote["bid_qty"],
                        "ask_qty": quote["ask_qty"],
                        "timestamp": quote["timestamp"],
                    }
                    
                    await event_bus.emit(
                        Event(
                            type=EventType.FUTURES_QUOTE,
                            data=futures_quote,
                            source="live_ws",
                        )
                    )
                except Exception as e:
                    logger.debug(f"MarketPublisher: Failed to emit FUTURES_QUOTE: {e}")
        else:
            # Equity, Index, or Commodity tick -> Route to QuoteCoordinator
            try:
                from providers.contract_symbol_map import mirror_canonicals_for_quote
                from market.quote_coordinator import quote_coordinator

                mirrors = mirror_canonicals_for_quote(canonical)
                
                await quote_coordinator.ingest_equity_quote(
                    canonical,
                    quote,
                    source="live_ws",
                    changed=_changed,
                    mirror_symbols=mirrors,
                    write_redis=bool(self._redis),
                    emit_event=True,
                )
            except Exception as e:
                logger.debug(f"MarketPublisher: QuoteCoordinator ingestion failed: {e}")

market_publisher = MarketPublisher()
