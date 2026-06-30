"""
Market Data Worker — Background price streaming.

Reads prices from any available ZebuProvider session and emits
PRICE_UPDATED events via the EventBus. Downstream consumers
(WebSocket manager, Order Worker, ZeroLoss) subscribe to these events.

Per-user architecture:
    - No global provider. Worker uses broker_session_manager.get_any_session().
    - If no sessions exist, the worker idles (no data to stream).
    - When a user connects their broker, a session appears and the
      worker resumes streaming.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

from sqlalchemy import text

from database.connection import async_session_factory
from core.event_bus import event_bus, Event, EventType
from engines.market_session import market_session, MarketState
from cache.smart_cache import quote_cache
from config.settings import settings
from providers.symbol_mapper import is_commodity_symbol

logger = logging.getLogger(__name__)


class MarketDataWorker:
    """
    Fetches live prices from any available broker session and emits events.

    Interval adapts to market state:
    - Open:   3 seconds between sweeps
    - Closed: 60 seconds (reduced frequency)
    """

    ACTIVE_INTERVAL = max(0.5, float(settings.WORKER_MARKET_DATA_INTERVAL or 1.0))
    IDLE_INTERVAL = 60  # seconds when market closed
    NO_SESSION_INTERVAL = 10  # seconds when no broker sessions
    # Lower batch size and increase timeout to reduce timeout failures when
    # resolving many symbols or when on-demand REST lookups are required.
    BATCH_SIZE = 16
    BATCH_TIMEOUT_SECONDS = 4.0
    HISTORY_PERSIST_INTERVAL = 15  # seconds
    MAX_CANDLES_1M = 480  # ~1+ trading day
    MAX_CANDLES_5M = 192  # ~4 trading days
    MASTER_RECOVER_COOLDOWN = 30  # seconds
    EMPTY_SWEEP_RECOVER_THRESHOLD = 5
    BATCH_FAIL_RECOVER_THRESHOLD = 8

    def __init__(self):
        self._running = False
        self._subscribed_symbols: set[str] = set()
        self._candle_state: dict[str, dict[str, dict]] = {"1m": {}, "5m": {}}
        self._history_buffers: dict[str, dict[str, list[dict]]] = {"1m": {}, "5m": {}}
        self._dirty_history_symbols: set[str] = set()
        self._last_history_persist_ts = 0.0
        self._last_market_state = None
        self._last_master_recover_attempt = 0.0
        self._consecutive_empty_sweeps = 0
        self._consecutive_batch_failures = 0
        self._stats = {"sweeps": 0, "emits": 0, "no_session_waits": 0}

    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to the streaming set."""
        self._subscribed_symbols.add(symbol)

    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from the streaming set."""
        self._subscribed_symbols.discard(symbol)

    def get_stats(self) -> dict:
        """Return worker stats."""
        return {
            **self._stats,
            "symbols": list(self._subscribed_symbols),
            "symbol_count": len(self._subscribed_symbols),
        }

    @staticmethod
    def _chunked(items: list[str], size: int) -> list[list[str]]:
        return [items[i : i + size] for i in range(0, len(items), size)]

    @staticmethod
    def _build_ticker_items(quotes_by_symbol: dict[str, dict]) -> list[dict]:
        from services.market_data import (
            POPULAR_INDIAN_STOCKS,
            INDIAN_INDICES,
            POPULAR_COMMODITIES,
        )

        ticker_items: list[dict] = []

        for idx in INDIAN_INDICES:
            q = quotes_by_symbol.get(idx["symbol"])
            if q:
                item = dict(q)
                item["name"] = idx["name"]
                item["kind"] = "index"
                ticker_items.append(item)

        for stock in POPULAR_INDIAN_STOCKS:
            q = quotes_by_symbol.get(stock["symbol"])
            if q:
                item = dict(q)
                item["name"] = stock["name"]
                item["kind"] = "stock"
                ticker_items.append(item)

        for comm in POPULAR_COMMODITIES:
            q = quotes_by_symbol.get(comm["symbol"])
            if q:
                item = dict(q)
                item["name"] = comm["name"]
                item["kind"] = "commodity"
                item["exchange"] = comm["exchange"]
                item["category"] = comm["category"]
                item["unit"] = comm["unit"]
                item["lot"] = comm.get("lot", 1)
                ticker_items.append(item)

        return ticker_items

    async def _load_watchlist_symbols(self) -> set[str]:
        """Load all unique watchlist symbols from the database."""
        symbols: set[str] = set()
        session = async_session_factory()
        try:
            result = await session.execute(
                text("SELECT DISTINCT UPPER(symbol) AS symbol FROM watchlist_items")
            )
            for row in result.fetchall():
                sym = (row[0] or "").strip().upper()
                if not sym:
                    continue
                symbols.add(sym)
                is_derivative = bool(
                    re.search(r"\d", sym) and re.search(r"(FUT|CE|PE)$", sym)
                )
                if (
                    not sym.startswith("^")
                    and not sym.endswith((".NS", ".BO"))
                    and not is_derivative
                    and not is_commodity_symbol(sym)
                ):
                    symbols.add(f"{sym}.NS")
        except Exception as e:
            logger.debug(f"MarketDataWorker watchlist load failed: {e}")
        finally:
            await session.close()

        return symbols

    async def _publish_quotes(
        self, quotes_by_symbol: dict[str, dict], source: str
    ) -> None:
        if not quotes_by_symbol:
            return

        self._stats["emits"] += len(quotes_by_symbol)

        try:
            from cache.redis_client import set_prices_batch

            await set_prices_batch(quotes_by_symbol)
        except Exception as _re:
            logger.debug(f"Redis batch write skipped ({source}): {_re}")

        now_ts = time.time()
        try:
            from market.quote_coordinator import quote_coordinator
        except Exception:
            quote_coordinator = None

        for symbol, normalized in quotes_by_symbol.items():
            quote_cache.set(f"q:{symbol}", normalized, ttl=5)
            self._update_candles(symbol, normalized)

            skip_emit = False
            if source != "live_ws":
                cached_src = normalized.get("source", "")
                cached_ts = normalized.get("timestamp", "")
                if cached_src == "live_ws" and cached_ts:
                    try:
                        from datetime import datetime as _dt
                        ts_dt = _dt.fromisoformat(str(cached_ts).replace("Z", "+00:00"))
                        age = now_ts - ts_dt.timestamp()
                        if age < 2.0:
                            skip_emit = True
                    except Exception:
                        pass

            if quote_coordinator is not None:
                await quote_coordinator.ingest_equity_quote(
                    symbol,
                    normalized,
                    source=source,
                    changed=not skip_emit,
                    emit_event=not skip_emit,
                )
            elif not skip_emit:
                await event_bus.emit(
                    Event(
                        type=EventType.PRICE_UPDATED,
                        data={"symbol": symbol, "quote": normalized},
                        source=source,
                    )
                )

        now = time.time()
        if (
            self._dirty_history_symbols
            and (now - self._last_history_persist_ts) >= self.HISTORY_PERSIST_INTERVAL
        ):
            await self._persist_history_to_redis(set(self._dirty_history_symbols))
            self._dirty_history_symbols.clear()
            self._last_history_persist_ts = now

    @staticmethod
    def _parse_quote_ts(quote: dict) -> int:
        raw = quote.get("timestamp") or quote.get("last_trade_time") or quote.get("ft")
        if raw in (None, ""):
            return int(time.time())

        try:
            numeric = float(raw)
            if numeric > 1_000_000_000_000:
                numeric /= 1000.0
            return int(numeric) if numeric > 0 else int(time.time())
        except (TypeError, ValueError):
            pass

        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return int(time.time())

    @staticmethod
    def _interval_seconds(interval: str) -> int:
        return 60 if interval == "1m" else 300

    @classmethod
    def _max_candles(cls, interval: str) -> int:
        return cls.MAX_CANDLES_1M if interval == "1m" else cls.MAX_CANDLES_5M

    @staticmethod
    def _bucket_start(ts: int, interval_seconds: int) -> int:
        return int(ts // interval_seconds) * interval_seconds

    def _append_history_candle(self, symbol: str, interval: str, candle: dict) -> None:
        history_map = self._history_buffers[interval]
        candles = history_map.setdefault(symbol, [])

        persisted = {
            "time": int(candle["time"]),
            "open": round(float(candle["open"]), 2),
            "high": round(float(candle["high"]), 2),
            "low": round(float(candle["low"]), 2),
            "close": round(float(candle["close"]), 2),
            "volume": max(0, int(float(candle.get("volume", 0) or 0))),
        }

        if candles and candles[-1]["time"] == persisted["time"]:
            candles[-1] = persisted
        else:
            candles.append(persisted)

        max_len = self._max_candles(interval)
        if len(candles) > max_len:
            del candles[: len(candles) - max_len]

    def _update_interval_candle(
        self,
        symbol: str,
        interval: str,
        price: float,
        ts: int,
        cumulative_volume: float | None = None,
    ) -> None:
        interval_seconds = self._interval_seconds(interval)
        bucket = self._bucket_start(ts, interval_seconds)

        active_map = self._candle_state[interval]
        active = active_map.get(symbol)

        if cumulative_volume is not None:
            try:
                cumulative_volume = float(cumulative_volume)
                if cumulative_volume < 0:
                    cumulative_volume = None
            except (TypeError, ValueError):
                cumulative_volume = None

        if not active or active["time"] != bucket:
            prev_last_cum = None
            if active:
                prev_last_cum = active.get("_last_cum_volume")
                self._append_history_candle(symbol, interval, active)

            base_cum = None
            next_volume = 0
            if cumulative_volume is not None:
                if prev_last_cum is None:
                    base_cum = cumulative_volume
                    next_volume = 0
                else:
                    base_cum = prev_last_cum
                    next_volume = max(0, int(cumulative_volume - prev_last_cum))

            active_map[symbol] = {
                "time": bucket,
                "open": round(price, 2),
                "high": round(price, 2),
                "low": round(price, 2),
                "close": round(price, 2),
                "volume": next_volume,
                "_base_cum_volume": base_cum,
                "_last_cum_volume": cumulative_volume,
            }
            return

        active["high"] = round(max(float(active["high"]), price), 2)
        active["low"] = round(min(float(active["low"]), price), 2)
        active["close"] = round(price, 2)

        if cumulative_volume is not None:
            base_cum = active.get("_base_cum_volume")
            if base_cum is None:
                current_volume = int(float(active.get("volume", 0) or 0))
                base_cum = max(0.0, cumulative_volume - current_volume)

            if cumulative_volume < base_cum:
                base_cum = cumulative_volume

            active["_base_cum_volume"] = base_cum
            active["_last_cum_volume"] = cumulative_volume
            active["volume"] = max(0, int(cumulative_volume - base_cum))

    def _update_candles(self, symbol: str, quote: dict) -> None:
        try:
            price = float(quote.get("price") or 0)
        except (TypeError, ValueError):
            return
        if price <= 0:
            return

        cumulative_volume = quote.get("volume")
        try:
            cumulative_volume = (
                float(cumulative_volume) if cumulative_volume is not None else None
            )
        except (TypeError, ValueError):
            cumulative_volume = None

        ts = self._parse_quote_ts(quote)
        self._update_interval_candle(symbol, "1m", price, ts, cumulative_volume)
        self._update_interval_candle(symbol, "5m", price, ts, cumulative_volume)
        self._dirty_history_symbols.add(symbol)

    def _current_and_history_candles(self, symbol: str, interval: str) -> list[dict]:
        candles = list(self._history_buffers[interval].get(symbol, []))
        active = self._candle_state[interval].get(symbol)
        if active:
            candles.append(dict(active))

        # de-duplicate by candle start time and keep order
        merged: dict[int, dict] = {}
        for c in candles:
            merged[int(c["time"])] = c
        ordered = [merged[t] for t in sorted(merged.keys())]

        max_len = self._max_candles(interval)
        if len(ordered) > max_len:
            ordered = ordered[-max_len:]
        return ordered

    @staticmethod
    def _tail_candles(candles: list[dict], max_len: int) -> list[dict]:
        if not candles:
            return []
        if len(candles) <= max_len:
            return candles
        return candles[-max_len:]

    @staticmethod
    def _aggregate_history_candles(candles: list[dict], minutes: int) -> list[dict]:
        """Aggregate 1m candles into larger intraday buckets for Redis persistence."""
        if not candles or minutes <= 1:
            return candles or []

        bucket_seconds = minutes * 60
        aggregated: list[dict] = []
        current_bucket = None
        current = None

        for candle in candles:
            try:
                ts = int(candle["time"])
                o = float(candle["open"])
                h = float(candle["high"])
                l = float(candle["low"])
                cl = float(candle["close"])
                v = int(float(candle.get("volume", 0) or 0))
            except (TypeError, ValueError, KeyError):
                continue

            bucket = (ts // bucket_seconds) * bucket_seconds
            if current_bucket is None or bucket != current_bucket:
                if current is not None:
                    aggregated.append(current)
                current_bucket = bucket
                current = {
                    "time": bucket,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": v,
                }
                continue

            current["high"] = max(float(current["high"]), h, o, cl, l)
            current["low"] = min(float(current["low"]), l, o, cl, h)
            current["close"] = cl
            current["volume"] = int(current.get("volume", 0)) + v

        if current is not None:
            aggregated.append(current)

        return aggregated

    async def _persist_history_to_redis(
        self, symbols: set[str] | None = None, force_all: bool = False
    ) -> None:
        try:
            from cache.redis_client import set_history

            target_symbols = set(symbols or set())
            if force_all or not target_symbols:
                target_symbols = set()
                target_symbols.update(self._history_buffers["1m"].keys())
                target_symbols.update(self._history_buffers["5m"].keys())
                target_symbols.update(self._candle_state["1m"].keys())
                target_symbols.update(self._candle_state["5m"].keys())

            if not target_symbols:
                return

            for symbol in target_symbols:
                candles_1m = self._current_and_history_candles(symbol, "1m")
                if candles_1m:
                    await set_history(symbol, "1d", "1m", candles_1m)

                    # Persist derived intraday intervals so restart warmup does not
                    # collapse charts to a single candle when Redis is re-read.
                    candles_2m = self._aggregate_history_candles(candles_1m, 2)
                    if candles_2m:
                        await set_history(symbol, "1d", "2m", candles_2m)

                    candles_3m = self._aggregate_history_candles(candles_1m, 3)
                    if candles_3m:
                        await set_history(symbol, "1d", "3m", candles_3m)

                candles_5m = self._current_and_history_candles(symbol, "5m")
                if candles_5m:
                    # Frontend default period for 5m interval is 1d.
                    await set_history(
                        symbol,
                        "1d",
                        "5m",
                        self._tail_candles(candles_5m, 96),
                    )
                    await set_history(symbol, "5d", "5m", candles_5m)
        except Exception as e:
            logger.debug(f"MarketDataWorker history persist failed: {e}")

    async def _freeze_market_snapshots(self) -> None:
        """Flush any in-memory candles to Redis before entering closed market state."""
        await self._persist_history_to_redis(force_all=True)
        await self._freeze_price_snapshots()
        self._dirty_history_symbols.clear()
        self._last_history_persist_ts = time.time()

    async def _freeze_price_snapshots(self) -> None:
        """Lock last tradable quotes into authoritative frozen Redis rows with day change."""
        try:
            from cache.redis_client import get_last_price, set_authoritative_close
            from services.market_data import (
                _enrich_frozen_quote_day_change,
                _normalize_quote,
            )
        except Exception as e:
            logger.debug(f"MarketDataWorker price freeze imports failed: {e}")
            return

        frozen = 0
        for symbol in sorted(self._subscribed_symbols):
            try:
                quote = await get_last_price(symbol)
                if not quote:
                    continue
                normalized = _normalize_quote({**quote, "symbol": quote.get("symbol") or symbol})
                if not normalized:
                    continue
                enriched = await _enrich_frozen_quote_day_change(symbol, normalized)
                if not enriched:
                    continue
                enriched.setdefault("source", "official_eod_close")
                enriched["frozen"] = True
                await set_authoritative_close(symbol, enriched)
                frozen += 1
            except Exception as e:
                logger.debug(f"MarketDataWorker price freeze skipped for {symbol}: {e}")

        if frozen:
            logger.info(
                f"MarketDataWorker frozen authoritative price snapshots for {frozen} symbols"
            )

    async def _hydrate_history_from_redis(self) -> None:
        """Restore intraday candle buffers from Redis so restarts keep the prior session history."""
        try:
            from cache.redis_client import get_history as redis_get_history
            from services.market_data import normalize_history_candles
        except Exception as e:
            logger.debug(f"MarketDataWorker history hydrate imports failed: {e}")
            return

        hydrate_map = (("1m", "1d"), ("5m", "5d"))
        restored = 0

        for symbol in sorted(self._subscribed_symbols):
            for interval, period in hydrate_map:
                try:
                    candles = await redis_get_history(symbol, period, interval)
                except Exception as e:
                    logger.debug(
                        f"MarketDataWorker history hydrate failed ({symbol} {interval}): {e}"
                    )
                    continue

                candles = normalize_history_candles(candles or [])
                if not candles:
                    continue

                max_len = self._max_candles(interval)
                self._history_buffers[interval][symbol] = candles[-max_len:]
                self._candle_state[interval][symbol] = dict(
                    self._history_buffers[interval][symbol][-1]
                )
                restored += 1

        if restored:
            logger.info(
                f"MarketDataWorker hydrated intraday history from Redis for {restored} symbol/interval sets"
            )

    async def _provider_health_status(self, provider) -> str:
        """Best-effort provider health status string."""
        try:
            health = await provider.health()
            return str(getattr(getattr(health, "status", None), "value", ""))
        except Exception:
            return ""

    async def _attempt_master_recover(self, reason: str) -> bool:
        now = time.time()
        if (now - self._last_master_recover_attempt) < self.MASTER_RECOVER_COOLDOWN:
            return False

        self._last_master_recover_attempt = now
        try:
            from services.master_session import master_session_service

            recovered = await master_session_service.refresh()
            if recovered:
                logger.info(f"MarketDataWorker recovered master session ({reason})")
                self._consecutive_empty_sweeps = 0
                self._consecutive_batch_failures = 0
                return True
            logger.warning(f"MarketDataWorker master recover failed ({reason})")
            return False
        except Exception as e:
            logger.debug(f"MarketDataWorker master recover exception ({reason}): {e}")
            return False

    async def run(self) -> None:
        """Main loop — started via asyncio.create_task in lifespan."""
        self._running = True
        logger.info("Market Data Worker started (per-user architecture)")

        # Auto-subscribe popular symbols + MCX commodities
        from services.market_data import (
            POPULAR_INDIAN_STOCKS,
            INDIAN_INDICES,
            POPULAR_COMMODITIES,
        )

        for s in POPULAR_INDIAN_STOCKS:
            self._subscribed_symbols.add(s["symbol"])
        for i in INDIAN_INDICES:
            self._subscribed_symbols.add(i["symbol"])
        for c in POPULAR_COMMODITIES:
            self._subscribed_symbols.add(c["symbol"])

        # Also subscribe every symbol from persisted user watchlists.
        watchlist_symbols = await self._load_watchlist_symbols()
        self._subscribed_symbols.update(watchlist_symbols)
        if watchlist_symbols:
            logger.info(
                f"MarketDataWorker loaded {len(watchlist_symbols)} watchlist symbols"
            )

        # Warm-start from Redis so a backend restart does not collapse intraday charts
        # to a single live candle while the worker rebuilds state from ticks.
        await self._hydrate_history_from_redis()

        refresh_watchlist_every = 20
        sweep_since_refresh = 0

        while self._running:
            try:
                # CHECK MARKET STATE — adapt polling frequency
                actual_state = market_session.get_current_state()
                market_frozen = actual_state != MarketState.OPEN

                if self._last_market_state is None:
                    self._last_market_state = actual_state

                just_frozen = (
                    market_frozen and self._last_market_state == MarketState.OPEN
                )
                if just_frozen:
                    await self._freeze_market_snapshots()
                    try:
                        from services.market_eod_reconciliation import (
                            schedule_reconcile_market_close,
                        )

                        schedule_reconcile_market_close(reason="market_worker_open_to_closed")
                    except Exception as e:
                        logger.warning(
                            f"MarketDataWorker EOD reconciliation schedule failed: {e}"
                        )

                # Freeze live publishing for all non-open sessions.
                # Keep last traded values in cache until next open.
                if market_frozen:
                    self._last_market_state = actual_state
                    await asyncio.sleep(self.IDLE_INTERVAL)
                    continue

                # Get any available provider session
                from services.broker_session import broker_session_manager

                provider = broker_session_manager.get_any_session()

                if provider is None:
                    now = time.time()
                    if (
                        now - self._last_master_recover_attempt
                        >= self.MASTER_RECOVER_COOLDOWN
                    ):
                        self._last_master_recover_attempt = now
                        try:
                            from services.master_session import master_session_service

                            recovered = await master_session_service.initialize()
                            if recovered:
                                provider = broker_session_manager.get_any_session()
                                if provider is not None:
                                    logger.info(
                                        "MarketDataWorker recovered master Zebu session"
                                    )
                        except Exception as e:
                            logger.debug(
                                f"MarketDataWorker master recover attempt failed: {e}"
                            )

                if provider is None:
                    # No broker sessions — keep existing cache until expiry.
                    self._stats["no_session_waits"] += 1
                    if self._stats["no_session_waits"] % 30 == 1:
                        logger.debug(
                            "MarketDataWorker: No broker sessions, "
                            "waiting for live provider session"
                        )
                    await asyncio.sleep(self.NO_SESSION_INTERVAL)
                    continue

                provider_status = await self._provider_health_status(provider)
                if provider_status in ("disconnected", "error"):
                    await self._attempt_master_recover(
                        f"provider_status={provider_status}"
                    )

                # Sweep all subscribed symbols
                symbols = list(self._subscribed_symbols)
                sweep_quotes: dict[str, dict] = {}

                if symbols:
                    for batch in self._chunked(symbols, self.BATCH_SIZE):
                        if not self._running:
                            break

                        try:
                            quotes = await asyncio.wait_for(
                                provider.get_batch_quotes(batch),
                                timeout=self.BATCH_TIMEOUT_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            self._consecutive_batch_failures += 1
                            logger.debug(
                                f"MarketDataWorker batch timeout ({len(batch)} symbols)"
                            )
                            continue
                        except Exception as e:
                            self._consecutive_batch_failures += 1
                            logger.debug(f"MarketDataWorker batch fetch failed: {e}")
                            continue

                        if quotes:
                            sweep_quotes.update(quotes)
                            await self._publish_quotes(
                                quotes, source="market_data_worker"
                            )

                if sweep_quotes:
                    self._consecutive_empty_sweeps = 0
                    self._consecutive_batch_failures = 0
                else:
                    self._consecutive_empty_sweeps += 1

                if (
                    self._consecutive_empty_sweeps >= self.EMPTY_SWEEP_RECOVER_THRESHOLD
                    or self._consecutive_batch_failures
                    >= self.BATCH_FAIL_RECOVER_THRESHOLD
                ):
                    await self._attempt_master_recover(
                        f"empty_sweeps={self._consecutive_empty_sweeps},batch_failures={self._consecutive_batch_failures}"
                    )

                self._stats["sweeps"] += 1
                sweep_since_refresh += 1

                if sweep_since_refresh >= refresh_watchlist_every:
                    sweep_since_refresh = 0
                    try:
                        watchlist_symbols = await self._load_watchlist_symbols()
                        if watchlist_symbols:
                            self._subscribed_symbols.update(watchlist_symbols)
                    except Exception:
                        pass

                # After each full sweep, refresh the ticker cache in Redis
                # so all API calls to /ticker immediately get fresh data
                try:
                    from cache.redis_client import (
                        set_commodities,
                        set_ticker,
                        set_indices,
                    )

                    ticker_items = self._build_ticker_items(sweep_quotes)
                    if ticker_items:
                        await set_ticker(ticker_items)
                        await set_indices(
                            [i for i in ticker_items if i.get("kind") == "index"]
                        )
                        await set_commodities(
                            [i for i in ticker_items if i.get("kind") == "commodity"]
                        )
                except Exception as _te:
                    logger.debug(f"Ticker cache refresh failed: {_te}")

                # Adapt polling frequency: active during open session, idle otherwise.
                interval = self.IDLE_INTERVAL if market_frozen else self.ACTIVE_INTERVAL
                self._last_market_state = actual_state
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Market Data Worker error: {e}", exc_info=True)
                await asyncio.sleep(5)

        logger.info("Market Data Worker stopped")

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        self._running = False


# ── Singleton ──────────────────────────────────────────────────────
market_data_worker = MarketDataWorker()
