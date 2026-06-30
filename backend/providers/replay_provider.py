# replay_provider.py - MarketProvider implementation for simulated tick replay
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from providers.base import MarketProvider, ProviderHealth, ProviderStatus, Quote
from market_data.replay.replay_engine import replay_engine
from market_data.replay.simulation_clock import simulation_clock
from market_data.replay.market_publisher import market_publisher

logger = logging.getLogger(__name__)


class ReplayProvider(MarketProvider):
    """
    ReplayProvider feeds simulated ticks into the QuoteCoordinator and EventBus.
    It acts exactly like a live broker WebSocket provider.
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._status = ProviderStatus.DISCONNECTED
        self._price_cache: Dict[str, dict] = {}
        self._subscribed_symbols: set[str] = set()
        self._running = False
        self._last_tick_at: Optional[float] = None
        self._started_at: Optional[float] = None

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize the connection to the replay engine."""
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._status = ProviderStatus.CONNECTED

        # Set redis client on the publisher
        market_publisher.set_redis(self._redis)

        # ── Share price cache with MarketPublisher ──────────────────────
        # MarketPublisher.publish_tick() stores every tick in its own
        # _price_cache.  Point our _price_cache at the same dict so that
        # MarketDataWorker.get_batch_quotes() sees live data immediately.
        self._price_cache = market_publisher._price_cache

        # Start the global replay engine
        await replay_engine.start()
        logger.info("ReplayProvider started and ReplayEngine initialized")


    async def stop(self) -> None:
        """Stop the provider."""
        self._running = False
        self._status = ProviderStatus.DISCONNECTED
        await replay_engine.stop()
        logger.info("ReplayProvider stopped")

    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to a list of symbols in the replay engine."""
        clean_symbols = [str(s).strip().upper() for s in symbols if s]
        self._subscribed_symbols.update(clean_symbols)
        replay_engine.subscribe(clean_symbols)

    async def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from a list of symbols in the replay engine."""
        clean_symbols = [str(s).strip().upper() for s in symbols if s]
        for s in clean_symbols:
            self._subscribed_symbols.discard(s)
        replay_engine.unsubscribe(clean_symbols)

    def get_subscribed_symbols(self) -> set:
        """Return the set of currently subscribed symbols."""
        return set(self._subscribed_symbols)

    async def get_quote(self, symbol: str) -> Optional[dict]:
        """Get the latest quote for a symbol from the local cache."""
        sym = str(symbol).strip().upper()
        return self._price_cache.get(sym)

    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        """Get the latest quotes for multiple symbols."""
        results = {}
        for sym in symbols:
            clean_sym = str(sym).strip().upper()
            quote = self._price_cache.get(clean_sym)
            if quote:
                results[clean_sym] = quote
        return results

    async def get_historical_data(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> list:
        """
        Generates realistic simulated historical OHLCV candles using a random walk.
        This ensures that when a user clicks a symbol, the chart immediately loads.
        """
        import random
        from datetime import datetime, timedelta, timezone

        # Determine base price based on symbol name
        base_price = 100.0
        sym = symbol.upper().strip()
        if sym == "^NSEI" or "NIFTY" in sym:
            base_price = 22000.0
        elif sym == "^NSEBANK" or "BANKNIFTY" in sym:
            base_price = 47000.0
        elif sym == "^BSESN" or "SENSEX" in sym:
            base_price = 72000.0
        elif "RELIANCE" in sym:
            base_price = 2500.0
        elif "TCS" in sym:
            base_price = 3800.0
        elif "HDFCBANK" in sym:
            base_price = 1450.0
        elif "INFY" in sym:
            base_price = 1500.0
        elif "SBIN" in sym:
            base_price = 750.0
        elif sym in ("GOLD", "SILVER", "CRUDEOIL"):
            if sym == "GOLD":
                base_price = 65000.0
            elif sym == "SILVER":
                base_price = 72000.0
            else:
                base_price = 6500.0
        else:
            random.seed(sym)
            base_price = random.uniform(100.0, 2000.0)
            random.seed()

        # Determine number of candles and time delta based on interval and period
        num_candles = 300
        delta = timedelta(days=1)
        
        intraday_intervals = {
            "1m": timedelta(minutes=1),
            "2m": timedelta(minutes=2),
            "3m": timedelta(minutes=3),
            "5m": timedelta(minutes=5),
            "10m": timedelta(minutes=10),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "2h": timedelta(hours=2),
            "4h": timedelta(hours=4),
        }

        if interval in intraday_intervals:
            delta = intraday_intervals[interval]
            # Match reasonable counts for intraday
            if interval == "1m":
                num_candles = 375  # ~1 trading day of minutes
            elif interval == "5m":
                num_candles = 300  # ~4 trading days
            else:
                num_candles = 200
        else:
            delta = timedelta(days=1)
            num_candles = 250  # ~1 year of daily trading candles

        # Generate candles going backwards from current simulation clock time
        now = simulation_clock.now()
        candles = []
        current_price = base_price
        volatility = 0.005 if interval == "1d" else 0.001

        for i in range(num_candles):
            t = now - (num_candles - i) * delta
            # Skip weekends for daily candles
            if interval == "1d" and t.weekday() >= 5:
                continue
                
            # Random walk
            change = current_price * random.normalvariate(0, volatility)
            open_price = current_price
            close_price = current_price + change
            high_price = max(open_price, close_price) + (current_price * abs(random.normalvariate(0, volatility * 0.5)))
            low_price = min(open_price, close_price) - (current_price * abs(random.normalvariate(0, volatility * 0.5)))
            
            # Keep prices positive
            if low_price <= 0:
                low_price = 0.05
            if open_price <= 0:
                open_price = 0.05
            if close_price <= 0:
                close_price = 0.05
            if high_price <= 0:
                high_price = 0.05

            candles.append({
                "time": int(t.timestamp()),
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2),
                "volume": random.randint(1000, 500000),
            })
            current_price = close_price

        return candles

    async def health(self) -> ProviderHealth:
        """Get the health status of the provider."""
        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        return ProviderHealth(
            status=self._status,
            provider_name="ReplayProvider",
            subscribed_symbols=len(self._subscribed_symbols),
            last_tick_at=datetime.fromtimestamp(self._last_tick_at, timezone.utc).isoformat() if self._last_tick_at else None,
            uptime_seconds=uptime,
            reconnect_count=0,
            error=None,
        )

    # ── Internal Tick Handler ───────────────────────────────────────

    def _on_engine_tick(self, tick: dict) -> None:
        """Callback triggered by ReplayEngine on every tick."""
        if not self._running:
            return

        self._last_tick_at = time.time()
        canonical = tick["symbol"]
        exchange = tick["exchange"]
        lp = tick["price"]
        
        # Check if price changed
        prev_cache = self._price_cache.get(canonical, {})
        _changed = prev_cache.get("price") != lp or prev_cache.get("volume") != tick["volume"]

        # 1. Build canonical quote dictionary
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
            "volume": tick["volume"],
            "bid_price": tick["bid_price"] or lp,
            "ask_price": tick["ask_price"] or lp,
            "bid_qty": tick["bid_qty"],
            "ask_qty": tick["ask_qty"],
            "oi": tick["oi"],
            "market_cap": 0,
            "exchange": exchange,
            "timestamp": tick["timestamp"],  # Matches the simulation clock
            "last_trade_time": tick["timestamp"],
            "source": "live_ws",  # Disguise as live_ws for the downstream pipeline
        }

        # Update local cache
        self._price_cache[canonical] = quote

        # 2. Dispatch based on asset class
        if exchange in ("NFO", "BFO"):
            # Derivative contract tick -> Emit FUTURES_QUOTE on the EventBus
            if _changed:
                try:
                    from core.event_bus import event_bus, Event, EventType

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
                    
                    # Run on event loop
                    asyncio.create_task(
                        event_bus.emit(
                            Event(
                                type=EventType.FUTURES_QUOTE,
                                data=futures_quote,
                                source="live_ws",
                            )
                        )
                    )
                except Exception as e:
                    logger.debug(f"ReplayProvider: Failed to emit FUTURES_QUOTE: {e}")
        else:
            # Equity, Index, or Commodity tick -> Route to QuoteCoordinator
            try:
                from providers.symbol_mapper import mirror_canonicals_for_quote
                from market.quote_coordinator import quote_coordinator

                mirrors = mirror_canonicals_for_quote(canonical)
                
                # We schedule the async call on the event loop
                asyncio.create_task(
                    quote_coordinator.ingest_equity_quote(
                        canonical,
                        quote,
                        source="live_ws",
                        changed=_changed,
                        mirror_symbols=mirrors,
                        write_redis=bool(self._redis),
                        emit_event=True,
                    )
                )
            except Exception as e:
                logger.debug(f"ReplayProvider: QuoteCoordinator ingestion failed: {e}")
