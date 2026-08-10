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

            base_symbol = canonical.replace(".NS", "").replace(".BO", "").split(":")[-1].upper()

            # PriceData.symbol is NOT unique per instrument: the equity
            # ("RELIANCE", segment=EQ), its futures contract, and every
            # option strike/expiry combo (segment=FUT/OPT) can all share the
            # same base symbol string. Without a segment filter the query
            # below could match an option row (price ~tens of rupees) as the
            # "previous close" for a ~3000-4000 rupee equity, producing a
            # nonsensical >50,000% change (the RELIANCE +59764% incident).
            # Always scope to the EQ segment here since this cache is only
            # ever consulted for equity/index/commodity canonicals (NFO/BFO
            # derivative ticks carry their own contract-specific symbol
            # strings like "RELIANCEFUT", not the bare base symbol, so they
            # naturally fall through to the hash-based fallback instead).
            segment = "EQ"

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
                        PriceData.segment == segment,
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
                            PriceData.segment == segment,
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

        if prev_close == lp or prev_close <= 0 or prev_close > lp * 3 or prev_close < lp / 3:
            try:
                from data_layer.simulator.brownian_bridge import _resolve_realistic_base_price
                base_ref = _resolve_realistic_base_price(base_symbol)
                if base_ref > 0 and (lp / 3 <= base_ref <= lp * 3):
                    prev_close = base_ref
            except Exception:
                pass

        if prev_close <= 0 or prev_close > lp * 3 or prev_close < lp / 3:
            logger.warning(
                f"MarketPublisher: implausible prev_close={prev_close} for {canonical} "
                f"(live={lp}); falling back to live price as reference."
            )
            prev_close = lp

        self._prev_close_cache[canonical] = prev_close
        return prev_close

    async def publish_tick(self, tick: dict) -> None:
        """
        Normalize and publish a single tick.
        """
        canonical = tick["symbol"]
        exchange = tick.get("exchange", "NSE")
        lp = tick["price"]
        session_rollover = bool(tick.get("session_rollover"))

        # Check if price or volume changed
        prev_cache = self._price_cache.get(canonical, {})
        _changed = prev_cache.get("price") != lp or prev_cache.get("volume") != tick.get("volume", 0)

        prev_close = await self._get_prev_close(canonical, exchange, lp)

        # On a session rollover, today's running open/high/low must reset to
        # the new session's own price rather than carry over the previous
        # session's — otherwise a symbol's displayed day-range would keep
        # reflecting yesterday's (or Friday's) high/low after the date has
        # already moved on.
        running_open = lp if session_rollover else prev_cache.get("open", lp)
        running_high = lp if session_rollover else max(lp, prev_cache.get("high", lp))
        running_low = lp if session_rollover else min(lp, prev_cache.get("low", lp))

        # Build canonical quote dictionary
        quote = {
            "symbol": canonical,
            "instrument_token": canonical,
            "name": canonical,
            "price": lp,
            "change": round(lp - prev_close, 2),
            "change_percent": round(((lp - prev_close) / prev_close * 100.0) if prev_close else 0.0, 2),
            "open": running_open,
            "high": running_high,
            "low": running_low,
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
            # Tags the first quote of a new trading session so the frontend
            # chart can render a real gap instead of stitching sessions
            # together — see InternalSimProvider._handle_sim_message and
            # LiveChart.jsx's live-tick handler.
            "session_rollover": session_rollover,
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
