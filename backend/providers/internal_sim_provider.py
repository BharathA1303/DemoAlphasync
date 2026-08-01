# internal_sim_provider.py - MarketProvider implementation backed directly
# by the in-process simulation engine (backend/data_layer/*: real NSE/BSE/
# NSE_FO bhavcopy EOD data -> Brownian-bridge tick-by-tick simulator).
#
# This replaces the old TickAlphaProvider, which opened a real HTTP/JWT/
# WebSocket connection to "TickAlpha" even though TickAlpha is this same
# process's own simulator — a legacy split from when the two were meant to
# be separately deployable services. All calls here are direct in-process
# function calls (see services/internal_sim_engine.py); there is no network
# hop and nothing external is contacted.
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any

from providers.base import MarketProvider, ProviderHealth, ProviderStatus
from market_data.replay.market_publisher import market_publisher

logger = logging.getLogger(__name__)

_DEFAULT_EXCHANGE = "NSE"
_DEFAULT_SEGMENT = "EQ"

# Intraday interval strings (as sent by the frontend, see
# services/market_data.py::_INTRADAY_HISTORY_INTERVALS) -> bucket width in
# seconds, used to downsample cached per-second ticks into OHLC candles.
# Daily+ intervals (1d/1wk/1mo, or anything unrecognized) are intentionally
# absent here so get_historical_data falls back to one EOD row per day.
_INTERVAL_SECONDS: Dict[str, int] = {
    "1m": 60, "2m": 120, "3m": 180, "5m": 300, "10m": 600,
    "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
}

_MCX_COMMODITY_BASES = {
    "GOLD", "GOLDM", "GOLDGUINEA", "GOLDPETAL",
    "SILVER", "SILVERM", "SILVERMIC",
    "COPPER", "COPPERM",
    "CRUDEOIL", "CRUDEOILM",
    "NATURALGAS", "NATGASMINI",
    "ALUMINIUM", "ALUMINI",
    "ZINC", "ZINCMINI",
    "LEAD", "LEADMINI",
    "NICKEL",
    "MENTHOIL",
    "COTTONCNDY", "KAPAS",
}

# "^"-prefixed Yahoo-style index symbols (as used throughout services/market_data.py
# and the frontend) -> the bare underlying ticker + exchange the internal sim engine's
# PriceData rows are seeded under (see data_layer/ingestion/index_bhavcopy.py).
_INDEX_SIM_MAP: Dict[str, tuple] = {
    "^NSEI": ("NSE", "NIFTY50"),
    "^NSEBANK": ("NSE", "BANKNIFTY"),
    "^CNXFIN": ("NSE", "FINNIFTY"),
    "^BSESN": ("BSE", "SENSEX"),
}
_INDEX_SEGMENT = "IDX"
_INDEX_SIM_MAP_REVERSE = {
    (exch, base): yahoo for yahoo, (exch, base) in _INDEX_SIM_MAP.items()
}


def _canonical_to_sim_symbol(symbol: str) -> str:
    """Map an AlphaSync canonical symbol (e.g. RELIANCE.NS, GOLD, ^NSEI) to the
    engine's 'EXCHANGE:SEGMENT:SYMBOL' subscription format
    (e.g. NSE:EQ:RELIANCE, MCX:FUT:GOLD, NSE:IDX:NIFTY50)."""
    clean = str(symbol or "").strip().upper()
    if clean in _INDEX_SIM_MAP:
        exchange, base = _INDEX_SIM_MAP[clean]
        return f"{exchange}:{_INDEX_SEGMENT}:{base}"
    if ":" in clean:
        return clean
    base = clean[:-3] if clean.endswith((".NS", ".BO")) else clean
    if base in _MCX_COMMODITY_BASES:
        return f"MCX:FUT:{base}"
    exchange = "BSE" if clean.endswith(".BO") else _DEFAULT_EXCHANGE
    return f"{exchange}:{_DEFAULT_SEGMENT}:{base}"


def _sim_symbol_to_canonical(sim_symbol: str) -> str:
    """Reverse of _canonical_to_sim_symbol: 'NSE:EQ:RELIANCE' -> 'RELIANCE.NS',
    'NSE:IDX:NIFTY50' -> '^NSEI'."""
    parts = str(sim_symbol or "").strip().upper().split(":")
    if len(parts) == 3:
        exchange, segment, base = parts
        if segment == _INDEX_SEGMENT:
            yahoo = _INDEX_SIM_MAP_REVERSE.get((exchange, base))
            if yahoo:
                return yahoo
        if exchange == "MCX":
            return base
        if exchange == "BSE":
            return f"{base}.BO"
        return f"{base}.NS"
    base = parts[-1] if parts else str(sim_symbol or "").strip().upper()
    return f"{base}.NS"


def _eligible_dates(max_lookback: int = 10) -> List[str]:
    """Trading dates that clear the engine's 3-rolling-day compliance delay
    gate, most-recent first, skipping weekends. The engine only has EOD data
    for days it has actually ingested, so callers may need to walk back past
    the most recent eligible date (holidays, un-ingested days) until
    subscription succeeds. Returns up to ``max_lookback`` YYYY-MM-DD strings."""
    dates: List[str] = []
    d = (datetime.now(timezone.utc) - timedelta(days=4)).date()
    while len(dates) < max_lookback:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d -= timedelta(days=1)
    return dates


class InternalSimProvider(MarketProvider):
    """
    Drives the in-process simulation engine directly: opens a virtual replay
    session for the most recent compliance-eligible trading date, subscribes
    to instruments, and streams simulated tick-by-tick data by registering a
    local listener queue on SimulatorManager — forwarding ticks to the
    shared MarketPublisher. No network connection of any kind is made.

    A replay session never truly ends: once its virtual clock reaches
    market close it rolls over to the next eligible trading day on its own
    and keeps streaming (see SimulatorManager.process_active_session).
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client

        self._status = ProviderStatus.DISCONNECTED
        self._price_cache: Dict[str, dict] = {}
        self._subscribed_symbols: set[str] = set()
        self._running = False
        self._last_tick_at: Optional[float] = None
        self._started_at: Optional[float] = None

        self._session_id: Optional[str] = None
        self._listener_queue: Optional[asyncio.Queue] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._setup_task: Optional[asyncio.Task] = None
        self._reconnect_count = 0

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the provider and initiate the background session/listener loop."""
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._status = ProviderStatus.CONNECTING
        self._reconnect_count = 0

        market_publisher.set_redis(self._redis)
        self._price_cache = market_publisher._price_cache

        self._setup_task = asyncio.create_task(self._setup_and_listen())
        logger.info("InternalSimProvider started background session loop")

    async def stop(self) -> None:
        """Stop the provider, cancel tasks and unregister listeners."""
        self._running = False
        self._status = ProviderStatus.DISCONNECTED

        if self._setup_task:
            self._setup_task.cancel()
            try:
                await self._setup_task
            except asyncio.CancelledError:
                pass
            self._setup_task = None

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._session_id and self._listener_queue is not None:
            from services.internal_sim_engine import unregister_local_listener
            unregister_local_listener(self._session_id, self._listener_queue)

        self._session_id = None
        self._listener_queue = None
        logger.info("InternalSimProvider stopped")

    # ── Subscription APIs ────────────────────────────────────────────

    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to a list of symbols."""
        clean_symbols = [str(s).strip().upper() for s in symbols if s]
        self._subscribed_symbols.update(clean_symbols)

        if self._session_id:
            await self._subscribe_on_session(clean_symbols)

    async def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from a list of symbols.

        The engine has no unsubscribe operation for an active session; we
        simply stop tracking the symbols locally so future resubscribes
        omit them.
        """
        clean_symbols = [str(s).strip().upper() for s in symbols if s]
        for s in clean_symbols:
            self._subscribed_symbols.discard(s)

    def get_subscribed_symbols(self) -> set:
        return set(self._subscribed_symbols)

    async def get_quote(self, symbol: str) -> Optional[dict]:
        return self._price_cache.get(str(symbol).strip().upper())

    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, dict]:
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
        """Fetch historical candles directly from the internal engine.

        Daily+ intervals (1d/1wk/1mo) return one EOD candle per trading day
        straight from price_data. Intraday intervals (1m/5m/15m/...) instead
        expand each trading day's single EOD row into real intraday candles
        by reading the cached per-second Brownian-bridge tick path (see
        data_layer/simulator/brownian_bridge.py) and bucketing it into
        interval-sized OHLCV windows — otherwise every intraday timeframe
        would silently collapse to one bar per day.
        """
        from database.connection import async_session
        from services.internal_sim_engine import get_eligible_price_range

        logger.info(f"InternalSimProvider: Fetching historical data for {symbol} ({interval})")
        try:
            sim_symbol = _canonical_to_sim_symbol(symbol)
            exchange, segment, base_symbol = sim_symbol.split(":")

            end_date = datetime.now(timezone.utc).date()
            bucket_seconds_for_lookback = _INTERVAL_SECONDS.get(interval)
            if bucket_seconds_for_lookback is None:
                lookback_days = 90
            elif bucket_seconds_for_lookback >= 3600:
                # 1h/2h/4h charts request up to 6mo of period from the
                # frontend; generating/caching ticks for that many trading
                # days is still bounded (~130 trading days), unlike 1m/5m.
                lookback_days = 190
            else:
                lookback_days = 7
            start_date = end_date - timedelta(days=lookback_days)

            async with async_session() as db:
                rows = await get_eligible_price_range(
                    db, exchange, base_symbol, start_date, end_date, segment=segment
                )

                bucket_seconds = _INTERVAL_SECONDS.get(interval)
                if bucket_seconds:
                    candles = await self._build_intraday_candles(
                        db, exchange, segment, base_symbol, rows, bucket_seconds
                    )
                    if candles:
                        return candles
                    # Fall through to EOD candles if no tick data resolved
                    # (e.g. brand new symbol not yet cached).

            return [
                {
                    "time": row.get("market_timestamp"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"InternalSimProvider: History lookup failed: {e}.")
            return []

    async def _build_intraday_candles(
        self, db, exchange: str, segment: str, base_symbol: str,
        rows: List[dict], bucket_seconds: int,
    ) -> list:
        """Expand each day's EOD row into intraday candles from its cached
        per-second tick path, bucketed into `bucket_seconds`-wide windows."""
        from data_layer.simulator.brownian_bridge import ensure_ticks_cached, tick_cache_key
        from data_layer.core.cache import get_cached_response
        import json as _json

        candles: list = []
        for row in rows:
            ts = row.get("market_timestamp")
            if not ts:
                continue
            try:
                target_date = datetime.fromisoformat(ts).date() if isinstance(ts, str) else ts
            except ValueError:
                continue

            eod_data = await ensure_ticks_cached(db, exchange, segment, base_symbol, target_date)
            if not eod_data:
                continue

            cache_key = tick_cache_key(exchange, segment, base_symbol, target_date, eod_data.version)
            raw = await get_cached_response(cache_key)
            if not raw:
                continue

            try:
                ticks = _json.loads(raw)
            except (ValueError, TypeError):
                continue

            # Tick "t" strings are IST wall-clock times (see brownian_bridge.py's
            # TIME_STRINGS, 09:15:00-15:30:00) with no date component, so anchor
            # midnight-IST-as-UTC-offset ourselves rather than relying on a
            # system/library IST timezone lookup.
            IST_OFFSET_SECONDS = 5 * 3600 + 30 * 60
            midnight_ist_epoch = int(
                datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()
            ) - IST_OFFSET_SECONDS

            bucket: Optional[dict] = None
            bucket_start_epoch: Optional[int] = None
            for tick in ticks:
                t_str = tick.get("t")
                if not t_str:
                    continue
                h, m, s = (int(part) for part in t_str.split(":"))
                tick_epoch = midnight_ist_epoch + (h * 3600 + m * 60 + s)
                bucket_id = (tick_epoch // bucket_seconds) * bucket_seconds

                price = tick.get("p")
                volume = tick.get("v", 0) or 0
                if price is None:
                    continue

                if bucket_start_epoch != bucket_id:
                    if bucket is not None:
                        candles.append(bucket)
                    bucket_start_epoch = bucket_id
                    bucket = {
                        "time": bucket_id,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": volume,
                    }
                else:
                    bucket["high"] = max(bucket["high"], price)
                    bucket["low"] = min(bucket["low"], price)
                    bucket["close"] = price
                    bucket["volume"] += volume

            if bucket is not None:
                candles.append(bucket)

        return candles

    async def health(self) -> ProviderHealth:
        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        return ProviderHealth(
            status=self._status,
            provider_name="InternalSimProvider",
            subscribed_symbols=len(self._subscribed_symbols),
            last_tick_at=datetime.fromtimestamp(self._last_tick_at, timezone.utc).isoformat() if self._last_tick_at else None,
            uptime_seconds=uptime,
            reconnect_count=self._reconnect_count,
            error=None if self._status == ProviderStatus.CONNECTED else "Simulation session not active",
        )

    # ── Session & listener setup ─────────────────────────────────────

    async def _subscribe_on_session(self, symbols: List[str]) -> int:
        """Subscribe the active session to the given canonical symbols.
        Returns the number of symbols actually resolved/subscribed."""
        if not symbols or not self._session_id:
            return 0
        from database.connection import async_session
        from services.internal_sim_engine import subscribe_session_symbols

        sim_symbols = [_canonical_to_sim_symbol(s) for s in symbols]
        try:
            async with async_session() as db:
                state = await subscribe_session_symbols(db, self._session_id, sim_symbols)
                await db.commit()
            count = len(state.get("subscriptions", []))
            logger.info(f"InternalSimProvider: Subscribed {count} symbols on session {self._session_id}")
            return count
        except Exception as e:
            logger.warning(f"InternalSimProvider: Subscribe failed: {e}")
            return 0

    async def _setup_session(self) -> None:
        """Create a session (on a date that actually has data), subscribe,
        and start playback. Walks back across recent eligible trading dates
        until one yields subscribable data."""
        from services.internal_sim_engine import create_replay_session, start_session_clock

        symbols = list(self._subscribed_symbols)

        subscribed = 0
        for replay_date_str in _eligible_dates():
            replay_date = datetime.strptime(replay_date_str, "%Y-%m-%d").date()
            # 5 virtual seconds of ticks delivered per real second (still one
            # broadcast per ~1s loop iteration, see SimulatorManager.run_loop)
            # so the feed reads closer to a real broker's tick density instead
            # of one price point per second. A full 09:15-15:30 session then
            # plays out in ~75 real minutes instead of ~6h15m.
            session_state = await create_replay_session(replay_date, replay_speed=5)
            self._session_id = session_state["session_id"]

            if not symbols:
                break
            subscribed = await self._subscribe_on_session(symbols)
            if subscribed > 0:
                break
            logger.warning(f"InternalSimProvider: No data for {replay_date}; trying an earlier date")
        else:
            logger.error(
                "InternalSimProvider: No eligible date yielded subscribable data — "
                "the session will start but no ticks will flow"
            )

        await start_session_clock(self._session_id)
        logger.info(f"InternalSimProvider: Session {self._session_id} clock started")

    async def _setup_and_listen(self) -> None:
        """Background loop: sets up a session, registers a local listener
        queue, and processes tick messages. Reconnects (re-creates a
        session/listener) only on genuine failures, not on end-of-day
        completion (sessions auto-roll to the next trading day on their own).
        """
        backoff = 1.0
        while self._running:
            try:
                self._status = ProviderStatus.CONNECTING
                await self._setup_session()

                from services.internal_sim_engine import register_local_listener, unregister_local_listener

                self._listener_queue = asyncio.Queue(maxsize=256)
                register_local_listener(self._session_id, self._listener_queue)
                self._status = ProviderStatus.CONNECTED
                backoff = 1.0
                logger.info(f"InternalSimProvider: Listening on session {self._session_id}")

                try:
                    while self._running:
                        message = await self._listener_queue.get()
                        await self._handle_sim_message(message)
                finally:
                    unregister_local_listener(self._session_id, self._listener_queue)
                    self._listener_queue = None
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"InternalSimProvider session error: {e}", exc_info=True)
                self._status = ProviderStatus.ERROR

            if self._running:
                self._reconnect_count += 1
                logger.info(f"InternalSimProvider: Retrying in {backoff}s (attempt #{self._reconnect_count})...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _handle_sim_message(self, data: dict) -> None:
        """Process tick_update / day_rollover messages published directly
        by SimulatorManager onto our local listener queue."""
        try:
            msg_type = data.get("type")

            if msg_type == "day_rollover":
                logger.info(
                    f"InternalSimProvider: Session {self._session_id} rolled over "
                    f"{data.get('previous_date')} -> {data.get('date')} "
                    f"(virtual_time={data.get('virtual_time')})"
                )
                return

            if msg_type != "tick_update":
                return

            ticks_by_symbol: Dict[str, list] = data.get("ticks", {}) or {}
            for sim_symbol, ticks in ticks_by_symbol.items():
                canonical_symbol = _sim_symbol_to_canonical(sim_symbol)
                for tick in ticks:
                    self._last_tick_at = time.time()
                    mapped_tick = {
                        "symbol": canonical_symbol,
                        "exchange": "NSE",
                        "price": tick.get("p", 0.0),
                        "volume": tick.get("v", 0),
                        "bid_price": tick.get("bid"),
                        "ask_price": tick.get("ask"),
                        "bid_qty": tick.get("bidQty"),
                        "ask_qty": tick.get("askQty"),
                        "oi": tick.get("oi"),
                        "timestamp": data.get("virtual_time") or tick.get("t"),
                    }
                    await market_publisher.publish_tick(mapped_tick)
        except Exception as e:
            logger.debug(f"InternalSimProvider: Failed to handle sim message: {e}")
