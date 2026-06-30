"""
AliceBlueProvider — Real-time market data via Alice Blue ANT OpenAPI WebSocket.

Alice Blue v2 API (https://v2api.aliceblueonline.com/):
    - WebSocket URL  : wss://ws1.aliceblueonline.com/NorenWS
    - REST API base  : https://a3.aliceblueonline.com/open-api
    - WS session init: POST /od/v1/profile/createWsSess
    - Historical data: POST /od/ChartAPIService/api/chart/history
    - Auth header    : Authorization: Bearer <userSession>  (session token only)
    - WS auth        : susertoken = sha256(sha256(session_id)), uid/actid = "<client_id>_API"
    - Heartbeat      : {"t":"h","k":""} every 50 s
    - Subscribe tick : {"t":"t","k":"EXCHANGE|TOKEN#..."}
    - Subscribe depth: {"t":"d","k":"EXCHANGE|TOKEN#..."}
    - Timestamps     : milliseconds (UNIX epoch * 1000) for historical API

Token/symbol mapping: reuses the same NSE token IDs as Zebu (exchange-standardised).
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from providers.base import MarketProvider, ProviderHealth, ProviderStatus
from providers.symbol_mapper import (
    canonical_to_zebu,
    zebu_token_to_canonical,
    load_zebu_contracts,
    is_commodity_symbol,
    is_mcx_symbol,
    is_ncdex_symbol,
    mirror_canonicals_for_quote,
)

logger = logging.getLogger(__name__)


class AliceBlueProvider(MarketProvider):
    """
    Alice Blue market data provider via ANT OpenAPI WebSocket (NorenOMS protocol).

    Each user gets their own instance created by BrokerSessionManager after OAuth.

    Implements all the same methods as ZebuProvider so that existing routes
    (options.py, broker.py segment-check, etc.) work transparently with Alice Blue.
    """

    RECONNECT_BASE_DELAY = 1.0
    RECONNECT_MAX_DELAY = 60.0
    RECONNECT_BACKOFF_FACTOR = 2.0
    MAX_RECONNECT_ATTEMPTS = 50
    # Docs say: "Send heartbeat once in every 50 seconds"
    HEARTBEAT_INTERVAL = 50.0
    HEARTBEAT_TIMEOUT = 15.0
    QUOTE_STALE_SECONDS = 20.0
    STREAM_STALE_SECONDS = 60.0

    # Alice Blue REST endpoint map — maps Zebu NorenOMS route names to
    # Alice Blue v2 API paths.
    # Note: Alice Blue does NOT expose SearchScrip/GetOptionChain via its
    # REST API the same way Zebu does. We handle those via:
    #   - SearchScrip  → contract master CDN (already handled by options.py)
    #   - GetOptionChain → same CDN zips + WS-based live ticks
    #   - GetQuotes → try WS cache first, then getScripQuoteDetails (old ANT API)
    #
    # Historical data docs: https://v2api.aliceblueonline.com/Historical%20Data/
    # Correct endpoint: POST https://a3.aliceblueonline.com/open-api/od/ChartAPIService/api/chart/history
    _AB_ROUTE_MAP = {
        "/SearchScrip":      None,     # No direct equivalent; handled via CDN
        "/GetQuotes":        None,     # Handled via WS cache / _alice_get_quotes
        "/GetOptionChain":   None,     # No direct equivalent; handled via CDN
        "/TPSeries":         "/od/ChartAPIService/api/chart/history",
        "/EODChartData":     "/od/ChartAPIService/api/chart/history",
    }

    # Alice Blue v2 API base URL (from official docs)
    # All REST calls go to a3.aliceblueonline.com/open-api
    _AB_REST_BASE = "https://a3.aliceblueonline.com/open-api"

    # NSE/BSE market hours: 09:15 – 15:30 IST, Mon–Fri
    # MCX market hours: 09:00 – 23:30 IST, Mon–Fri (approx)
    _MARKET_TZ = timezone(timedelta(hours=5, minutes=30))  # IST = UTC+5:30

    def __init__(
        self,
        ws_url: str,
        user_id: str,
        session_token: str,       # SID / userSession from Alice Blue session endpoint
        api_url: str = "",
        access_token: str = "",   # Bearer token (for REST calls) – optional
        redis_client=None,
    ):
        self._ws_url = ws_url
        self._user_id = user_id
        self._session_token = session_token   # used as susertoken in WS auth
        self._access_token = access_token or f"{user_id} {session_token}"
        self._api_url = api_url.rstrip("/") if api_url else ""
        self._redis = redis_client

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._status = ProviderStatus.DISCONNECTED
        self._started_at: Optional[float] = None
        self._last_tick_at: Optional[float] = None
        self._reconnect_count = 0
        self._consecutive_failures = 0

        self._subscribed_symbols: set[str] = set()
        self._pending_subscribe: set[str] = set()
        self._price_cache: dict[str, dict] = {}

        self._recv_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self._credential_lock = asyncio.Lock()

    def _ws_is_closed(self) -> bool:
        if not self._ws:
            return True
        try:
            return self._ws.closed
        except AttributeError:
            return self._ws.close_code is not None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._started_at = time.time()
        logger.info(
            f"AliceBlueProvider.start() | user={str(self._user_id)[:8] if self._user_id else 'NONE'} "
            f"| has_token={bool(self._session_token)}"
        )
        if not self._session_token:
            logger.warning("AliceBlueProvider started without session token")
            self._status = ProviderStatus.DISCONNECTED
            return
        await self._connect()

    async def stop(self) -> None:
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
        logger.info("AliceBlueProvider stopped")

    async def update_credentials(self, user_id: str, session_token: str) -> None:
        async with self._credential_lock:
            self._user_id = user_id
            self._session_token = session_token
            if not session_token:
                if self._ws and not self._ws_is_closed():
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                self._status = ProviderStatus.DISCONNECTED
                return
            if self._running:
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
        return bool(self._user_id and self._session_token)

    # ── Connection ───────────────────────────────────────────────────

    async def _connect(self) -> None:
        self._status = ProviderStatus.CONNECTING
        try:
            # Create a WebSocket session via Alice Blue REST API before connecting
            ws_session_url = "https://a3.aliceblueonline.com/open-api/od/v1/profile/createWsSess"
            headers = {
                "Authorization": f"Bearer {self._session_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "source": "API",
                "userId": self._user_id,
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(ws_session_url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        logger.info(f"Alice Blue WS session created successfully: {resp.text}")
                    else:
                        logger.error(
                            f"Alice Blue WS session creation failed HTTP {resp.status_code}: {resp.text}"
                        )
                        self._status = ProviderStatus.ERROR
                        if self._running:
                            asyncio.create_task(self._reconnect())
                        return
            except Exception as e:
                logger.error(f"Alice Blue WS session creation request failed: {e}")
                self._status = ProviderStatus.ERROR
                if self._running:
                    asyncio.create_task(self._reconnect())
                return

            self._ws = await websockets.connect(
                self._ws_url,
                ping_interval=None,   # We manage heartbeats manually via {t:"h"}
                ping_timeout=None,
                close_timeout=10,
                max_size=2**20,
            )

            # Alice Blue: susertoken = double SHA-256 of the raw session token
            hashed_token = hashlib.sha256(
                hashlib.sha256(self._session_token.encode()).hexdigest().encode()
            ).hexdigest()

            # Alice Blue ANT auth — NorenOMS format, "_API" suffix on uid/actid
            # Docs: https://v2api.aliceblueonline.com/Websocket/
            auth_msg = {
                "t": "c",
                "uid": f"{self._user_id}_API",
                "actid": f"{self._user_id}_API",
                "susertoken": hashed_token,
                "source": "API",
            }
            await self._ws.send(json.dumps(auth_msg))
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            resp = json.loads(raw)

            # Docs: success response is {"t":"cf","k":"OK"}
            #       failure response is {"t":"cf","k":"failed"}
            msg_t = resp.get("t", "")
            msg_k = str(resp.get("k") or resp.get("s") or "").strip()
            auth_ok = (
                (msg_t == "cf" and msg_k.upper() == "OK")
                or msg_k.upper() == "OK"
                or resp.get("s", "").upper() == "OK"
            )
            if not auth_ok:
                logger.error(
                    f"AliceBlue WS auth failed: t={msg_t!r} k={msg_k!r} full={resp}"
                )
                self._status = ProviderStatus.ERROR
                if self._running:
                    asyncio.create_task(self._reconnect())
                return

            self._status = ProviderStatus.CONNECTED
            self._consecutive_failures = 0
            logger.info(
                f"[ALICEBLUE WS CONNECTED] user={str(self._user_id)[:8]}... "
                f"symbols={len(self._subscribed_symbols)}"
            )

            # Re-subscribe all active symbols after reconnect
            all_symbols = self._subscribed_symbols | self._pending_subscribe
            if all_symbols:
                await self._send_subscribe(all_symbols)
            self._subscribed_symbols.update(self._pending_subscribe)
            self._pending_subscribe.clear()

            self._recv_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except Exception as e:
            logger.error(f"AliceBlueProvider connection failed: {e}")
            self._status = ProviderStatus.ERROR
            if self._running:
                asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        if not self._running:
            return
        self._consecutive_failures += 1
        if self._consecutive_failures > self.MAX_RECONNECT_ATTEMPTS:
            logger.error("AliceBlue: max reconnect attempts reached")
            self._status = ProviderStatus.ERROR
            return
        delay = min(
            self.RECONNECT_BASE_DELAY * (self.RECONNECT_BACKOFF_FACTOR ** (self._consecutive_failures - 1)),
            self.RECONNECT_MAX_DELAY,
        )
        self._status = ProviderStatus.RECONNECTING
        self._reconnect_count += 1
        logger.warning(f"AliceBlue reconnecting in {delay:.1f}s (attempt {self._consecutive_failures})")
        await asyncio.sleep(delay)
        if self._running:
            await self._connect()

    # ── Receive loop ─────────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        try:
            async for raw_message in self._ws:
                if not self._running:
                    break
                try:
                    data = json.loads(raw_message)
                    msg_type = data.get("t")
                    if msg_type in ("tk", "tf"):
                        # Market feed: tk = tick acknowledgement, tf = tick feed
                        await self._handle_tick(data)
                    elif msg_type in ("dk", "df"):
                        # Depth feed: dk = depth ack, df = depth feed
                        # Extract lp/pc from depth messages too
                        await self._handle_tick(data)
                    elif msg_type == "cf":
                        # Connection feed — auth success/fail response (handled in _connect)
                        # May also arrive mid-session; log only
                        logger.debug(f"AliceBlue cf message: k={data.get('k')}")
                    elif msg_type == "hb":
                        logger.debug("[ALICEBLUE] Heartbeat ack")
                    elif msg_type == "ck":
                        # Legacy connection ack (some server versions)
                        pass
                except json.JSONDecodeError:
                    logger.warning(f"AliceBlue non-JSON: {raw_message[:100]}")
                except Exception as e:
                    logger.error(f"AliceBlue tick error: {e}", exc_info=True)
        except (ConnectionClosed, ConnectionClosedError) as e:
            logger.warning(f"AliceBlue WS closed: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"AliceBlue receive loop error: {e}", exc_info=True)
        if self._running:
            self._status = ProviderStatus.RECONNECTING
            asyncio.create_task(self._reconnect())

    async def _handle_tick(self, data: dict) -> None:
        """
        Parse Alice Blue WS tick (NorenOMS format).

        Field reference from official docs (https://v2api.aliceblueonline.com/Websocket/):
          t   = type (tk/tf = market tick ack/feed, dk/df = depth ack/feed)
          e   = exchange
          tk  = token
          ts  = symbol name (trading symbol)
          lp  = LTP (last traded price)
          pc  = percentage change
          cv  = change value (absolute price change)
          c   = close (= prev day close price)
          o   = open
          h   = high
          l   = low
          v   = volume
          oi  = open interest
          ap  = average price
          bp1..bp5 = depth buy prices
          sp1..sp5 = depth sell prices
          bq1..bq5 = depth buy quantities
          sq1..sq5 = depth sell quantities
        """
        token = data.get("tk", "")
        exchange = str(data.get("e") or "").strip().upper()
        canonical = zebu_token_to_canonical(token, exchange=exchange)
        if not canonical:
            return

        self._last_tick_at = time.time()
        lp = self._safe_float(data.get("lp"))
        if lp is None or lp <= 0:
            return

        prev_cache = self._price_cache.get(canonical, {})

        # "c" = close = previous day's close price (per docs)
        prev_close = (
            self._safe_float(data.get("c"))
            or self._safe_float(prev_cache.get("prev_close"))
        )

        # "pc" = percentage change (provided directly by Alice Blue)
        # "cv" = absolute change value
        pc_raw = self._safe_float(data.get("pc"))
        cv_raw = self._safe_float(data.get("cv"))
        change_pct = pc_raw if pc_raw is not None else (
            round((lp - prev_close) / prev_close * 100, 2) if prev_close else None
        )
        change = cv_raw if cv_raw is not None else (
            round(lp - prev_close, 2) if prev_close else None
        )

        prev_vol = int(prev_cache.get("volume", 0) or 0)
        tick_vol = self._safe_float(data.get("v"))
        if tick_vol is not None:
            cumulative_volume = int(tick_vol) if int(tick_vol) >= prev_vol else prev_vol + int(tick_vol)
        else:
            cumulative_volume = prev_vol

        quote = {
            "symbol": canonical,
            "name": str(data.get("ts") or prev_cache.get("name") or canonical).replace("-EQ", ""),
            "price": lp,
            "change": change,
            "change_percent": change_pct,
            "open": self._safe_float(data.get("o")) or prev_cache.get("open", 0),
            "high": self._safe_float(data.get("h")) or prev_cache.get("high", 0),
            "low": self._safe_float(data.get("l")) or prev_cache.get("low", 0),
            "close": prev_close,
            "prev_close": prev_close,
            "volume": int(cumulative_volume or 0),
            "bid_price": self._safe_float(data.get("bp1")) or prev_cache.get("bid_price", 0),
            "ask_price": self._safe_float(data.get("sp1")) or prev_cache.get("ask_price", 0),
            "bid_qty": int(self._safe_float(data.get("bq1")) or 0),
            "ask_qty": int(self._safe_float(data.get("sq1")) or 0),
            "oi": int(self._safe_float(data.get("oi")) or 0),
            "avg_price": self._safe_float(data.get("ap")) or prev_cache.get("avg_price", 0),
            "market_cap": 0,
            "exchange": exchange or prev_cache.get("exchange", "NSE"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "live_ws",
            # Zebu-compatible aliases for options chain compatibility
            "lp": lp,
            "ltp": lp,
            "stat": "Ok",
            "tsym": data.get("ts") or canonical,
            "token": str(token),
        }

        self._price_cache[canonical] = quote
        _changed = (
            prev_cache.get("price") != lp
            or prev_cache.get("volume") != quote["volume"]
        )

        try:
            from market.quote_coordinator import quote_coordinator
            mirrors = mirror_canonicals_for_quote(canonical)
            await quote_coordinator.ingest_equity_quote(
                canonical, quote, source="live_ws", changed=_changed,
                mirror_symbols=mirrors, write_redis=bool(self._redis), emit_event=True,
            )
        except Exception as e:
            logger.warning(f"AliceBlue coordinator ingest failed for {canonical}: {e}")

        # ── Futures: emit FUTURES_QUOTE for NFO/BFO ticks ─────────────
        if _changed and exchange in ("NFO", "BFO"):
            try:
                from core.event_bus import event_bus, Event, EventType

                tick_open = self._safe_float(data.get("o"))
                tick_high = self._safe_float(data.get("h"))
                tick_low = self._safe_float(data.get("l"))
                tick_bp1 = self._safe_float(data.get("bp1"))
                tick_sp1 = self._safe_float(data.get("sp1"))
                tick_bq1 = self._safe_float(data.get("bq1"))
                tick_sq1 = self._safe_float(data.get("sq1"))
                tick_oi = self._safe_float(data.get("oi"))
                tick_ltt = data.get("ltt") or data.get("ft")

                futures_quote = {
                    "contract_symbol": canonical,
                    "exchange": exchange,
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

    # ── Heartbeat ────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """
        Alice Blue heartbeat per official docs:
          Request:  {"k": "", "t": "h"}
          Interval: every 50 seconds (docs say: "Send heartbeat once in every 50 seconds")
          Response: NO response — server just keeps connection alive

        The "k" field must be empty string (not omitted) per the docs.
        No WS ping frames — server doesn't respond to them.
        """
        try:
            while self._running and self._ws and not self._ws_is_closed():
                try:
                    await self._ws.send(json.dumps({"t": "h", "k": ""}))
                    logger.debug("[ALICEBLUE] Heartbeat sent")
                except Exception as e:
                    logger.warning(f"AliceBlue heartbeat send failed: {e}")
                    break
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"AliceBlue heartbeat loop error: {e}")
        # If heartbeat died and we're still running, trigger reconnect
        if self._running and not self._ws_is_closed():
            self._status = ProviderStatus.RECONNECTING
            asyncio.create_task(self._reconnect())

    # ── Subscriptions ────────────────────────────────────────────────

    async def subscribe(self, symbols: list[str]) -> None:
        new_symbols = set()
        for s in symbols:
            fmt = self._fmt(s)
            if fmt in self._subscribed_symbols:
                continue
            # Try to get mapping; if not found, try to resolve it
            mapping = canonical_to_zebu(fmt)
            if not mapping:
                mapping = await self._resolve_symbol(fmt)
            if mapping:
                new_symbols.add(fmt)
            else:
                # For F&O contracts already registered via options CDN zip,
                # try direct lookup without normalization
                raw_mapping = canonical_to_zebu(s.upper().strip())
                if raw_mapping:
                    new_symbols.add(s.upper().strip())

        if not new_symbols:
            return
        if self._status == ProviderStatus.CONNECTED and self._ws:
            await self._send_subscribe(new_symbols)
            self._subscribed_symbols.update(new_symbols)
        else:
            self._pending_subscribe.update(new_symbols)
            self._subscribed_symbols.update(new_symbols)

    async def unsubscribe(self, symbols: list[str]) -> None:
        remove = set()
        for s in symbols:
            fmt = self._fmt(s)
            if fmt in self._subscribed_symbols:
                remove.add(fmt)
            raw = s.upper().strip()
            if raw in self._subscribed_symbols:
                remove.add(raw)
        if not remove:
            return
        self._subscribed_symbols -= remove
        self._pending_subscribe -= remove
        if self._status == ProviderStatus.CONNECTED and self._ws:
            await self._send_unsubscribe(remove)

    async def _send_subscribe(self, symbols: set[str]) -> None:
        scrip_list = self._build_scrip_list(symbols)
        if not scrip_list:
            logger.warning(f"[ALICEBLUE] _send_subscribe: no token mappings found for {symbols}")
            return
        msg = json.dumps({"t": "t", "k": scrip_list})
        try:
            await self._ws.send(msg)
            logger.info(f"AliceBlue subscribed: {scrip_list[:200]}")
        except Exception as e:
            logger.error(f"AliceBlue subscribe send failed: {e}")

    async def _send_unsubscribe(self, symbols: set[str]) -> None:
        scrip_list = self._build_scrip_list(symbols)
        if not scrip_list:
            return
        try:
            await self._ws.send(json.dumps({"t": "u", "k": scrip_list}))
        except Exception as e:
            logger.error(f"AliceBlue unsubscribe send failed: {e}")

    def get_subscribed_symbols(self) -> set[str]:
        return self._subscribed_symbols.copy()

    # ── REST API — compatible interface matching ZebuProvider._rest_post ───

    async def _rest_post(
        self,
        route: str,
        payload: dict,
        content_type: str = "application/x-www-form-urlencoded",
    ):
        """
        Emulate Zebu-style REST calls using Alice Blue's API.

        Alice Blue does NOT expose SearchScrip/GetOptionChain via its REST API
        the same way Zebu does. This method:

        - /SearchScrip  → returns None (CDN contract master is used instead)
        - /GetOptionChain → returns None (CDN-based chain building is used)
        - /GetQuotes    → tries WS price cache first, then Alice Blue's
                          getScripQuoteDetails REST endpoint
        - /TPSeries     → chart/history intraday candles
        - /EODChartData → chart/history daily candles

        Returns a dict with Zebu-compatible field names on success, None on failure.
        """
        if route in ("/SearchScrip", "/GetOptionChain"):
            # These are not available in Alice Blue REST API in the same format.
            # Callers fall back to CDN contract master + WS tick data.
            return None

        if route == "/GetQuotes":
            return await self._alice_get_quotes(payload)

        # For TPSeries / EODChartData, delegate to the history endpoint
        if route in ("/TPSeries", "/EODChartData"):
            return await self._alice_chart_history(route, payload)

        # Unknown route — attempt generic Bearer-auth GET
        if not self._api_url or not self._session_token:
            return None

        ab_route = self._AB_ROUTE_MAP.get(route, route)
        if ab_route is None:
            return None
        url = f"{self._api_url}{ab_route}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self._session_token}"},
                    params=payload,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"AliceBlue REST {route} HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    return None
                try:
                    return resp.json()
                except json.JSONDecodeError as e:
                    logger.error(f"AliceBlue REST {route} JSON parse failed: {e}")
                    return None
        except Exception as e:
            logger.error(f"AliceBlue REST {route} failed ({type(e).__name__}): {e}")
            return None

    async def _alice_get_quotes(self, payload: dict) -> Optional[dict]:
        """
        Translate Zebu GetQuotes into Alice Blue's getScripQuoteDetails.

        Priority:
        1. Return from in-process WS tick cache if fresh (avoids REST round-trip)
        2. Subscribe to symbol + wait up to 1.5s for WS tick (first-time access)
        3. Alice Blue getScripQuoteDetails REST endpoint
        4. Return None

        Returns a dict with Zebu-compatible fields (stat, lp, v, oi, bp1, sp1 …).
        """
        exch = str(payload.get("exch") or "").strip().upper()
        token = str(payload.get("token") or "").strip()
        if not exch or not token:
            return None

        def _build_ws_quote(cached: dict, canonical: str) -> dict:
            return {
                "stat": "Ok",
                "lp": str(cached.get("price", 0)),
                "ltp": str(cached.get("price", 0)),
                "o": str(cached.get("open", 0)),
                "h": str(cached.get("high", 0)),
                "l": str(cached.get("low", 0)),
                "c": str(cached.get("prev_close", 0)),
                "v": str(cached.get("volume", 0)),
                "oi": str(cached.get("oi", 0)),
                "bp1": str(cached.get("bid_price", 0)),
                "sp1": str(cached.get("ask_price", 0)),
                "bq1": str(cached.get("bid_qty", 0)),
                "sq1": str(cached.get("ask_qty", 0)),
                "ts": cached.get("name", canonical),
                "token": token,
                "tsym": cached.get("tsym") or canonical,
                "exchange": exch,
            }

        # 1. Check WS cache first — fastest path
        from providers.symbol_mapper import zebu_token_to_canonical
        canonical = zebu_token_to_canonical(token, exchange=exch)
        if canonical and canonical in self._price_cache:
            cached = self._price_cache[canonical]
            if not self._is_quote_stale(cached):
                return _build_ws_quote(cached, canonical)

        # 2. If symbol not yet subscribed, subscribe and wait up to 1.2s for tick
        #    This is the first-time access pattern (options chain on load).
        #    Alice Blue pushes ticks via WS when subscribed — we wait for the tick
        #    rather than hitting REST for every leg (which would be very slow).
        if canonical and canonical not in self._subscribed_symbols:
            # Subscribe directly using exchange|token format
            scrip_key = f"{exch}|{token}"
            if self._status == ProviderStatus.CONNECTED and self._ws and not self._ws_is_closed():
                try:
                    await self._ws.send(json.dumps({"t": "t", "k": scrip_key}))
                    self._subscribed_symbols.add(canonical)
                except Exception:
                    pass
            # Poll for tick arrival up to 1.2s
            deadline = time.time() + 1.2
            while time.time() < deadline:
                await asyncio.sleep(0.08)
                if canonical in self._price_cache:
                    cached = self._price_cache[canonical]
                    if not self._is_quote_stale(cached):
                        return _build_ws_quote(cached, canonical)

        # 3. Alice Blue REST: GET /ScripDetails/getScripQuoteDetails
        if not self._api_url or not self._session_token:
            return None
        try:
            url = f"{self._api_url}/ScripDetails/getScripQuoteDetails"
            headers = {"Authorization": f"Bearer {self._session_token}"}
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    url,
                    params={"exch": exch, "symbol": token},
                    headers=headers,
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                # Alice Blue response format → Zebu-compatible
                if not data:
                    return None
                # Handle list response (alice blue returns a list)
                item = data[0] if isinstance(data, list) and data else data
                if not isinstance(item, dict):
                    return None
                lp = str(item.get("ltp") or item.get("lp") or item.get("last_price") or 0)
                return {
                    "stat": "Ok",
                    "lp": lp,
                    "ltp": lp,
                    "o": str(item.get("open") or 0),
                    "h": str(item.get("high") or 0),
                    "l": str(item.get("low") or 0),
                    "c": str(item.get("prev_close") or item.get("close") or 0),
                    "v": str(item.get("volume") or item.get("vol") or 0),
                    "oi": str(item.get("oi") or item.get("open_interest") or 0),
                    "bp1": str(item.get("bid_price") or item.get("bp1") or 0),
                    "sp1": str(item.get("ask_price") or item.get("sp1") or 0),
                    "ts": str(item.get("symbol") or item.get("tsym") or token),
                    "token": token,
                    "tsym": str(item.get("symbol") or token),
                    "exchange": exch,
                }
        except Exception as e:
            logger.debug(f"AliceBlue getScripQuoteDetails failed for {exch}|{token}: {e}")
        return None

    async def _alice_chart_history(self, route: str, payload: dict) -> Optional[list]:
        """
        Alice Blue v2 historical chart data.

        Official docs: https://v2api.aliceblueonline.com/Historical%20Data/
          Method  : POST
          URL     : https://a3.aliceblueonline.com/open-api/od/ChartAPIService/api/chart/history
          Auth    : Authorization: Bearer <userSession>   ← session token ONLY, no user_id prefix
          Params  : token, resolution, from, to (ms), exchange
          Response: {"status":"Ok","message":"Success","result":[{"t":ms,"o":,"h":,"l":,"c":,"v":,"oi":}]}

        IMPORTANT:
          - Timestamps are in MILLISECONDS (epoch * 1000)
          - Resolution: "1" = 1 min, "3" = 3 min, "5" = 5 min, "15" = 15 min,
            "30" = 30 min, "60" = 60 min, "1D" = daily
          - Authorization header is just Bearer <session_token> (NOT "{user_id} {session_token}")
        """
        if not self._session_token:
            return None
        try:
            exchange = str(payload.get("exchange", payload.get("exch", "NSE"))).upper()

            # Official URL per docs (POST to a3.aliceblueonline.com, NOT ant.aliceblueonline.com)
            url = f"{self._AB_REST_BASE}/od/ChartAPIService/api/chart/history"
            # Docs: Authorization: Bearer <userSession> — session token only, no uid prefix
            headers = {
                "Authorization": f"Bearer {self._session_token}",
                "Content-Type": "application/json",
            }
            params = dict(payload)

            # ── Translate from Zebu-style params to Alice Blue v2 params ──
            # token and exchange stay the same
            # from/to must be in MILLISECONDS
            raw_from = params.pop("st", params.pop("from", ""))
            raw_to = params.pop("et", params.pop("to", ""))
            # Detect if already in ms (> year 2001 in ms = > 1e12) or still in seconds
            def _to_ms(val: str) -> str:
                try:
                    v = int(float(str(val)))
                    return str(v * 1000) if v < 10_000_000_000 else str(v)
                except Exception:
                    return str(val)

            raw_intrv = params.pop("intrv", params.pop("resolution", "5"))
            # Map resolution to Alice Blue format:
            # 1m→"1", 3m→"3", 5m→"5", 15m→"15", 30m→"30", 60m→"60", daily→"D"
            _DAILY_KEYS = ("D", "1d", "day", "daily", "1D")
            resolution = "D" if str(raw_intrv).upper() in {k.upper() for k in _DAILY_KEYS} else str(raw_intrv)

            body = {
                "token": str(params.get("token", "")),
                "resolution": resolution,
                "from": _to_ms(raw_from),
                "to": _to_ms(raw_to),
                "exchange": exchange,
            }
            # Remove empty fields
            body = {k: v for k, v in body.items() if v}

            logger.debug(
                f"AliceBlue chart/history POST {url} body={body}"
            )
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code != 200:
                    logger.warning(
                        f"AliceBlue chart/history HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    return None
                data = resp.json()
                # Docs response: {"status":"Ok","message":"Success","result":[...]}
                if isinstance(data, dict):
                    result = data.get("result") or data.get("data") or []
                    status = str(data.get("status") or data.get("stat") or "").upper()
                    message = str(data.get("message") or data.get("emsg") or "")
                    if status not in ("OK", "SUCCESS", "") and not result:
                        logger.warning(
                            f"AliceBlue chart/history non-OK: {message or data}"
                        )
                        return None
                    return result if isinstance(result, list) else []
                if isinstance(data, list):
                    return data
                return None
        except Exception as e:
            logger.debug(f"AliceBlue chart history failed: {e}")
        return None

    # ── Helpers for Resampling and Parsing ──────────────────────────

    def _parse_candle(self, c: dict) -> Optional[dict]:
        if not isinstance(c, dict):
            return None
        try:
            ts_raw = c.get("Time") or c.get("time") or c.get("t") or c.get("ssboe")
            ts_sec = 0
            if isinstance(ts_raw, str):
                ts_raw = ts_raw.strip()
                try:
                    dt = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
                    ist_tz = timezone(timedelta(hours=5, minutes=30))
                    dt = dt.replace(tzinfo=ist_tz)
                    ts_sec = int(dt.timestamp())
                except ValueError:
                    try:
                        dt = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M")
                        ist_tz = timezone(timedelta(hours=5, minutes=30))
                        dt = dt.replace(tzinfo=ist_tz)
                        ts_sec = int(dt.timestamp())
                    except ValueError:
                        try:
                            ts_sec = int(float(ts_raw))
                            if ts_sec > 1_000_000_000_000:
                                ts_sec //= 1000
                        except ValueError:
                            pass
            elif ts_raw:
                ts_sec = int(float(ts_raw))
                if ts_sec > 1_000_000_000_000:
                    ts_sec //= 1000

            if ts_sec == 0:
                return None

            return {
                "time": ts_sec,
                "open": float(c.get("Open") or c.get("open") or c.get("o") or c.get("into") or 0),
                "high": float(c.get("High") or c.get("high") or c.get("h") or c.get("inth") or 0),
                "low": float(c.get("Low") or c.get("low") or c.get("l") or c.get("intl") or 0),
                "close": float(c.get("Close") or c.get("close") or c.get("c") or c.get("intc") or 0),
                "volume": int(float(c.get("Volume") or c.get("volume") or c.get("v") or c.get("intv") or 0)),
            }
        except (TypeError, ValueError, KeyError):
            return None

    @staticmethod
    def _parse_interval_minutes(interval: str) -> int:
        interval = interval.lower().strip()
        if interval.endswith("m"):
            try:
                return int(interval[:-1])
            except ValueError:
                return 1
        elif interval.endswith("h"):
            try:
                return int(interval[:-1]) * 60
            except ValueError:
                return 60
        elif interval.endswith("d"):
            try:
                return int(interval[:-1]) * 1440
            except ValueError:
                return 1
        else:
            try:
                return int(interval)
            except ValueError:
                return 1

    @staticmethod
    def _resample_candles(candles: list[dict], interval_minutes: int) -> list[dict]:
        if not candles or interval_minutes <= 1:
            return candles
        
        bucket_sec = interval_minutes * 60
        buckets = {}
        
        for c in candles:
            t = c.get("time")
            if not t:
                continue
            bucket_t = (t // bucket_sec) * bucket_sec
            
            if bucket_t not in buckets:
                buckets[bucket_t] = {
                    "time": bucket_t,
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c.get("volume", 0),
                }
            else:
                b = buckets[bucket_t]
                b["high"] = max(b["high"], c["high"])
                b["low"] = min(b["low"], c["low"])
                b["close"] = c["close"]
                b["volume"] += c.get("volume", 0)
                
        return sorted(buckets.values(), key=lambda x: x["time"])

    # ── Historical data ────────────────────────────────────────────

    async def _fetch_tp_series(
        self, exch: str, token: str, st_epoch: int, et_epoch: int, interval: str
    ) -> list[dict]:
        """
        Intraday candle data via Alice Blue v2 chart/history API.

        Per docs: POST https://a3.aliceblueonline.com/open-api/od/ChartAPIService/api/chart/history
        Timestamps in milliseconds. Response: {status, message, result:[{t,o,h,l,c,v,oi}]}
        """
        if not self._session_token:
            return []
        payload = {
            "token": token,
            "exchange": exch,
            # st_epoch/et_epoch arrive as seconds — _alice_chart_history converts to ms
            "st": str(st_epoch),
            "et": str(et_epoch),
            "intrv": interval,
        }
        try:
            candles_raw = await self._alice_chart_history("/TPSeries", payload)
            if not candles_raw:
                return []
            result = []
            for c in candles_raw:
                parsed = self._parse_candle(c)
                if parsed:
                    result.append(parsed)
            result.sort(key=lambda x: x["time"])
            return result
        except Exception as e:
            logger.warning(f"AliceBlue _fetch_tp_series failed: {e}")
            return []

    async def _fetch_eod_data(
        self, exch: str, token: str, st_epoch: int, et_epoch: int
    ) -> list[dict]:
        """
        EOD/daily candle data via Alice Blue v2 chart/history API.

        Per docs: resolution = "D" for daily data.
        Timestamps in milliseconds. Response: {status, message, result:[{t,o,h,l,c,v,oi}]}
        """
        if not self._session_token:
            return []
        payload = {
            "token": token,
            "exchange": exch,
            "st": str(st_epoch),
            "et": str(et_epoch),
            "intrv": "D",
        }
        try:
            data = await self._alice_chart_history("/EODChartData", payload)
            if not data:
                return []
            candles_raw = data if isinstance(data, list) else (data.get("values") or [])
            result = []
            for c in candles_raw:
                parsed = self._parse_candle(c)
                if parsed:
                    result.append(parsed)
            result.sort(key=lambda x: x["time"])
            return result
        except Exception as e:
            logger.warning(f"AliceBlue _fetch_eod_data failed: {e}")
            return []

    async def get_historical_data(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list:
        """Alice Blue v2 REST historical data via chart/history API.

        Uses the correct v2 endpoint (a3.aliceblueonline.com) with POST method,
        millisecond timestamps, and proper resolution codes.
        """
        symbol = self._fmt(symbol)
        mapping = canonical_to_zebu(symbol)
        if not mapping:
            mapping = await self._resolve_symbol(symbol)
        if not mapping:
            return []

        _PERIOD_DAYS = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365,
        }
        days = _PERIOD_DAYS.get(period, 30)
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        st_epoch = int(start_time.timestamp())
        et_epoch = int(end_time.timestamp())

        exch = mapping.get("exchange", "NSE")
        token = str(mapping.get("token", "")).strip()
        tsym = str(mapping.get("trading_symbol", symbol)).strip()

        is_intraday = interval.lower().endswith(("m", "h")) or interval.isdigit()

        if is_intraday:
            # Alice Blue API only supports "1" resolution for intraday.
            # We fetch 1-minute data and resample it to the target interval.
            raw_candles = await self._fetch_tp_series(exch, token, st_epoch, et_epoch, "1")
            target_minutes = self._parse_interval_minutes(interval)
            if target_minutes > 1:
                return self._resample_candles(raw_candles, target_minutes)
            return raw_candles
        else:
            # Daily / weekly / monthly — use "D" resolution
            return await self._fetch_eod_data(exch, token, st_epoch, et_epoch)

    # ── Market hours detection ────────────────────────────────────────

    def _is_market_open(self, exchange: str = "NSE") -> bool:
        """
        Return True if the exchange is currently open for trading (IST).

        NSE/BSE: Mon–Fri 09:15–15:30 IST
        MCX    : Mon–Fri 09:00–23:30 IST
        NFO    : same as NSE

        Note: Does NOT account for exchange-declared holidays — use this as
        a quick guard to decide whether to use live WS or historical REST.
        """
        now_ist = datetime.now(self._MARKET_TZ)
        weekday = now_ist.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        if weekday >= 5:  # Saturday or Sunday
            return False
        h, m = now_ist.hour, now_ist.minute
        exch_upper = (exchange or "NSE").upper()
        if exch_upper == "MCX":
            # MCX commodity: 09:00 to 23:30 IST
            return (h, m) >= (9, 0) and (h, m) < (23, 30)
        else:
            # NSE/BSE/NFO: 09:15 to 15:30 IST
            return (h, m) >= (9, 15) and (h, m) < (15, 30)

    # ── Quotes ───────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Optional[dict]:
        """
        Get a quote for a symbol.

        When market is OPEN: returns live data from the WS tick cache.
        When market is CLOSED / holiday: falls back to the Alice Blue v2
        historical API to fetch the last known close price.
        """
        symbol = self._fmt(symbol)
        # 1. Check WS tick cache (always preferred when fresh)
        if symbol in self._price_cache:
            cached = self._price_cache[symbol]
            if not self._is_quote_stale(cached):
                return cached

        # 2. If market is open, subscribe and let ticks come via WS
        mapping = canonical_to_zebu(symbol)
        if mapping and symbol not in self._subscribed_symbols:
            asyncio.create_task(self.subscribe([symbol]))

        # 3. If market is CLOSED, use historical API for last-close data
        if not self._is_market_open(mapping.get("exchange", "NSE") if mapping else "NSE"):
            # Return stale cache if available (better than nothing)
            if symbol in self._price_cache:
                return self._price_cache[symbol]
            # Try to fetch last bar from historical API
            try:
                candles = await self._fetch_eod_data(
                    mapping.get("exchange", "NSE") if mapping else "NSE",
                    symbol.split(".")[0] if "." in symbol else symbol,
                    int((datetime.now() - timedelta(days=7)).timestamp()),
                    int(datetime.now().timestamp()),
                )
                if candles:
                    last = candles[-1]
                    quote = {
                        "symbol": symbol,
                        "name": symbol,
                        "price": last["close"],
                        "change": None,
                        "change_percent": None,
                        "open": last["open"],
                        "high": last["high"],
                        "low": last["low"],
                        "close": last["close"],
                        "prev_close": last["close"],
                        "volume": last["volume"],
                        "lp": last["close"],
                        "ltp": last["close"],
                        "stat": "Ok",
                        "source": "historical",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    self._price_cache[symbol] = quote
                    return quote
            except Exception as e:
                logger.debug(f"AliceBlue historical fallback for {symbol}: {e}")
        return None

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        result = {}
        for s in symbols:
            q = await self.get_quote(s)
            if q:
                result[self._fmt(s)] = q
        return result

    # ── Symbol resolution (reuses Zebu/NSE token mapping) ───────────

    async def _resolve_symbol(self, canonical: str) -> Optional[dict]:
        """
        Resolve canonical symbol → token/exchange mapping for Alice Blue.

        Alice Blue does not have a NorenOMS-style SearchScrip REST endpoint.
        Instead we resolve via:
          1. Alice Blue contract master CDN (v2api.aliceblueonline.com)
          2. Subscribe and infer token from the first tick

        The resolved mapping is registered in the shared _ZEBU_SYMBOL_MAP so
        subsequent WS subscriptions and tick reverse-lookups work correctly.
        """
        canonical_upper = str(canonical or "").strip().upper()
        base = canonical_upper.split(".")[0].upper()

        if not base:
            return None

        # Alice Blue contract master CDN — covers all NSE/BSE equities and indices
        _ALICE_CDN_EXCHANGES = {
            "NSE": "NSE",
            "BSE": "BSE",
            "NFO": "NFO",
            "MCX": "MCX",
        }

        # Detect derivative contracts
        is_derivative = bool(
            re.search(r"\d", canonical_upper)
            and re.search(r"(FUT|CE|PE)$", canonical_upper)
        )

        if is_derivative:
            if canonical_upper.endswith(("CE", "PE", "FUT")):
                exchange_candidates = ["NFO"]
                if "SENSEX" in canonical_upper or "BANKEX" in canonical_upper:
                    exchange_candidates = ["BFO"]
                search_key = canonical_upper
            else:
                return None
        elif is_ncdex_symbol(canonical_upper):
            exchange_candidates = ["NCDEX"]
            search_key = base
        elif is_mcx_symbol(canonical_upper):
            exchange_candidates = ["MCX"]
            search_key = base
        elif canonical_upper.endswith(".BO"):
            exchange_candidates = ["BSE"]
            search_key = base
        elif canonical_upper.endswith(".NS"):
            exchange_candidates = ["NSE"]
            search_key = base
        else:
            exchange_candidates = ["NSE", "BSE"]
            search_key = base

        # Try Alice Blue contract master for each candidate exchange
        if self._api_url:
            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    for exchange in exchange_candidates:
                        # Alice Blue contract master CDN
                        cdn_url = (
                            f"https://v2api.aliceblueonline.com/restpy/"
                            f"static/contract_master/V2/{exchange}"
                        )
                        try:
                            cdn_resp = await client.get(
                                cdn_url,
                                headers={},
                                timeout=10.0,
                            )
                            if cdn_resp.status_code == 200:
                                contracts = cdn_resp.json()
                                contract_list = None
                                if isinstance(contracts, dict):
                                    # V2 CDN returns a dict mapping the exchange name to the list
                                    contract_list = (
                                        contracts.get(exchange)
                                        or contracts.get(exchange.upper())
                                        or contracts.get(exchange.lower())
                                    )
                                    if not contract_list and len(contracts) == 1:
                                        contract_list = list(contracts.values())[0]
                                elif isinstance(contracts, list):
                                    contract_list = contracts

                                if isinstance(contract_list, list):
                                    for item in contract_list:
                                        tsym = str(
                                            item.get("trading_symbol")
                                            or item.get("Symbol")
                                            or item.get("symbol")
                                            or ""
                                        ).strip().upper()
                                        token = str(
                                            item.get("token")
                                            or item.get("Token")
                                            or ""
                                        ).strip()
                                        if not token or not tsym:
                                            continue
                                        # Match by trading symbol
                                        is_match = (
                                            tsym == search_key
                                            or tsym == f"{search_key}-EQ"
                                            or tsym == f"{search_key} EQ"
                                        )
                                        if not is_match and not is_derivative:
                                            is_match = tsym.startswith(search_key)
                                        if is_match:
                                            mapping = {
                                                "symbol": base,
                                                "canonical": canonical_upper,
                                                "trading_symbol": tsym,
                                                "token": token,
                                                "exchange": exchange,
                                            }
                                            load_zebu_contracts([mapping])
                                            logger.info(
                                                f"AliceBlue CDN resolved {canonical_upper} → "
                                                f"token={token} ({exchange}:{tsym})"
                                            )
                                            return canonical_to_zebu(canonical_upper)
                        except Exception as cdn_e:
                            logger.debug(
                                f"AliceBlue CDN fetch failed for {exchange}: {cdn_e}"
                            )
            except Exception as e:
                logger.warning(f"AliceBlue symbol resolve failed for {canonical}: {e}")

        return None

    # ── Health ───────────────────────────────────────────────────────

    async def health(self) -> ProviderHealth:
        uptime = (time.time() - self._started_at) if self._started_at else 0
        last_tick = (
            datetime.utcfromtimestamp(self._last_tick_at).isoformat()
            if self._last_tick_at else None
        )
        return ProviderHealth(
            status=self._status,
            provider_name="aliceblue",
            subscribed_symbols=len(self._subscribed_symbols),
            last_tick_at=last_tick,
            uptime_seconds=uptime,
            reconnect_count=self._reconnect_count,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _fmt(symbol: str) -> str:
        clean = str(symbol or "").strip().upper()
        if not clean:
            return clean
        if clean.startswith("^") or clean.endswith((".NS", ".BO", "=F")):
            return clean
        if is_mcx_symbol(clean):
            return clean
        # F&O contracts contain digits + end in FUT/CE/PE — preserve as-is
        if re.search(r"\d", clean) and re.search(r"(FUT|CE|PE)$", clean):
            return clean
        return f"{clean}.NS"

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _is_quote_stale(cls, quote: dict) -> bool:
        raw_ts = quote.get("timestamp")
        if not raw_ts:
            return True
        try:
            if isinstance(raw_ts, (int, float)):
                quote_epoch = float(raw_ts)
            else:
                raw_str = str(raw_ts).strip()
                if raw_str.endswith("Z"):
                    raw_str = raw_str[:-1] + "+00:00"
                quote_epoch = datetime.fromisoformat(raw_str).timestamp()
            return (time.time() - quote_epoch) > cls.QUOTE_STALE_SECONDS
        except Exception:
            return True

    @staticmethod
    def _build_scrip_list(symbols: set[str]) -> str:
        """Build 'NSE|2885#NFO|12345#...' touchline subscription string."""
        parts = []
        for sym in symbols:
            mapping = canonical_to_zebu(sym)
            if mapping:
                exch = mapping.get("exchange", "NSE")
                tok = mapping.get("token", "")
                if tok:
                    parts.append(f"{exch}|{tok}")
        return "#".join(parts)
