"""
ZerodhaProvider — Real-time market data via Kite Connect WebSocket.

Protocol: Binary (Kite WebSocket v3 — not JSON like NorenOMS)

Message format:
    - First 2 bytes: number of packets in this frame
    - For each packet:
        - 2 bytes: packet length
        - 4 bytes: instrument_token (uint32 big-endian)
        - Variable: price data depending on mode

Modes and packet sizes:
    - LTP   : 8 bytes  (token + last_price)
    - Quote : 44 bytes (LTP + OHLCV + buy/sell qty)
    - Full  : 184 bytes (Quote + depth + OI + timestamps)

Prices: stored as int paise (divide by 100 to get INR)

Symbol mapping:
    - Zerodha uses its own instrument_token per scrip (not NSE token IDs)
    - Instruments downloaded from https://api.kite.trade/instruments
    - Mapped: canonical symbol → instrument_token
"""

import asyncio
import json
import logging
import struct
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from providers.base import MarketProvider, ProviderHealth, ProviderStatus
from providers.symbol_mapper import mirror_canonicals_for_quote

logger = logging.getLogger(__name__)

# Packet sizes per mode
_PACKET_LTP = 8
_PACKET_QUOTE = 44
_PACKET_FULL = 184

# NSE exchange code in Zerodha instrument_token (top 3 bits)
_EXCHANGE_MAP = {
    1: "NSE",
    2: "NFO",
    3: "CDS",
    4: "BSE",
    5: "BFO",
    6: "BCD",
    7: "MCX",
    8: "MCXSX",
    9: "INDICES",
}


def _parse_price(b: bytes, offset: int) -> float:
    """Read big-endian uint32 from bytes at offset and convert paise → INR."""
    val = struct.unpack_from(">I", b, offset)[0]
    return round(val / 100.0, 2)


def _parse_signed_price(b: bytes, offset: int) -> float:
    """Read big-endian int32 (for negative values) and convert paise → INR."""
    val = struct.unpack_from(">i", b, offset)[0]
    return round(val / 100.0, 2)


def _parse_uint32(b: bytes, offset: int) -> int:
    return struct.unpack_from(">I", b, offset)[0]


def _parse_int64(b: bytes, offset: int) -> int:
    return struct.unpack_from(">q", b, offset)[0]


def _parse_kite_packet(packet: bytes) -> Optional[dict]:
    """
    Parse a single Kite binary packet into a quote dict.

    Packet layout (Full mode, 184 bytes):
        [0-3]   instrument_token (uint32)
        [4-7]   last_price (uint32, paise)
        [8-11]  last_traded_quantity (uint32)
        [12-15] average_traded_price (uint32, paise)
        [16-19] volume_traded (uint32)
        [20-23] total_buy_quantity (uint32)
        [24-27] total_sell_quantity (uint32)
        [28-31] ohlc.open (uint32, paise)
        [32-35] ohlc.high (uint32, paise)
        [36-39] ohlc.low (uint32, paise)
        [40-43] ohlc.close (uint32, paise)
        [44-51] last_traded_time (int64, epoch seconds)
        [52-55] oi (uint32)
        [56-59] oi_day_high (uint32)
        [60-63] oi_day_low (uint32)
        [64-71] exchange_timestamp (int64, epoch seconds)
        [72-131] depth_buy (5 × 12 bytes each)
        [132-191] depth_sell (5 × 12 bytes each)
    """
    pkt_len = len(packet)
    if pkt_len < _PACKET_LTP:
        return None

    instrument_token = _parse_uint32(packet, 0)
    last_price = _parse_price(packet, 4)
    if last_price <= 0:
        return None

    # Determine exchange from token's top bits
    segment = instrument_token & 0xFF
    exchange = _EXCHANGE_MAP.get(segment, "NSE")

    result = {
        "instrument_token": instrument_token,
        "price": last_price,
        "exchange": exchange,
        "volume": 0,
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "close": 0.0,
        "prev_close": 0.0,
        "oi": 0,
        "bid_price": 0.0,
        "ask_price": 0.0,
        "bid_qty": 0,
        "ask_qty": 0,
        "change": 0.0,
        "change_percent": 0.0,
    }

    if pkt_len >= _PACKET_QUOTE:
        result["volume"] = _parse_uint32(packet, 16)
        result["bid_qty"] = _parse_uint32(packet, 20)
        result["ask_qty"] = _parse_uint32(packet, 24)
        result["open"] = _parse_price(packet, 28)
        result["high"] = _parse_price(packet, 32)
        result["low"] = _parse_price(packet, 36)
        prev_close = _parse_price(packet, 40)
        result["close"] = prev_close
        result["prev_close"] = prev_close
        if prev_close > 0:
            result["change"] = round(last_price - prev_close, 2)
            result["change_percent"] = round((last_price - prev_close) / prev_close * 100, 2)

    if pkt_len >= _PACKET_FULL:
        result["oi"] = _parse_uint32(packet, 52)
        # Depth: 5 buy + 5 sell, each 12 bytes: [qty(4), price(4), orders(2), pad(2)]
        for i in range(5):
            off = 72 + i * 12
            if off + 12 <= pkt_len:
                result["bid_qty"] = _parse_uint32(packet, off)
                result["bid_price"] = _parse_price(packet, off + 4)
                break  # take best bid only
        for i in range(5):
            off = 132 + i * 12
            if off + 12 <= pkt_len:
                result["ask_qty"] = _parse_uint32(packet, off)
                result["ask_price"] = _parse_price(packet, off + 4)
                break  # take best ask only

    return result


def _parse_kite_binary(data: bytes) -> list[dict]:
    """Parse a Kite binary WebSocket frame into a list of parsed packets."""
    if len(data) < 2:
        return []

    num_packets = struct.unpack_from(">H", data, 0)[0]
    packets = []
    offset = 2

    for _ in range(num_packets):
        if offset + 2 > len(data):
            break
        pkt_len = struct.unpack_from(">H", data, offset)[0]
        offset += 2
        if offset + pkt_len > len(data):
            break
        packet_bytes = data[offset: offset + pkt_len]
        offset += pkt_len
        parsed = _parse_kite_packet(packet_bytes)
        if parsed:
            packets.append(parsed)

    return packets


class ZerodhaProvider(MarketProvider):
    """
    Zerodha Kite Connect WebSocket provider.

    Auth: api_key + access_token (obtained via OAuth)
    WS URL: wss://ws.kite.trade?api_key=X&access_token=Y
    Protocol: Binary (Kite v3)
    """

    RECONNECT_BASE_DELAY = 1.0
    RECONNECT_MAX_DELAY = 60.0
    RECONNECT_BACKOFF_FACTOR = 2.0
    MAX_RECONNECT_ATTEMPTS = 50
    HEARTBEAT_INTERVAL = 30.0
    QUOTE_STALE_SECONDS = 20.0
    STREAM_STALE_SECONDS = 25.0

    # Kite subscribe mode — "full" gives OHLCV + depth + OI
    SUBSCRIBE_MODE = "full"

    def __init__(
        self,
        ws_url: str,
        api_key: str,
        access_token: str,
        user_id: str = "",
        api_url: str = "https://api.kite.trade",
        redis_client=None,
    ):
        self._ws_url = ws_url
        self._api_key = api_key
        self._access_token = access_token
        self._user_id = user_id
        self._api_url = api_url.rstrip("/")
        self._redis = redis_client

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._status = ProviderStatus.DISCONNECTED
        self._started_at: Optional[float] = None
        self._last_tick_at: Optional[float] = None
        self._reconnect_count = 0
        self._consecutive_failures = 0

        # symbol → instrument_token mapping (populated on demand)
        self._symbol_to_token: dict[str, int] = {}
        self._token_to_symbol: dict[int, str] = {}
        self._instruments_loaded = False

        self._subscribed_symbols: set[str] = set()
        self._subscribed_tokens: set[int] = set()
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

    def _build_ws_url(self) -> str:
        return f"{self._ws_url}?api_key={self._api_key}&access_token={self._access_token}"

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._started_at = time.time()
        logger.info(
            f"ZerodhaProvider.start() | user={str(self._user_id)[:8] if self._user_id else 'NONE'} "
            f"| has_token={bool(self._access_token)}"
        )
        if not self._access_token or not self._api_key:
            logger.warning("ZerodhaProvider started without credentials")
            self._status = ProviderStatus.DISCONNECTED
            return
        # Pre-load instrument mapping
        asyncio.create_task(self._load_instruments())
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
        logger.info("ZerodhaProvider stopped")

    async def update_credentials(self, api_key: str, access_token: str) -> None:
        async with self._credential_lock:
            self._api_key = api_key
            self._access_token = access_token
            if not access_token:
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

    # ── Instrument mapping ───────────────────────────────────────────

    async def _load_instruments(self) -> None:
        """Download NSE instruments CSV from Kite and build symbol→token map."""
        if self._instruments_loaded:
            return
        try:
            url = f"{self._api_url}/instruments/NSE"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self._api_key}:{self._access_token}",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Zerodha instruments fetch failed: HTTP {resp.status_code}")
                    return
                text = resp.text
                lines = text.strip().split("\n")
                if not lines:
                    return
                header = [h.strip() for h in lines[0].split(",")]
                token_idx = header.index("instrument_token") if "instrument_token" in header else -1
                symbol_idx = header.index("tradingsymbol") if "tradingsymbol" in header else -1
                exchange_idx = header.index("exchange") if "exchange" in header else -1
                if token_idx < 0 or symbol_idx < 0:
                    logger.warning("Zerodha instruments CSV missing expected columns")
                    return
                for line in lines[1:]:
                    cols = line.split(",")
                    if len(cols) <= max(token_idx, symbol_idx):
                        continue
                    try:
                        token = int(cols[token_idx].strip())
                        tsym = cols[symbol_idx].strip().upper()
                        exchange = cols[exchange_idx].strip().upper() if exchange_idx >= 0 else "NSE"
                        canonical = f"{tsym}.NS" if exchange == "NSE" else f"{tsym}.BO"
                        self._symbol_to_token[canonical] = token
                        self._symbol_to_token[tsym] = token
                        self._token_to_symbol[token] = canonical
                    except (ValueError, IndexError):
                        continue
                self._instruments_loaded = True
                logger.info(f"Zerodha instruments loaded: {len(self._symbol_to_token)} symbols")

                # Also load NFO (futures/options)
                asyncio.create_task(self._load_instruments_exchange("NFO"))
                asyncio.create_task(self._load_instruments_exchange("MCX"))
        except Exception as e:
            logger.warning(f"Zerodha instrument load failed: {e}")

    async def _load_instruments_exchange(self, exchange: str) -> None:
        try:
            url = f"{self._api_url}/instruments/{exchange}"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self._api_key}:{self._access_token}",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return
                lines = resp.text.strip().split("\n")
                if not lines:
                    return
                header = [h.strip() for h in lines[0].split(",")]
                token_idx = header.index("instrument_token") if "instrument_token" in header else -1
                symbol_idx = header.index("tradingsymbol") if "tradingsymbol" in header else -1
                if token_idx < 0 or symbol_idx < 0:
                    return
                count = 0
                for line in lines[1:]:
                    cols = line.split(",")
                    if len(cols) <= max(token_idx, symbol_idx):
                        continue
                    try:
                        token = int(cols[token_idx].strip())
                        tsym = cols[symbol_idx].strip().upper()
                        self._symbol_to_token[tsym] = token
                        self._token_to_symbol[token] = tsym
                        count += 1
                    except (ValueError, IndexError):
                        continue
                logger.info(f"Zerodha {exchange} instruments loaded: {count}")
        except Exception as e:
            logger.debug(f"Zerodha {exchange} instruments load failed: {e}")

    def _get_token(self, symbol: str) -> Optional[int]:
        """Map canonical symbol to Zerodha instrument_token."""
        clean = str(symbol or "").strip().upper()
        return (
            self._symbol_to_token.get(clean)
            or self._symbol_to_token.get(clean.replace(".NS", ""))
            or self._symbol_to_token.get(clean.replace(".BO", ""))
        )

    # ── Connection ───────────────────────────────────────────────────

    async def _connect(self) -> None:
        self._status = ProviderStatus.CONNECTING
        try:
            url = self._build_ws_url()
            self._ws = await websockets.connect(
                url,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
                max_size=2**22,  # Kite can send large depth frames
            )
            self._status = ProviderStatus.CONNECTED
            self._consecutive_failures = 0
            logger.info(
                f"[ZERODHA WS CONNECTED] user={str(self._user_id)[:8] if self._user_id else '?'}... "
                f"subscribed={len(self._subscribed_tokens)}"
            )

            # Re-subscribe previously active tokens
            if self._subscribed_tokens:
                await self._send_subscribe(self._subscribed_tokens)
                await self._send_mode(self._subscribed_tokens)

            # Subscribe pending symbols
            if self._pending_subscribe:
                await self._subscribe_symbols(self._pending_subscribe)
                self._pending_subscribe.clear()

            self._recv_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except Exception as e:
            logger.error(f"ZerodhaProvider connection failed: {e}")
            self._status = ProviderStatus.ERROR
            if self._running:
                asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        if not self._running:
            return
        self._consecutive_failures += 1
        if self._consecutive_failures > self.MAX_RECONNECT_ATTEMPTS:
            logger.error("Zerodha: max reconnect attempts reached")
            self._status = ProviderStatus.ERROR
            return
        delay = min(
            self.RECONNECT_BASE_DELAY * (self.RECONNECT_BACKOFF_FACTOR ** (self._consecutive_failures - 1)),
            self.RECONNECT_MAX_DELAY,
        )
        self._status = ProviderStatus.RECONNECTING
        self._reconnect_count += 1
        logger.warning(f"Zerodha reconnecting in {delay:.1f}s (attempt {self._consecutive_failures})")
        await asyncio.sleep(delay)
        if self._running:
            await self._connect()

    # ── Receive loop ─────────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        try:
            async for message in self._ws:
                if not self._running:
                    break
                try:
                    if isinstance(message, bytes):
                        packets = _parse_kite_binary(message)
                        for packet in packets:
                            await self._handle_packet(packet)
                    else:
                        # JSON control messages from Kite (error, reconnect, order update)
                        data = json.loads(message)
                        msg_type = data.get("type", "")
                        if msg_type == "error":
                            logger.error(f"Kite WS error: {data.get('data')}")
                        elif msg_type == "order":
                            pass  # Order updates — not used for market data
                except Exception as e:
                    logger.error(f"Zerodha tick error: {e}", exc_info=True)
        except (ConnectionClosed, ConnectionClosedError) as e:
            logger.warning(f"Zerodha WS closed: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"Zerodha receive loop error: {e}", exc_info=True)
        if self._running:
            self._status = ProviderStatus.RECONNECTING
            asyncio.create_task(self._reconnect())

    async def _handle_packet(self, packet: dict) -> None:
        token = packet.get("instrument_token")
        if not token:
            return

        canonical = self._token_to_symbol.get(token)
        if not canonical:
            return

        self._last_tick_at = time.time()
        lp = packet.get("price", 0.0)
        if lp <= 0:
            return

        prev_cache = self._price_cache.get(canonical, {})
        prev_close = packet.get("prev_close") or prev_cache.get("prev_close", 0)

        quote = {
            "symbol": canonical,
            "name": canonical.replace(".NS", "").replace(".BO", ""),
            "price": lp,
            "change": packet.get("change") or (round(lp - prev_close, 2) if prev_close else 0.0),
            "change_percent": packet.get("change_percent") or (
                round((lp - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            ),
            "open": packet.get("open", prev_cache.get("open", 0.0)),
            "high": packet.get("high", prev_cache.get("high", 0.0)),
            "low": packet.get("low", prev_cache.get("low", 0.0)),
            "close": prev_close,
            "prev_close": prev_close,
            "volume": packet.get("volume", prev_cache.get("volume", 0)),
            "bid_price": packet.get("bid_price", prev_cache.get("bid_price", 0.0)),
            "ask_price": packet.get("ask_price", prev_cache.get("ask_price", 0.0)),
            "bid_qty": packet.get("bid_qty", prev_cache.get("bid_qty", 0)),
            "ask_qty": packet.get("ask_qty", prev_cache.get("ask_qty", 0)),
            "oi": packet.get("oi", prev_cache.get("oi", 0)),
            "market_cap": 0,
            "exchange": packet.get("exchange", "NSE"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "live_ws",
        }

        self._price_cache[canonical] = quote
        _changed = prev_cache.get("price") != lp or prev_cache.get("volume") != quote["volume"]

        try:
            from market.quote_coordinator import quote_coordinator
            mirrors = mirror_canonicals_for_quote(canonical)
            await quote_coordinator.ingest_equity_quote(
                canonical, quote, source="live_ws", changed=_changed,
                mirror_symbols=mirrors, write_redis=bool(self._redis), emit_event=True,
            )
        except Exception as e:
            logger.warning(f"Zerodha coordinator ingest failed for {canonical}: {e}")

    # ── Heartbeat ────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Kite WS keeps alive with text ping messages."""
        try:
            while self._running and self._ws and not self._ws_is_closed():
                try:
                    await self._ws.send("ping")
                except Exception as e:
                    logger.warning(f"Zerodha heartbeat failed: {e}")
                    break
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            return

    # ── Subscriptions ────────────────────────────────────────────────

    async def subscribe(self, symbols: list[str]) -> None:
        if not self._instruments_loaded:
            # Instruments still loading — queue and retry shortly
            self._pending_subscribe.update(symbols)
            asyncio.create_task(self._retry_pending_subscribe())
            return
        new_symbols = {s for s in symbols if s not in self._subscribed_symbols}
        if new_symbols:
            self._subscribed_symbols.update(new_symbols)
            if self._status == ProviderStatus.CONNECTED and self._ws:
                await self._subscribe_symbols(new_symbols)
            else:
                self._pending_subscribe.update(new_symbols)

    async def _retry_pending_subscribe(self) -> None:
        await asyncio.sleep(3.0)
        if self._pending_subscribe:
            symbols = set(self._pending_subscribe)
            self._pending_subscribe.clear()
            await self.subscribe(list(symbols))

    async def _subscribe_symbols(self, symbols: set[str]) -> None:
        tokens = set()
        for sym in symbols:
            token = self._get_token(sym)
            if token:
                tokens.add(token)
                self._token_to_symbol[token] = sym
            else:
                logger.debug(f"Zerodha: no instrument token for {sym}")
        if tokens:
            self._subscribed_tokens.update(tokens)
            await self._send_subscribe(tokens)
            await self._send_mode(tokens)

    async def unsubscribe(self, symbols: list[str]) -> None:
        remove_syms = {s for s in symbols if s in self._subscribed_symbols}
        remove_tokens = {self._get_token(s) for s in remove_syms if self._get_token(s)}
        self._subscribed_symbols -= remove_syms
        self._subscribed_tokens -= remove_tokens
        if remove_tokens and self._status == ProviderStatus.CONNECTED and self._ws:
            msg = json.dumps({"a": "unsubscribe", "v": list(remove_tokens)})
            try:
                await self._ws.send(msg)
            except Exception as e:
                logger.error(f"Zerodha unsubscribe failed: {e}")

    async def _send_subscribe(self, tokens: set[int]) -> None:
        msg = json.dumps({"a": "subscribe", "v": list(tokens)})
        try:
            await self._ws.send(msg)
            logger.info(f"Zerodha subscribed: {len(tokens)} tokens")
        except Exception as e:
            logger.error(f"Zerodha subscribe send failed: {e}")

    async def _send_mode(self, tokens: set[int]) -> None:
        msg = json.dumps({"a": "mode", "v": [self.SUBSCRIBE_MODE, list(tokens)]})
        try:
            await self._ws.send(msg)
        except Exception as e:
            logger.error(f"Zerodha mode send failed: {e}")

    def get_subscribed_symbols(self) -> set[str]:
        return self._subscribed_symbols.copy()

    # ── Quotes ───────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Optional[dict]:
        clean = str(symbol or "").strip().upper()
        if clean in self._price_cache:
            cached = self._price_cache[clean]
            if not self._is_quote_stale(cached):
                return cached
        # Auto-subscribe if not already
        if clean not in self._subscribed_symbols:
            asyncio.create_task(self.subscribe([clean]))
        # REST fallback
        return await self._rest_quote(clean)

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        result = {}
        for s in symbols:
            q = await self.get_quote(s)
            if q:
                result[s.strip().upper()] = q
        return result

    async def _rest_quote(self, symbol: str) -> Optional[dict]:
        """Fetch quote via Kite REST LTP endpoint."""
        token = self._get_token(symbol)
        if not token or not self._api_key or not self._access_token:
            return None
        # Determine exchange prefix
        exchange_code = token & 0xFF
        exchange = _EXCHANGE_MAP.get(exchange_code, "NSE")
        tsym = symbol.replace(".NS", "").replace(".BO", "")
        kite_sym = f"{exchange}:{tsym}"
        try:
            url = f"{self._api_url}/quote/ltp"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self._api_key}:{self._access_token}",
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, params={"i": kite_sym}, headers=headers)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                ltp_data = data.get("data", {}).get(kite_sym, {})
                lp = float(ltp_data.get("last_price", 0))
                if lp <= 0:
                    return None
                return {
                    "symbol": symbol,
                    "name": tsym,
                    "price": lp,
                    "change": 0.0,
                    "change_percent": 0.0,
                    "exchange": exchange,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "live_rest",
                }
        except Exception as e:
            logger.debug(f"Zerodha REST quote failed for {symbol}: {e}")
            return None

    async def get_historical_data(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list:
        """Fetch OHLCV candles via Kite historical data API."""
        token = self._get_token(symbol)
        if not token or not self._api_key or not self._access_token:
            return []

        _INTERVAL_MAP = {
            "1m": "minute", "3m": "3minute", "5m": "5minute", "10m": "10minute",
            "15m": "15minute", "30m": "30minute", "1h": "60minute", "2h": "2hour",
            "4h": "4hour", "1d": "day",
        }
        _PERIOD_DAYS = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730,
        }
        from datetime import timedelta
        days = _PERIOD_DAYS.get(period, 30)
        kite_interval = _INTERVAL_MAP.get(interval, "day")
        end_dt = datetime.now()
        from_dt = end_dt - timedelta(days=days)

        try:
            url = f"{self._api_url}/instruments/historical/{token}/{kite_interval}"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self._api_key}:{self._access_token}",
            }
            params = {
                "from": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "to": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            }
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                candles_raw = data.get("data", {}).get("candles", [])
                result = []
                for c in candles_raw:
                    if len(c) < 6:
                        continue
                    try:
                        # [timestamp_iso, open, high, low, close, volume, oi?]
                        dt = datetime.fromisoformat(str(c[0]).replace("Z", "+00:00"))
                        result.append({
                            "time": int(dt.timestamp()),
                            "open": float(c[1]),
                            "high": float(c[2]),
                            "low": float(c[3]),
                            "close": float(c[4]),
                            "volume": int(float(c[5])),
                        })
                    except (TypeError, ValueError):
                        continue
                result.sort(key=lambda x: x["time"])
                return result
        except Exception as e:
            logger.warning(f"Zerodha history failed for {symbol}: {e}")
            return []

    # ── Health ───────────────────────────────────────────────────────

    async def health(self) -> ProviderHealth:
        uptime = (time.time() - self._started_at) if self._started_at else 0
        last_tick = (
            datetime.utcfromtimestamp(self._last_tick_at).isoformat()
            if self._last_tick_at else None
        )
        return ProviderHealth(
            status=self._status,
            provider_name="zerodha",
            subscribed_symbols=len(self._subscribed_symbols),
            last_tick_at=last_tick,
            uptime_seconds=uptime,
            reconnect_count=self._reconnect_count,
        )

    @classmethod
    def _is_quote_stale(cls, quote: dict) -> bool:
        raw_ts = quote.get("timestamp")
        if not raw_ts:
            return True
        try:
            if isinstance(raw_ts, (int, float)):
                return (time.time() - float(raw_ts)) > cls.QUOTE_STALE_SECONDS
            raw_str = str(raw_ts).strip().replace("Z", "+00:00")
            return (time.time() - datetime.fromisoformat(raw_str).timestamp()) > cls.QUOTE_STALE_SECONDS
        except Exception:
            return True
