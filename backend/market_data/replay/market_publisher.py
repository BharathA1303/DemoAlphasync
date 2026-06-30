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
        self._redis = None

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

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

        # Build canonical quote dictionary
        quote = {
            "symbol": canonical,
            "instrument_token": canonical,
            "name": canonical,
            "price": lp,
            "change": round(lp - prev_cache.get("close", lp), 2),
            "change_percent": round(((lp - prev_cache.get("close", lp)) / prev_cache.get("close", lp) * 100.0) if prev_cache.get("close", 0) else 0.0, 2),
            "open": prev_cache.get("open", lp),
            "high": max(lp, prev_cache.get("high", lp)),
            "low": min(lp, prev_cache.get("low", lp)),
            "close": prev_cache.get("close", lp),
            "prev_close": prev_cache.get("close", lp),
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
                from providers.symbol_mapper import mirror_canonicals_for_quote
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
