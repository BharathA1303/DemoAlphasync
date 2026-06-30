"""
ZebuProvider — Real-time market data via Zebu WebSocket feed.

Architecture:
    - Single global WebSocket connection to Zebu's streaming API
    - Token-based subscription management
    - Incoming ticks are parsed, normalized to canonical Quote format,
      and stored in Redis for low-latency reads
    - Emits PRICE_UPDATED on every valid tick for instant WS broadcast
    - Auto-reconnect with exponential backoff
    - Heartbeat monitoring to detect dead connections

Zebu WebSocket Protocol (NorenOMS):
    - Connect to: wss://ws1.zebull.in/NorenWS/
    - Auth via connection request with jKey (session token)
    - Subscribe with exchange|token pairs
    - Tick data arrives as JSON with lp (last price), v (volume), etc.

IMPORTANT: This provider is for MARKET DATA ONLY.
    - No broker credentials stored
    - No demat account access
    - No real order placement
    - Single read-only data feed
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import websockets
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
    InvalidStatusCode,
)

from providers.base import (
    MarketProvider,
    ProviderHealth,
    ProviderStatus,
)
from providers.symbol_mapper import (
    canonical_to_zebu,
    zebu_token_to_canonical,
    load_zebu_contracts,
    is_commodity_symbol,
    is_mcx_symbol,
    is_ncdex_symbol,
)
from services.broker_safety import is_safe_websocket_message

logger = logging.getLogger(__name__)


class ZebuProvider(MarketProvider):
    """
    Zebu WebSocket-based market data provider.

    Per-user instances created by BrokerSessionManager after OAuth.
    Each instance connects with the user's own session token.
    """

    # ── Reconnect strategy ──────────────────────────────────────────
    RECONNECT_BASE_DELAY = 1.0  # seconds
    RECONNECT_MAX_DELAY = 60.0  # cap backoff at 60s
    RECONNECT_BACKOFF_FACTOR = 2.0
    MAX_RECONNECT_ATTEMPTS = 50  # give up after this many consecutive failures

    # ── Heartbeat ───────────────────────────────────────────────────
    HEARTBEAT_INTERVAL = 30.0  # send ping every 30s
    HEARTBEAT_TIMEOUT = 10.0  # expect pong within 10s
    QUOTE_STALE_SECONDS = 20.0
    STREAM_STALE_SECONDS = 25.0

    def __init__(
        self,
        ws_url: str,
        user_id: str = "",
        api_key: str = "",
        session_token: str = "",
        redis_client=None,  # Optional: cache/redis_client.PriceCache
        api_url: str = "",  # REST API base URL (e.g. https://go.mynt.in/NorenWClientTP)
    ):
        self._ws_url = ws_url
        self._user_id = user_id
        self._api_key = api_key
        self._session_token = session_token
        self._redis: Optional[object] = redis_client
        self._api_url = api_url.rstrip("/") if api_url else ""

        # Connection state
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._status = ProviderStatus.DISCONNECTED
        self._started_at: Optional[float] = None
        self._last_tick_at: Optional[float] = None
        self._reconnect_count = 0
        self._consecutive_failures = 0

        # Subscription tracking
        self._subscribed_symbols: set[str] = set()  # canonical symbols
        self._pending_subscribe: set[str] = set()  # queued while disconnected

        # In-memory latest prices (always available even without Redis)
        self._price_cache: dict[str, dict] = {}

        # Background tasks
        self._recv_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

        # Lock for credential updates (prevent race during reconnect)
        self._credential_lock = asyncio.Lock()

    def _ws_is_closed(self) -> bool:
        """Check if WebSocket is closed — compatible with websockets v10-v14+."""
        if not self._ws:
            return True
        try:
            return self._ws.closed  # websockets < 14
        except AttributeError:
            return self._ws.close_code is not None  # websockets 14+

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Zebu WebSocket and start receiving data."""
        self._running = True
        self._started_at = time.time()
        logger.info(
            f"ZebuProvider.start() | ws_url={self._ws_url} | "
            f"user_id={'*' * 4 + self._user_id[-4:] if self._user_id else 'NONE'} | "
            f"has_token={bool(self._session_token)}"
        )

        if not self.has_credentials():
            logger.warning(
                "ZebuProvider started without credentials — "
                "waiting for broker session manager to inject them."
            )
            self._status = ProviderStatus.DISCONNECTED
            return

        await self._connect()

    async def stop(self) -> None:
        """Gracefully disconnect."""
        self._running = False

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

        self._status = ProviderStatus.DISCONNECTED
        logger.info("ZebuProvider stopped")

    # ── Dynamic credential update ───────────────────────────────────

    async def update_credentials(self, user_id: str, session_token: str) -> None:
        """
        Hot-swap the authentication credentials and reconnect.

        Called by BrokerSessionManager when the active token changes
        (e.g. user connect/disconnect/token rotation).

        This triggers a clean disconnect + reconnect cycle so the
        WebSocket re-authenticates with the new token.
        """
        async with self._credential_lock:
            old_user = self._user_id
            self._user_id = user_id
            self._session_token = session_token

            logger.info(
                f"ZebuProvider credentials updated: "
                f"{str(old_user)[:8] if old_user else 'none'}... → "
                f"{str(user_id)[:8] if user_id else 'none'}..."
            )

            if not session_token:
                # No token — disconnect but keep running for later reconnect
                if self._ws and not self._ws_is_closed():
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                self._status = ProviderStatus.DISCONNECTED
                return

            # Reconnect with new credentials
            if self._running:
                # Stop current recv/heartbeat tasks
                if self._heartbeat_task and not self._heartbeat_task.done():
                    self._heartbeat_task.cancel()
                if self._recv_task and not self._recv_task.done():
                    self._recv_task.cancel()
                if self._ws and not self._ws_is_closed():
                    try:
                        await self._ws.close()
                    except Exception:
                        pass

                self._consecutive_failures = 0
                await self._connect()

    def has_credentials(self) -> bool:
        """Check if valid credentials are configured."""
        return bool(self._user_id and self._session_token)

    # ── Connection management ───────────────────────────────────────

    async def _connect(self) -> None:
        """Establish WebSocket connection and authenticate."""
        self._status = ProviderStatus.CONNECTING
        logger.debug(
            f"ZebuProvider._connect() | url={self._ws_url} | "
            f"subscribed_symbols={len(self._subscribed_symbols)} | "
            f"reconnect_count={self._reconnect_count}"
        )

        try:
            self._ws = await websockets.connect(
                self._ws_url,
                ping_interval=None,  # we handle heartbeats ourselves
                ping_timeout=None,
                close_timeout=10,
                max_size=2**20,  # 1 MB max message
            )

            # ── Authenticate ────────────────────────────────────────
            auth_msg = {
                "t": "c",  # connection type
                "uid": self._user_id,
                "actid": self._user_id,
                "susertoken": self._session_token,
                "accesstoken": self._session_token,  # MYNT OAuth tokens
                "source": "API",
            }
            if not is_safe_websocket_message(auth_msg):
                logger.error(
                    "Safety guard blocked auth message — this should never happen"
                )
                self._status = ProviderStatus.ERROR
                return

            await self._ws.send(json.dumps(auth_msg))

            # Wait for auth response
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            resp = json.loads(raw)

            if resp.get("s") != "OK":
                error_msg = resp.get("emsg", "Unknown auth error")
                logger.error(f"ZebuProvider auth failed: {error_msg}")
                self._status = ProviderStatus.ERROR
                return

            self._status = ProviderStatus.CONNECTED
            self._consecutive_failures = 0
            logger.info(
                f"[ZEBU WS CONNECTED] authenticated | "
                f"user={str(self._user_id)[:8] if self._user_id else '?'}... | "
                f"pending_resubscribe={len(self._subscribed_symbols)} | "
                f"subscribed_total={len(self._subscribed_symbols)} | "
                f"pending_queue={len(self._pending_subscribe)}"
            )

            # Re-subscribe symbols that were active before reconnect
            if self._subscribed_symbols:
                await self._send_subscribe(self._subscribed_symbols)

            # Subscribe any symbols queued while disconnected
            if self._pending_subscribe:
                await self._send_subscribe(self._pending_subscribe)
                self._subscribed_symbols.update(self._pending_subscribe)
                self._pending_subscribe.clear()

            # Start background receivers
            self._recv_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except Exception as e:
            logger.error(f"ZebuProvider connection failed: {e}")
            self._status = ProviderStatus.ERROR
            if self._running:
                asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if not self._running:
            return

        self._consecutive_failures += 1
        if self._consecutive_failures > self.MAX_RECONNECT_ATTEMPTS:
            logger.error(
                f"ZebuProvider: Max reconnect attempts ({self.MAX_RECONNECT_ATTEMPTS}) reached. Giving up."
            )
            self._status = ProviderStatus.ERROR
            return

        delay = min(
            self.RECONNECT_BASE_DELAY
            * (self.RECONNECT_BACKOFF_FACTOR ** (self._consecutive_failures - 1)),
            self.RECONNECT_MAX_DELAY,
        )
        self._status = ProviderStatus.RECONNECTING
        self._reconnect_count += 1

        logger.warning(
            f"ZebuProvider reconnecting in {delay:.1f}s "
            f"(attempt {self._consecutive_failures}/{self.MAX_RECONNECT_ATTEMPTS})"
        )
        await asyncio.sleep(delay)

        if self._running:
            await self._connect()

    # ── Data receiving ──────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """Main loop that reads messages from Zebu WebSocket."""
        try:
            async for raw_message in self._ws:
                if not self._running:
                    break

                try:
                    data = json.loads(raw_message)
                    msg_type = data.get("t")

                    if msg_type == "tk" or msg_type == "tf":
                        tick_exchange = str(data.get("e") or "").upper()
                        if tick_exchange in ("MCX", "NCDEX"):
                            logger.info(
                                f"[MCX RAW TICK] t={msg_type} e={tick_exchange} "
                                f"tk={data.get('tk')} ts={data.get('ts')} "
                                f"lp={data.get('lp')} bp1={data.get('bp1')} "
                                f"sp1={data.get('sp1')} oi={data.get('oi')} "
                                f"v={data.get('v')}"
                            )
                        await self._handle_tick(data)
                    elif msg_type == "dk" or msg_type == "df":
                        logger.debug(f"Zebu depth data: {data.get('tk', 'unknown')}")
                    elif msg_type == "om":
                        pass
                    elif msg_type == "hb":
                        logger.debug("[ZEBU HEARTBEAT] pong received")
                    else:
                        logger.debug(f"Zebu unknown message type: {msg_type}")

                except json.JSONDecodeError:
                    logger.warning(f"Zebu non-JSON message: {raw_message[:100]}")
                except Exception as e:
                    logger.error(f"Zebu tick processing error: {e}", exc_info=True)

        except ConnectionClosed as e:
            logger.warning(
                f"ZebuProvider WebSocket closed: code={e.code} reason={e.reason}"
            )
        except ConnectionClosedError as e:
            logger.warning(f"ZebuProvider connection closed with error: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"ZebuProvider receive loop error: {e}", exc_info=True)

        # Connection lost — reconnect
        if self._running:
            self._status = ProviderStatus.RECONNECTING
            asyncio.create_task(self._reconnect())

    async def _handle_tick(self, data: dict) -> None:
        """
        Parse Zebu tick data and update price cache + Redis + emit PRICE_UPDATED.

        Zebu tick format (touchline):
            {
                "t": "tk",          # touchline acknowledgement / "tf" for update
                "e": "NSE",         # exchange
                "tk": "2885",       # token
                "ts": "RELIANCE-EQ",# trading symbol
                "lp": "2513.45",   # last traded price
                "pc": "1.25",      # percent change
                "v": "1234567",    # volume
                "o": "2498.00",    # open
                "h": "2525.00",    # high
                "l": "2490.00",    # low
                "c": "2482.10",    # close (previous)
                "ap": "2505.00",   # average price
                "bp1": "2513.00",  # best buy price
                "sp1": "2513.50",  # best sell price
                "ft": "1709123456",# feed timestamp
            }

        NOTE: "tf" (update) ticks often omit fields that haven't changed
        (e.g., "c" prev_close is only in the initial "tk" ack). We must
        merge with the previous tick to preserve values like prev_close.
        """
        token = data.get("tk", "")
        exchange = str(data.get("e") or "").strip().upper()
        canonical = zebu_token_to_canonical(token, exchange=exchange)

        if exchange in ("MCX", "NCDEX"):
            if canonical:
                logger.info(
                    f"[MCX TOKEN RESOLVED] {exchange}|{token} → {canonical} "
                    f"ltp={data.get('lp')}"
                )
            else:
                from providers.symbol_mapper import _TOKEN_TO_CANONICAL
                nearby = [
                    k for k in _TOKEN_TO_CANONICAL
                    if k.startswith(f"{exchange}|")
                ][:10]
                logger.warning(
                    f"[MCX TOKEN MISS] {exchange}|{token} ts={data.get('ts')} "
                    f"— not in _TOKEN_TO_CANONICAL. "
                    f"Registered {exchange} tokens ({len(nearby)} sample): {nearby}"
                )

        if not canonical:
            logger.debug(f"Zebu tick for unmapped token: {exchange}|{token}")
            return

        self._last_tick_at = time.time()

        # Parse fields safely (Zebu sends strings)
        lp = self._safe_float(data.get("lp"))
        if lp is None or lp <= 0:
            return  # No valid price

        # For "tf" updates, Zebu often omits unchanged fields.
        # Merge with previous cache entry to preserve prev_close, open, etc.
        prev_cache = self._price_cache.get(canonical, {})

        metrics = self._extract_quote_metrics(data, lp, prev_cache)
        prev_close = metrics["prev_close"]
        change = metrics["change"]
        change_pct = metrics["change_percent"]

        # Same merge logic for OHLV fields — use tick value if present, else cached
        tick_open = self._safe_float(data.get("o"))
        tick_high = self._safe_float(data.get("h"))
        tick_low = self._safe_float(data.get("l"))
        tick_vol = self._safe_float(data.get("v"))

        # Parse bid/ask/OI (may be absent in "tf" updates)
        tick_bp1 = self._safe_float(data.get("bp1"))
        tick_sp1 = self._safe_float(data.get("sp1"))
        tick_bq1 = self._safe_float(data.get("bq1"))
        tick_sq1 = self._safe_float(data.get("sq1"))
        tick_oi = self._safe_float(data.get("oi"))
        tick_ltt = data.get("ltt") or data.get("ft")  # last trade time / feed time

        # Compute cumulative volume robustly: Zebu may send either cumulative
        # session volume or per-tick delta. Prefer monotonic values from feed;
        # if tick volume appears to be a per-tick value (smaller than previous)
        # accumulate it to keep MarketDataWorker's cumulative-volume logic correct.
        prev_vol = int(prev_cache.get("volume", 0) or 0)
        cumulative_volume = None
        if tick_vol is not None:
            try:
                tick_int = int(tick_vol)
            except Exception:
                tick_int = int(float(tick_vol) if tick_vol else 0)

            if tick_int >= prev_vol:
                cumulative_volume = tick_int
            else:
                cumulative_volume = prev_vol + tick_int
        else:
            cumulative_volume = prev_vol

        # Resolve exchange from mapping when tick omits "e" — prevents
        # commodity ticks from being tagged as NSE by default.
        resolved_exchange = exchange
        if not resolved_exchange:
            mapping = canonical_to_zebu(canonical)
            if mapping:
                resolved_exchange = str(mapping.get("exchange") or "").upper()
        if not resolved_exchange:
            if is_mcx_symbol(canonical):
                resolved_exchange = "MCX"
            elif is_ncdex_symbol(canonical):
                resolved_exchange = "NCDEX"
            else:
                resolved_exchange = prev_cache.get("exchange") or "NSE"

        quote = {
            "symbol": canonical,
            "instrument_token": int(token) if (token and token.isdigit()) else token,
            "name": data.get("ts", prev_cache.get("name", canonical)).replace(
                "-EQ", ""
            ),
            "price": lp,
            "change": change,
            "change_percent": change_pct,
            "open": tick_open if tick_open else prev_cache.get("open", 0),
            "high": tick_high if tick_high else prev_cache.get("high", 0),
            "low": tick_low if tick_low else prev_cache.get("low", 0),
            "close": prev_close,
            "prev_close": prev_close,
            "volume": int(cumulative_volume or 0),
            "bid_price": tick_bp1 if tick_bp1 else prev_cache.get("bid_price", 0),
            "ask_price": tick_sp1 if tick_sp1 else prev_cache.get("ask_price", 0),
            "bid_qty": int(tick_bq1 or 0) if tick_bq1 else prev_cache.get("bid_qty", 0),
            "ask_qty": int(tick_sq1 or 0) if tick_sq1 else prev_cache.get("ask_qty", 0),
            "oi": int(tick_oi or 0) if tick_oi else prev_cache.get("oi", 0),
            "market_cap": 0,
            "exchange": resolved_exchange,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "last_trade_time": tick_ltt or prev_cache.get("last_trade_time"),
            "source": "live_ws",
        }

        # Update in-memory cache
        self._price_cache[canonical] = quote

        _changed = (
            prev_cache.get("price") != lp
            or prev_cache.get("volume") != quote["volume"]
            or prev_cache.get("oi") != quote["oi"]
        )

        # Central quote coordinator — Redis + safe EventBus emit (Phase 2)
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
            if _changed and is_commodity_symbol(canonical):
                logger.info(
                    f"[MCX EVENT EMIT] PRICE_UPDATED {canonical} "
                    f"ltp={lp} exchange={resolved_exchange}"
                )
        except Exception as e:
            logger.warning(f"Quote coordinator ingest failed for {canonical}: {e}")

        if is_commodity_symbol(canonical):
            logger.info(
                f"[MCX HANDLE_TICK] {canonical} "
                f"ltp={lp} token={token} exchange={resolved_exchange} "
                f"bid={tick_bp1} ask={tick_sp1} oi={tick_oi} "
                f"changed={_changed}"
            )

        # ── Futures: emit FUTURES_QUOTE for NFO/BFO ticks ─────────────
        if _changed and resolved_exchange in ("NFO", "BFO"):
            try:
                from core.event_bus import event_bus, Event, EventType

                futures_quote = {
                    "contract_symbol": canonical,
                    "exchange": resolved_exchange,
                    "token": token,
                    "ltp": lp,
                    "bid": tick_bp1 if tick_bp1 else prev_cache.get("bid_price", 0),
                    "ask": tick_sp1 if tick_sp1 else prev_cache.get("ask_price", 0),
                    "spread": round(
                        (tick_sp1 or prev_cache.get("ask_price", 0))
                        - (tick_bp1 or prev_cache.get("bid_price", 0)),
                        2,
                    ),
                    "volume": int(cumulative_volume or 0),
                    "oi": int(tick_oi or 0) if tick_oi else prev_cache.get("oi", 0),
                    "open": tick_open if tick_open else prev_cache.get("open", 0),
                    "high": tick_high if tick_high else prev_cache.get("high", 0),
                    "low": tick_low if tick_low else prev_cache.get("low", 0),
                    "close": prev_close,
                    "change": change,
                    "percent_change": change_pct,
                    "avg_price": self._safe_float(data.get("ap"))
                    or prev_cache.get("avg_price", 0),
                    "bid_qty": int(tick_bq1 or 0)
                    if tick_bq1
                    else prev_cache.get("bid_qty", 0),
                    "ask_qty": int(tick_sq1 or 0)
                    if tick_sq1
                    else prev_cache.get("ask_qty", 0),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "last_trade_time": tick_ltt or prev_cache.get("last_trade_time"),
                    "source": "live_ws",
                }

                await event_bus.emit(
                    Event(
                        type=EventType.FUTURES_QUOTE,
                        data={
                            "contract_symbol": canonical,
                            "quote": futures_quote,
                        },
                        source="live_ws",
                    )
                )
            except Exception as e:
                logger.debug(f"FUTURES_QUOTE emit failed for {canonical}: {e}")

    # ── Heartbeat ───────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to keep the connection alive."""
        try:
            while self._running and self._ws and not self._ws_is_closed():
                try:
                    hb_msg = json.dumps({"t": "h"})
                    await self._ws.send(hb_msg)
                    pong_waiter = await self._ws.ping()
                    await asyncio.wait_for(
                        pong_waiter,
                        timeout=self.HEARTBEAT_TIMEOUT,
                    )
                    logger.debug("Zebu heartbeat sent")
                except Exception as e:
                    logger.warning(f"Zebu heartbeat send failed: {e}")
                    break

                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            return

    # ── Subscriptions ───────────────────────────────────────────────

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to price updates for canonical symbols."""
        new_symbols = set()
        unresolved_symbols = set()

        # Batch-register missing NSE mappings from master contracts before per-symbol resolve.
        try:
            from services.contract_loader import ensure_nse_equity_mappings

            await ensure_nse_equity_mappings([self._fmt(s) for s in symbols if s])
        except Exception as e:
            logger.debug(f"Zebu subscribe master-contract preload skipped: {e}")

        for s in symbols:
            fmt = self._fmt(s)
            if fmt not in self._subscribed_symbols:
                # Resolve unknown symbols before subscribing
                if not canonical_to_zebu(fmt):
                    await self._resolve_symbol(fmt)
                if canonical_to_zebu(fmt):
                    new_symbols.add(fmt)
                else:
                    unresolved_symbols.add(fmt)

        if not new_symbols and not unresolved_symbols:
            return

        if self._status == ProviderStatus.CONNECTED and self._ws:
            if new_symbols:
                await self._send_subscribe(new_symbols)
                self._subscribed_symbols.update(new_symbols)
        else:
            # Queue for when connection is established
            if new_symbols:
                self._pending_subscribe.update(new_symbols)
                self._subscribed_symbols.update(new_symbols)
            logger.debug(
                f"Zebu: queued {len(new_symbols)} symbols for subscription (not connected)"
            )

        if unresolved_symbols:
            self._pending_subscribe.update(unresolved_symbols)
            logger.warning(
                f"Zebu unresolved symbols (token mapping missing): {sorted(unresolved_symbols)[:8]}"
            )

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from price updates."""
        remove_symbols = set()
        for s in symbols:
            fmt = self._fmt(s)
            if fmt in self._subscribed_symbols:
                remove_symbols.add(fmt)

        if not remove_symbols:
            return

        self._subscribed_symbols -= remove_symbols
        self._pending_subscribe -= remove_symbols

        if self._status == ProviderStatus.CONNECTED and self._ws:
            await self._send_unsubscribe(remove_symbols)

    async def _send_subscribe(self, symbols: set[str]) -> None:
        """Send subscription request to Zebu for the given canonical symbols."""
        scrip_list = self._build_scrip_list(symbols)
        if not scrip_list:
            logger.warning(
                f"[MCX SUBSCRIBE EMPTY] _build_scrip_list returned empty for: "
                f"{sorted(symbols)[:10]}"
            )
            return

        # Log commodity-specific subscribe details
        mcx_pairs = [p for p in scrip_list.split("#") if p.startswith(("MCX|", "NCDEX|"))]
        if mcx_pairs:
            logger.info(
                f"[MCX SUBSCRIBE] {len(mcx_pairs)} commodity pairs: {mcx_pairs}"
            )
        for sym in symbols:
            mapping = canonical_to_zebu(sym)
            if mapping and mapping.get("exchange") in ("MCX", "NCDEX"):
                logger.info(
                    f"[MCX SUBSCRIBE DETAIL] {sym} → "
                    f"exchange={mapping['exchange']} token={mapping['token']} "
                    f"trading={mapping.get('trading_symbol')}"
                )

        msg = json.dumps(
            {
                "t": "t",  # touchline subscribe
                "k": scrip_list,
            }
        )
        try:
            if not is_safe_websocket_message({"t": "t"}):
                return
            await self._ws.send(msg)
            logger.info(f"Zebu subscribed: {scrip_list}")
        except Exception as e:
            logger.error(f"Zebu subscribe send failed: {e}")

    async def _send_unsubscribe(self, symbols: set[str]) -> None:
        """Send unsubscribe request to Zebu."""
        scrip_list = self._build_scrip_list(symbols)
        if not scrip_list:
            return

        msg = json.dumps(
            {
                "t": "u",  # touchline unsubscribe
                "k": scrip_list,
            }
        )
        try:
            if not is_safe_websocket_message({"t": "u"}):
                return
            await self._ws.send(msg)
            logger.info(f"Zebu unsubscribed: {scrip_list}")
        except Exception as e:
            logger.error(f"Zebu unsubscribe send failed: {e}")

    def get_subscribed_symbols(self) -> set[str]:
        return self._subscribed_symbols.copy()

    # ── Quote access + REST API ────────────────────────────────────

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch quotes for multiple symbols in parallel."""

        async def _fetch_one(sym: str):
            try:
                q = await self.get_quote(sym)
                return (self._fmt(sym), q)
            except Exception:
                return (self._fmt(sym), None)

        pairs = await asyncio.gather(*[_fetch_one(s) for s in symbols])
        return {sym: q for sym, q in pairs if q}

    # ── REST API helpers ────────────────────────────────────────────

    async def _rest_post(
        self,
        route: str,
        payload: dict,
        content_type: str = "application/x-www-form-urlencoded",
    ):
        """
        Send a jData-encoded POST to the Zebu/MYNT REST API.
        Returns parsed JSON (dict or list) on success, None on failure.
        """
        if not self._api_url:
            logger.warning("ZebuProvider REST call skipped — no api_url configured")
            return None
        if not self._session_token:
            logger.warning("ZebuProvider REST call skipped — no session token")
            return None

        url = f"{self._api_url}{route}"
        payload["uid"] = self._user_id
        payload["actid"] = self._user_id
        jdata = "jData=" + json.dumps(payload) + f"&jKey={self._session_token}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    data=jdata,
                    headers={"Content-Type": content_type},
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Zebu REST {route} HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    return None

                # Handle encoding — Zebu may return non-UTF-8 data
                raw = resp.content
                if not raw or not raw.strip():
                    logger.warning(f"Zebu REST {route} empty response")
                    return None

                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1", errors="replace")

                if not text.strip():
                    logger.warning(f"Zebu REST {route} blank response after decode")
                    return None

                result = json.loads(text)
                logger.debug(
                    f"Zebu REST {route} → {type(result).__name__} "
                    f"len={len(result) if isinstance(result, list) else 'dict'}"
                )
                return result
        except json.JSONDecodeError as e:
            logger.error(
                f"Zebu REST {route} JSON parse failed: {e} body={text[:200] if 'text' in dir() else '?'}"
            )
            return None
        except Exception as e:
            logger.error(f"Zebu REST {route} failed ({type(e).__name__}): {e}")
            return None

    async def _resolve_symbol(self, canonical: str) -> Optional[dict]:
        """
        Dynamically resolve a canonical symbol to its Zebu token via SearchScrip.
        Result is registered in the global symbol map for future calls.
        Returns the mapping dict or None if not found.

        Tries MCX exchange first for known commodity symbols, else NSE.
        """
        canonical_upper = str(canonical or "").strip().upper()
        base = canonical_upper.split(".")[0].upper()

        # Detect derivative contracts (examples: NIFTY30APR2026FUT, NIFTY24APR2523000CE).
        is_derivative = bool(
            re.search(r"\d", canonical_upper)
            and re.search(r"(FUT|CE|PE)$", canonical_upper)
        )

        derivative_root = ""
        derivative_search_terms: list[str] = []
        if is_derivative:
            derivative_root = re.split(r"\d", canonical_upper, maxsplit=1)[0].upper()
            if not derivative_root:
                derivative_root = canonical_upper

            derivative_search_terms.append(canonical_upper)
            # Convert YYYY-form contracts to YY-form (common Noren tsym style),
            # e.g. NIFTY30APR2026FUT -> NIFTY30APR26FUT.
            yy_variant = re.sub(
                r"(\d{2}[A-Z]{3})20(\d{2})(?=(FUT|CE|PE|F)$)",
                r"\1\2",
                canonical_upper,
            )
            if yy_variant != canonical_upper:
                derivative_search_terms.append(yy_variant)
            if derivative_root not in derivative_search_terms:
                derivative_search_terms.append(derivative_root)

            # Preserve order, remove duplicates.
            derivative_search_terms = list(dict.fromkeys(derivative_search_terms))

        # Determine candidate exchanges to search.
        if is_ncdex_symbol(canonical_upper):
            exchange_candidates = ["NCDEX"]
            search_text = base
        elif is_mcx_symbol(canonical_upper):
            exchange_candidates = ["MCX"]
            search_text = base
        elif is_commodity_symbol(canonical_upper):
            exchange_candidates = ["MCX", "NCDEX"]
            search_text = base
        elif is_derivative:
            if any(x in canonical_upper for x in ["SENSEX", "BANKEX"]):
                exchange_candidates = ["BFO", "NFO"]
            else:
                exchange_candidates = ["NFO", "BFO"]
            search_text = canonical_upper
        elif canonical_upper.endswith(".BO"):
            exchange_candidates = ["BSE"]
            search_text = base
        elif canonical_upper.endswith(".NS"):
            exchange_candidates = ["NSE"]
            search_text = base
        else:
            exchange_candidates = ["NSE", "BSE"]
            search_text = base

        # Prefer official NSE master contract tokens (exact symbol, no fuzzy fallbacks).
        try:
            from services.contract_loader import ensure_nse_equity_mappings

            await ensure_nse_equity_mappings([canonical_upper])
            mapped = canonical_to_zebu(canonical_upper)
            if mapped:
                logger.info(
                    "Resolved %s from NSE master contracts → token=%s",
                    canonical_upper,
                    mapped.get("token"),
                )
                return mapped
        except Exception as e:
            logger.debug(
                "NSE master ensure failed for %s: %s", canonical_upper, e
            )

        try:
            for exchange in exchange_candidates:
                if is_derivative:
                    search_terms = derivative_search_terms
                elif exchange in {"NSE", "BSE"}:
                    # Zebu cash symbols are registered as SYMBOL-EQ in SearchScrip.
                    search_terms = list(
                        dict.fromkeys([f"{base}-EQ", base, search_text])
                    )
                else:
                    search_terms = [search_text]
                values = []

                for term in search_terms:
                    data = await self._rest_post(
                        "/SearchScrip", {"exch": exchange, "stext": term}
                    )
                    if not data or data.get("stat") != "Ok":
                        continue
                    values.extend(data.get("values", []))

                if not values:
                    continue

                # Deduplicate by exchange+token+tsym while preserving order.
                deduped_values = []
                seen_keys = set()
                for item in values:
                    item_exch = str(item.get("exch") or exchange).strip().upper()
                    item_token = str(item.get("token") or "").strip()
                    item_tsym = str(item.get("tsym") or "").strip().upper()
                    dedup_key = (item_exch, item_token, item_tsym)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    deduped_values.append(item)

                values = deduped_values

                derivative_exact_candidates = {
                    s.upper() for s in derivative_search_terms if s
                }

                # Pass 1: strict exact match
                for item in values:
                    tsym = str(item.get("tsym", "")).strip().upper()
                    token = str(item.get("token", "")).strip()
                    if not token:
                        continue

                    if exchange == "MCX" and (tsym == base or tsym.startswith(base)):
                        # Additional check: ensure it's a futures contract, not an unrelated symbol
                        if tsym == base or (tsym.startswith(base) and tsym.endswith(("FUT", "F"))):
                            load_zebu_contracts(
                                [
                                    {
                                        "symbol": base,
                                        "canonical": canonical_upper,
                                        "token": token,
                                        "exchange": "MCX",
                                        "trading_symbol": tsym,
                                    }
                                ]
                            )
                            logger.info(
                                f"Dynamically resolved MCX {canonical_upper} → token={token} tsym={tsym}"
                            )
                            return canonical_to_zebu(canonical_upper)

                    if is_derivative and tsym in derivative_exact_candidates:
                        load_zebu_contracts(
                            [
                                {
                                    "symbol": canonical_upper,
                                    "canonical": canonical_upper,
                                    "token": token,
                                    "exchange": exchange,
                                    "trading_symbol": tsym,
                                }
                            ]
                        )
                        logger.info(
                            f"Dynamically resolved derivative {canonical_upper} ({exchange}) → token={token}"
                        )
                        return canonical_to_zebu(canonical_upper)

                    if (
                        not is_derivative
                        and exchange in {"NSE", "BSE"}
                        and tsym in {base, f"{base}-EQ"}
                    ):
                        load_zebu_contracts(
                            [
                                {
                                    "symbol": base,
                                    "token": token,
                                    "exchange": exchange,
                                    "trading_symbol": tsym,
                                }
                            ]
                        )
                        logger.info(
                            f"Dynamically resolved equity {canonical_upper} ({exchange}) → token={token}"
                        )
                        return canonical_to_zebu(canonical_upper)

                # Pass 2: fuzzy fallback for derivatives/MCX if exact not present
                for item in values:
                    tsym = str(item.get("tsym", "")).strip().upper()
                    token = str(item.get("token", "")).strip()
                    if not token:
                        continue

                    if exchange == "MCX" and base in tsym:
                        load_zebu_contracts(
                            [
                                {
                                    "symbol": base,
                                    "canonical": canonical_upper,
                                    "token": token,
                                    "exchange": "MCX",
                                    "trading_symbol": tsym,
                                }
                            ]
                        )
                        logger.info(
                            f"Dynamically resolved MCX {canonical_upper} → token={token} tsym={tsym} (fuzzy)"
                        )
                        return canonical_to_zebu(canonical_upper)

                    if (
                        is_derivative
                        and derivative_root
                        and derivative_root in tsym
                        and tsym.endswith(("FUT", "CE", "PE", "F"))
                    ):
                        load_zebu_contracts(
                            [
                                {
                                    "symbol": canonical_upper,
                                    "canonical": canonical_upper,
                                    "token": token,
                                    "exchange": exchange,
                                    "trading_symbol": tsym,
                                }
                            ]
                        )
                        logger.info(
                            f"Dynamically resolved derivative {canonical_upper} ({exchange}) → token={token} tsym={tsym} (fuzzy)"
                        )
                        return canonical_to_zebu(canonical_upper)

        except Exception as e:
            logger.warning(f"SearchScrip resolve failed for {canonical}: {e}")
        return None

    def _extract_quote_metrics(
        self, data: dict, lp: float, prev_cache: Optional[dict] = None
    ) -> dict:
        """
        Build change fields from Zebu quote payloads without inventing values.

        Zebu sends previous close as "c" for many NSE payloads, while BSE
        payloads commonly expose percent change as "pc". If only "pc" is
        present, derive previous close/change from Zebu's own LTP and percent.
        """
        prev_cache = prev_cache or {}

        def first_float(*keys):
            for key in keys:
                if key in data and data.get(key) is not None:
                    parsed = self._safe_float(data.get(key))
                    if parsed is not None:
                        return parsed
            return None

        prev_close = first_float("c", "prev_close", "prevClose", "previous_close", "close")
        if prev_close is None:
            prev_close = self._safe_float(prev_cache.get("prev_close"))
        if prev_close is not None and prev_close <= 0:
            prev_close = None

        change = first_float("change", "net_change", "netChange", "price_change")
        change_pct = first_float(
            "pc",
            "change_percent",
            "changePercent",
            "pct_change",
            "pChange",
            "percent_change",
        )

        if change is None and prev_close:
            change = lp - prev_close
        if change_pct is None and prev_close:
            change_pct = (lp - prev_close) / prev_close * 100

        if (prev_close is None or prev_close <= 0) and change is not None:
            derived_prev = lp - change
            if derived_prev > 0:
                prev_close = derived_prev
                if change_pct is None:
                    change_pct = (change / prev_close) * 100

        if (prev_close is None or prev_close <= 0) and change_pct is not None:
            denominator = 1 + (change_pct / 100)
            if denominator > 0:
                prev_close = lp / denominator
                if prev_close > 0 and change is None:
                    change = lp - prev_close

        return {
            "prev_close": round(prev_close, 2) if prev_close is not None else None,
            "change": round(change, 2) if change is not None else None,
            "change_percent": round(change_pct, 2) if change_pct is not None else None,
        }

    async def get_rest_quote(self, symbol: str) -> Optional[dict]:
        """
        Fetch a single quote via Zebu REST /GetQuotes endpoint.
        Used when WebSocket cache has no data yet — broker token required.
        """
        symbol = self._fmt(symbol)
        mapping = canonical_to_zebu(symbol)
        if not mapping:
            try:
                from services.contract_loader import ensure_nse_equity_mappings

                await ensure_nse_equity_mappings([symbol])
                mapping = canonical_to_zebu(symbol)
            except Exception:
                pass
        if not mapping:
            mapping = await self._resolve_symbol(symbol)
        if not mapping:
            logger.warning(
                "No Zebu mapping for REST quote: %s (NSE master + SearchScrip failed)",
                symbol,
            )
            return None

        data = await self._rest_post(
            "/GetQuotes",
            {
                "exch": mapping["exchange"],
                "token": mapping["token"],
            },
        )
        if not data or data.get("stat") != "Ok":
            return None

        lp = self._safe_float(data.get("lp"))
        if lp is None or lp <= 0:
            return None

        metrics = self._extract_quote_metrics(data, lp)
        prev_close = metrics["prev_close"]

        quote = {
            "symbol": symbol,
            "name": data.get("tsym", symbol).replace("-EQ", ""),
            "price": lp,
            "change": metrics["change"],
            "change_percent": metrics["change_percent"],
            "open": self._safe_float(data.get("o", 0)),
            "high": self._safe_float(data.get("h", 0)),
            "low": self._safe_float(data.get("l", 0)),
            "close": prev_close,
            "prev_close": prev_close,
            "volume": int(self._safe_float(data.get("v", 0)) or 0),
            "bid_price": self._safe_float(data.get("bp1", 0)),
            "ask_price": self._safe_float(data.get("sp1", 0)),
            "bid_qty": int(self._safe_float(data.get("bq1", 0)) or 0),
            "ask_qty": int(self._safe_float(data.get("sq1", 0)) or 0),
            "oi": int(self._safe_float(data.get("oi", 0)) or 0),
            "market_cap": 0,
            "exchange": mapping["exchange"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "last_trade_time": data.get("ltt") or data.get("ft"),
        }

        # Update local cache so future get_quote() calls return this
        self._price_cache[symbol] = quote
        return quote

    async def get_quote(self, symbol: str) -> Optional[dict]:
        """
        Get latest quote — WebSocket cache first, then REST fallback.
        Also auto-subscribes the symbol to the WS feed if not already tracked.
        """
        symbol = self._fmt(symbol)
        stream_stale = self._is_stream_stale()

        # 1. In-memory cache (fastest — populated by WS ticks)
        if symbol in self._price_cache:
            cached_quote = self._price_cache[symbol]
            if not self._is_quote_stale(cached_quote):
                return cached_quote

        # 2. Ensure symbol mapping exists so WS subscription can be made.
        if not canonical_to_zebu(symbol):
            try:
                await self._resolve_symbol(symbol)
            except Exception:
                pass

        # 3. REST API fetch (optional) — controlled by config strictness.
        # When STRICT_ZEBU_MARKET_DATA is True we avoid REST fallbacks and
        # return None so callers do not receive stale or synthetic values.
        try:
            from config.settings import settings
            allow_rest = not getattr(settings, "STRICT_ZEBU_MARKET_DATA", True) == True
        except Exception:
            allow_rest = False

        quote = None
        if allow_rest:
            quote = await self.get_rest_quote(symbol)

        # 4. Auto-subscribe to WS so future quotes arrive via ticks
        if symbol not in self._subscribed_symbols and canonical_to_zebu(symbol):
            asyncio.create_task(self.subscribe([symbol]))

        return quote

    # ── Historical data (Zebu REST) ─────────────────────────────────

    # Map API interval strings to Zebu TPSeries intervals (minutes)
    # TPSeries only supports: 1, 3, 5, 10, 15, 30, 60, 120, 240
    # Daily data uses EODChartData endpoint instead
    _INTERVAL_MAP = {
        "1m": "1",
        "3m": "3",
        "5m": "5",
        "10m": "10",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "1d": "D",  # sentinel — routes to EODChartData
        "1wk": "D",  # sentinel — routes to EODChartData
        "1mo": "D",  # sentinel — routes to EODChartData
    }

    # Map period strings to number of calendar days
    _PERIOD_DAYS = {
        "1d": 1,
        "5d": 5,
        "1mo": 30,
        "3mo": 90,
        "6mo": 180,
        "1y": 365,
        "2y": 730,
        "3y": 1095,
        "5y": 1825,
        "max": 3650,
    }

    async def get_historical_data(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> list:
        """
        Fetch historical OHLCV candle data from Zebu REST API.

        Uses /TPSeries for intraday intervals and /EODChartData for daily+.
        Returns list of dicts: [{time, open, high, low, close, volume}, ...]
        """
        symbol = self._fmt(symbol)
        mapping = canonical_to_zebu(symbol)
        if not mapping:
            mapping = await self._resolve_symbol(symbol)
        if not mapping:
            logger.warning(f"No Zebu mapping for history: {symbol}")
            return []

        # Calculate time range
        days = self._PERIOD_DAYS.get(period, 30)
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        st_epoch = int(start_time.timestamp())
        et_epoch = int(end_time.timestamp())

        zebu_interval = self._INTERVAL_MAP.get(interval, "D")

        logger.info(
            f"Zebu history: {symbol} exch={mapping['exchange']} token={mapping['token']} "
            f"interval={zebu_interval} period={period} days={days} "
            f"st={st_epoch} et={et_epoch}"
        )

        if interval == "2m":
            # Zebu does not expose a native 2-minute interval here.
            # Build it from 1-minute candles so the UI can render 2m charts
            # after restarts and during live sessions.
            one_minute_candles = await self._fetch_tp_series(
                mapping["exchange"],
                mapping["token"],
                st_epoch,
                et_epoch,
                self._INTERVAL_MAP["1m"],
            )
            candles = self._aggregate_intraday_candles(one_minute_candles, 2)
            logger.info(
                f"Zebu history: {symbol} → {len(candles)} aggregated 2m candles"
            )
            return candles

        if zebu_interval == "D":
            # Use EODChartData for daily data — needs trading_symbol
            candles = await self._fetch_eod_data(
                mapping["exchange"], mapping["trading_symbol"], st_epoch, et_epoch
            )
        else:
            # Use TPSeries for intraday data — needs token
            candles = await self._fetch_tp_series(
                mapping["exchange"], mapping["token"], st_epoch, et_epoch, zebu_interval
            )

        logger.info(f"Zebu history: {symbol} → {len(candles)} candles")
        return candles

    async def _fetch_tp_series(
        self, exchange: str, token: str, st_epoch: int, et_epoch: int, interval: str
    ) -> list:
        """
        Fetch intraday candles from Zebu /TPSeries endpoint.

        interval: minutes as string — valid: 1, 3, 5, 10, 15, 30, 60, 120, 240
        """
        payload = {
            "ordersource": "API",
            "exch": exchange,
            "token": token,
            "st": str(st_epoch),
            "et": str(et_epoch),
            "intrv": interval,
        }
        logger.info(
            f"Zebu TPSeries request: exch={payload['exch']} token={payload['token']} intrv={interval}"
        )
        data = await self._rest_post("/TPSeries", payload)

        if not data:
            logger.warning("Zebu TPSeries returned None/empty")
            return []

        logger.debug(
            f"Zebu TPSeries response type={type(data).__name__} "
            f"len={len(data) if isinstance(data, list) else 1} "
            f"sample={str(data[:1] if isinstance(data, list) else data)[:300]}"
        )

        # TPSeries normally returns candle dicts directly, but some exchange
        # segments can mirror EODChartData and return JSON strings.
        if isinstance(data, list):
            parsed = []
            for item in data:
                if isinstance(item, str):
                    try:
                        parsed.append(json.loads(item))
                    except json.JSONDecodeError:
                        continue
                elif isinstance(item, dict):
                    parsed.append(item)
            return self._parse_candles(parsed)

        # Single dict — could be an error or a single candle
        if isinstance(data, dict):
            if data.get("stat") == "Not_Ok":
                logger.warning(f"Zebu TPSeries error: {data.get('emsg', 'unknown')}")
                return []
            return self._parse_candles([data])

        return []

    async def _fetch_eod_data(
        self, exchange: str, trading_symbol: str, st_epoch: int, et_epoch: int
    ) -> list:
        """
        Fetch daily candles from Zebu /EODChartData endpoint.

        Uses sym=EXCHANGE:TRADING_SYMBOL, from=epoch, to=epoch format.
        """
        sym_str = f"{exchange}:{trading_symbol}"
        payload = {
            "sym": sym_str,
            "from": str(st_epoch),
            "to": str(et_epoch),
        }
        logger.info(f"Zebu EODChartData request: sym={sym_str}")
        data = await self._rest_post(
            "/EODChartData", payload, content_type="application/x-www-form-urlencoded"
        )

        if not data:
            logger.warning("Zebu EODChartData returned None/empty")
            return []

        # EODChartData returns a list of JSON *strings*, not dicts.
        # Each element like: '{"time":"02-MAR-2026", "into":"1375.50", ...}'
        if isinstance(data, list):
            parsed = []
            for item in data:
                if isinstance(item, str):
                    try:
                        parsed.append(json.loads(item))
                    except json.JSONDecodeError:
                        continue
                elif isinstance(item, dict):
                    parsed.append(item)
            logger.debug(
                f"Zebu EODChartData parsed {len(parsed)} candle dicts from {len(data)} items"
            )
            return self._parse_candles(parsed)

        if isinstance(data, dict):
            if data.get("stat") == "Not_Ok":
                logger.warning(
                    f"Zebu EODChartData error: {data.get('emsg', 'unknown')}"
                )
                return []
            return self._parse_candles([data])

        return []

    @staticmethod
    def _raw_candle_field(c: dict, *names: str):
        """Case-insensitive candle field lookup (Zebu keys vary by segment)."""
        if not c:
            return None
        lower_map = {str(k).lower(): v for k, v in c.items()}
        for name in names:
            key = str(name).lower()
            if key in lower_map:
                return lower_map[key]
        return None

    @staticmethod
    def _resolve_bar_volume(c: dict, prev_cumulative_v: int | None) -> tuple[int, int | None]:
        """
        Resolve per-bar volume from Zebu candle fields.

        Index feeds (NIFTY/SENSEX) often send intv=0 and only cumulative session
        volume in `v`. Convert cumulative → interval delta for chart histograms.
        """
        bar_vol = 0
        next_cumulative = prev_cumulative_v

        intv_raw = ZebuProvider._raw_candle_field(c, "intv", "INTV", "intervalvolume")
        if intv_raw is not None and str(intv_raw).strip() != "":
            intv_val = int(ZebuProvider._safe_float(intv_raw) or 0)
            if intv_val > 0:
                return intv_val, next_cumulative

        cum_raw = ZebuProvider._raw_candle_field(c, "v", "V", "vol", "volume", "ttv", "tq")
        if cum_raw is not None and str(cum_raw).strip() != "":
            cum_v = int(ZebuProvider._safe_float(cum_raw) or 0)
            if cum_v > 0:
                if prev_cumulative_v is None:
                    # First candle in a response window: treat as bar volume.
                    # This avoids dropping the first non-zero bar to 0.
                    bar_vol = cum_v
                elif cum_v >= prev_cumulative_v:
                    # Monotonic cumulative session volume -> per-bar delta.
                    bar_vol = cum_v - prev_cumulative_v
                else:
                    # Some feeds reset/restart cumulative volume mid-series, or
                    # intermittently send per-bar values in `v`. Keep the candle
                    # tradable by falling back to the reported value.
                    bar_vol = cum_v
                next_cumulative = cum_v
                return max(0, bar_vol), next_cumulative

        for alt_key in ("vo", "trdqty", "dq", "qty"):
            alt_raw = ZebuProvider._raw_candle_field(c, alt_key)
            if alt_raw is not None and str(alt_raw).strip() != "":
                alt = int(ZebuProvider._safe_float(alt_raw) or 0)
                if alt > 0:
                    return alt, next_cumulative

        oi_raw = ZebuProvider._raw_candle_field(c, "oi", "OI")
        oi_val = int(ZebuProvider._safe_float(oi_raw or 0) or 0)
        return max(0, oi_val), next_cumulative

    @staticmethod
    def _convert_monotonic_volumes_to_deltas(candles: list[dict]) -> list[dict]:
        """If volumes look like cumulative session totals, convert to bar deltas."""
        if not candles or len(candles) < 2:
            return candles

        vols = [int(c.get("volume") or 0) for c in candles]
        positives = [v for v in vols if v > 0]
        if len(positives) < 3:
            return candles

        monotonic = all(positives[i] <= positives[i + 1] for i in range(len(positives) - 1))
        if not monotonic or positives[-1] <= positives[0]:
            return candles

        prev = 0
        out = []
        for c in candles:
            raw_v = int(c.get("volume") or 0)
            if raw_v > prev:
                bar_v = raw_v - prev
                prev = raw_v
            else:
                bar_v = max(0, raw_v)
                if raw_v > 0:
                    prev = raw_v
            out.append({**c, "volume": max(0, bar_v)})
        return out

    def _parse_candles(self, raw_candles: list) -> list:
        """
        Parse Zebu candle data into lightweight-charts format.

        Zebu TPSeries response per candle:
            {"stat":"Ok","time":"14-02-2025 09:15:00","into":"1290.00",
             "inth":"1295.00","intl":"1285.00","intc":"1292.00","intv":"12345",
             "intvwap":"1290.50","oi":"0","ssboe":"1739506500","v":"123456"}
        Also supports EOD format with slightly different keys.
        """
        candles = []
        prev_cumulative_v: int | None = None
        last_log_ts: int | None = None
        for c in raw_candles:
            if not isinstance(c, dict):
                continue

            # Parse timestamp — Zebu sends multiple formats:
            #   TPSeries:  "DD-MM-YYYY HH:MM:SS" or epoch in ssboe
            #   EODChart:  "DD-MMM-YYYY" e.g. "02-MAR-2026"
            # Return canonical Unix seconds (UTC epoch). Do not pre-shift
            # to IST here; frontend/chart should use one consistent timeline.
            ts = None
            if "ssboe" in c:
                try:
                    ts = int(c["ssboe"])
                except (ValueError, TypeError):
                    pass
            if ts is None and "time" in c:
                for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        dt = datetime.strptime(c["time"], fmt)
                        # Intraday TPSeries timestamps include clock time and are IST wall-clock.
                        # Date-only EOD timestamps should remain on their calendar date boundary,
                        # so store them at UTC midnight to avoid off-by-one-day shifts later.
                        if "%H" in fmt:
                            dt_value = dt.replace(
                                tzinfo=timezone(timedelta(hours=5, minutes=30))
                            )
                        else:
                            dt_value = dt.replace(tzinfo=timezone.utc)
                        ts = int(dt_value.timestamp())
                        break
                    except (ValueError, TypeError):
                        continue

            if ts is None:
                continue

            # Parse OHLCV — Zebu uses into/inth/intl/intc/intv for intraday
            # NOTE: Use explicit key checks — Python's `or` chain treats 0, "",
            # and 0.0 as falsy, which incorrectly skips valid zero values and
            # falls through to cumulative fields (e.g. intv=0 → uses cum. vol v).
            o = self._safe_float(c["into"] if "into" in c else c.get("o"))
            h = self._safe_float(c["inth"] if "inth" in c else c.get("h"))
            l = self._safe_float(c["intl"] if "intl" in c else c.get("l"))
            cl = self._safe_float(c["intc"] if "intc" in c else c.get("c"))

            bar_vol, prev_cumulative_v = self._resolve_bar_volume(c, prev_cumulative_v)

            if o is None or h is None or l is None or cl is None:
                continue

            candles.append(
                {
                    "time": ts,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": bar_vol,
                }
            )

            # Index-only debug: inspect raw cumulative/intv to validate bar-volume conversion.
            ts_log = int(ts // 60) if ts is not None else None
            raw_sym = str(c.get("ts") or c.get("symbol") or "").upper()
            if raw_sym.startswith(("NIFTY", "SENSEX", "BANKNIFTY")) and ts_log != last_log_ts:
                last_log_ts = ts_log
                logger.debug(
                    "Zebu index volume parse sym=%s ts=%s intv=%s v=%s bar=%s prev_cum=%s",
                    raw_sym,
                    ts,
                    ZebuProvider._raw_candle_field(c, "intv", "INTV", "intervalvolume"),
                    ZebuProvider._raw_candle_field(c, "v", "V", "vol", "volume", "ttv", "tq"),
                    bar_vol,
                    prev_cumulative_v,
                )

        # Sort by time ascending (lightweight-charts requires sorted data)
        candles.sort(key=lambda x: x["time"])
        return self._convert_monotonic_volumes_to_deltas(candles)

    @staticmethod
    def _aggregate_intraday_candles(candles: list[dict], minutes: int) -> list[dict]:
        """Aggregate 1m candles into larger intraday buckets."""
        if not candles or minutes <= 1:
            return candles or []

        bucket_seconds = minutes * 60
        aggregated: list[dict] = []
        current_bucket = None
        current = None

        for candle in candles:
            try:
                ts = int(candle.get("time"))
                o = float(candle.get("open"))
                h = float(candle.get("high"))
                l = float(candle.get("low"))
                cl = float(candle.get("close"))
                v = int(float(candle.get("volume", 0) or 0))
            except (TypeError, ValueError):
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

    async def health(self) -> ProviderHealth:
        uptime = (time.time() - self._started_at) if self._started_at else 0
        last_tick = (
            datetime.utcfromtimestamp(self._last_tick_at).isoformat()
            if self._last_tick_at
            else None
        )
        return ProviderHealth(
            status=self._status,
            provider_name="zebu",
            subscribed_symbols=len(self._subscribed_symbols),
            last_tick_at=last_tick,
            uptime_seconds=uptime,
            reconnect_count=self._reconnect_count,
        )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _fmt(symbol: str) -> str:
        """Normalise symbol to canonical form.

        NSE equities get .NS suffix.
        MCX commodities, derivatives, and indices are left as-is.
        """
        clean = str(symbol or "").strip().upper()
        if not clean:
            return clean

        if clean.startswith("^") or clean.endswith((".NS", ".BO", "=F")):
            return clean
        if is_mcx_symbol(clean):
            return clean

        if re.search(r"\d", clean) and re.search(r"(FUT|CE|PE)$", clean):
            return clean

        return f"{clean}.NS"

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        """Safely parse a float from string or number."""
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _is_quote_stale(cls, quote: dict) -> bool:
        if not isinstance(quote, dict):
            return True

        raw_ts = quote.get("timestamp")
        if not raw_ts:
            return True

        quote_epoch = None
        if isinstance(raw_ts, (int, float)):
            quote_epoch = float(raw_ts)
        else:
            raw_str = str(raw_ts).strip()
            try:
                if raw_str.endswith("Z"):
                    raw_str = raw_str[:-1] + "+00:00"
                quote_epoch = datetime.fromisoformat(raw_str).timestamp()
            except Exception:
                try:
                    quote_epoch = float(raw_str)
                except (ValueError, TypeError):
                    quote_epoch = None

        if quote_epoch is None:
            return True

        return (time.time() - quote_epoch) > cls.QUOTE_STALE_SECONDS

    def _is_stream_stale(self) -> bool:
        if self._last_tick_at is None:
            return False
        return (time.time() - self._last_tick_at) > self.STREAM_STALE_SECONDS

    @staticmethod
    def _build_scrip_list(symbols: set[str]) -> str:
        """
        Build Zebu scrip list string from canonical symbols.

        Format: "NSE|2885#NSE|11536"  (exchange|token pairs joined by #)
        """
        parts = []
        for sym in symbols:
            mapping = canonical_to_zebu(sym)
            if mapping:
                parts.append(f"{mapping['exchange']}|{mapping['token']}")
            else:
                logger.warning(f"No Zebu mapping for symbol: {sym}")
        return "#".join(parts)
