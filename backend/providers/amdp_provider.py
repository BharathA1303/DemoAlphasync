# amdp_provider.py - MarketProvider implementation for live AlphaSync Market Data Platform feed
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

import aiohttp
from providers.base import MarketProvider, ProviderHealth, ProviderStatus
from market_data.replay.market_publisher import market_publisher

logger = logging.getLogger(__name__)


class AMDPProvider(MarketProvider):
    """
    AMDPProvider connects to the live AlphaSync Market Data Platform (AMDP) API.
    It retrieves real-time ticks via WSS and forwards them to the publisher.
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str, redis_client=None):
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._redis = redis_client

        self._status = ProviderStatus.DISCONNECTED
        self._price_cache: Dict[str, dict] = {}
        self._subscribed_symbols: set[str] = set()
        self._running = False
        self._last_tick_at: Optional[float] = None
        self._started_at: Optional[float] = None

        self._session_id: Optional[str] = None
        self._access_token: Optional[str] = None
        self._ws_url: Optional[str] = None

        self._ws_client: Optional[aiohttp.ClientWebSocketResponse] = None
        self._http_client: Optional[aiohttp.ClientSession] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._reconnect_count = 0

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the provider and initiate background WS listener."""
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._status = ProviderStatus.CONNECTING
        self._reconnect_count = 0

        # Share price cache with MarketPublisher
        market_publisher.set_redis(self._redis)
        self._price_cache = market_publisher._price_cache

        # Create ClientSession
        self._http_client = aiohttp.ClientSession()

        # Start connection task
        self._ws_task = asyncio.create_task(self._connect_and_listen())
        logger.info("AMDPProvider started background connection loop")

    async def stop(self) -> None:
        """Stop the provider, cancel tasks and close connections."""
        self._running = False
        self._status = ProviderStatus.DISCONNECTED

        # Cancel WebSocket background loop
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        # Close WebSocket connection
        if self._ws_client:
            try:
                await self._ws_client.close()
            except Exception as e:
                logger.debug(f"AMDPProvider: Error closing WS client: {e}")
            self._ws_client = None

        # Close HTTP client
        if self._http_client:
            try:
                await self._http_client.close()
            except Exception as e:
                logger.debug(f"AMDPProvider: Error closing HTTP client: {e}")
            self._http_client = None

        # Clean up session on AMDP if session exists
        if self._session_id and self._access_token:
            try:
                # Use a temporary session to delete since self._http_client is closed
                async with aiohttp.ClientSession() as cleanup_session:
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    async with cleanup_session.delete(
                        f"{self._base_url}/sessions/{self._session_id}",
                        headers=headers,
                        timeout=5.0
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"AMDP Replay Session {self._session_id} destroyed successfully.")
            except Exception as e:
                logger.warning(f"AMDPProvider: Failed to destroy session {self._session_id}: {e}")

        self._session_id = None
        self._access_token = None
        logger.info("AMDPProvider stopped")

    # ── Broker Subscription APIs ────────────────────────────────────

    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to a list of symbols."""
        clean_symbols = [str(s).strip().upper() for s in symbols if s]
        self._subscribed_symbols.update(clean_symbols)

        if self._ws_client and not self._ws_client.closed:
            try:
                await self._ws_client.send_json({
                    "action": "subscribe",
                    "symbols": clean_symbols
                })
                logger.debug(f"AMDPProvider subscribed: {clean_symbols}")
            except Exception as e:
                logger.warning(f"AMDPProvider subscribe send failed: {e}")

    async def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from a list of symbols."""
        clean_symbols = [str(s).strip().upper() for s in symbols if s]
        for s in clean_symbols:
            self._subscribed_symbols.discard(s)

        if self._ws_client and not self._ws_client.closed:
            try:
                await self._ws_client.send_json({
                    "action": "unsubscribe",
                    "symbols": clean_symbols
                })
                logger.debug(f"AMDPProvider unsubscribed: {clean_symbols}")
            except Exception as e:
                logger.warning(f"AMDPProvider unsubscribe send failed: {e}")

    def get_subscribed_symbols(self) -> set:
        """Return the set of currently subscribed symbols."""
        return set(self._subscribed_symbols)

    async def get_quote(self, symbol: str) -> Optional[dict]:
        """Get latest quote from the shared cache."""
        return self._price_cache.get(str(symbol).strip().upper())

    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        """Get latest quotes for multiple symbols."""
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
        Fetch historical candles from AMDP REST API history endpoint.
        Falls back to local random walk if API fails or is unavailable.
        """
        logger.info(f"AMDPProvider: Fetching historical data for {symbol} ({interval})")
        if self._session_id and self._access_token:
            try:
                # AMDP History endpoint: GET /api/v1/history
                # Parameters: symbol, resolution (interval), from, to, sessionId
                # Let's map interval: 1m -> 1m, 5m -> 5m, 1d -> 1d
                import httpx
                headers = {"Authorization": f"Bearer {self._access_token}"}
                params = {
                    "symbol": symbol.upper().strip(),
                    "resolution": interval,
                    "sessionId": self._session_id,
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self._base_url}/history",
                        headers=headers,
                        params=params,
                        timeout=10.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        # Verify it returned list of candles
                        if isinstance(data, list):
                            return data
            except Exception as e:
                logger.warning(f"AMDPProvider: History API request failed: {e}. Falling back to Replay historical generation.")

        # Fallback to simulated candles generator
        from providers.replay_provider import ReplayProvider
        temp_provider = ReplayProvider(self._redis)
        temp_provider._started_at = self._started_at
        return await temp_provider.get_historical_data(symbol, period, interval)

    async def health(self) -> ProviderHealth:
        """Get provider health status."""
        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        return ProviderHealth(
            status=self._status,
            provider_name="AMDPProvider",
            subscribed_symbols=len(self._subscribed_symbols),
            last_tick_at=datetime.fromtimestamp(self._last_tick_at, timezone.utc).isoformat() if self._last_tick_at else None,
            uptime_seconds=uptime,
            reconnect_count=self._reconnect_count,
            error=None if self._status == ProviderStatus.CONNECTED else "WebSocket disconnected",
        )

    # ── Connection & Ingestion Engine ───────────────────────────────

    async def _authenticate_and_create_session(self) -> None:
        """Authenticate with AMDP and prepare a replay session."""
        logger.info(f"AMDPProvider: Authenticating with {self._base_url}")
        
        # 1. Exchange credentials for JWT access token
        async with self._http_client.post(
            f"{self._base_url}/auth/token",
            json={"api_key": self._api_key, "secret": self._api_secret},
            timeout=10.0
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise Exception(f"Authentication failed (status={resp.status}): {body}")
            token_data = await resp.json()
            self._access_token = token_data["access_token"]
            logger.info("AMDPProvider: JWT token acquired successfully")

        # 2. Create Replay Session
        headers = {"Authorization": f"Bearer {self._access_token}"}
        # Omit 'date' to let AMDP select an eligible trading date
        async with self._http_client.post(
            f"{self._base_url}/sessions",
            headers=headers,
            json={"speed": 1.0},
            timeout=10.0
        ) as resp:
            if resp.status != 201:
                body = await resp.text()
                raise Exception(f"Failed to create replay session (status={resp.status}): {body}")
            session_data = await resp.json()
            self._session_id = session_data["sessionId"]
            logger.info(f"AMDPProvider: Created Replay Session ID: {self._session_id}")

        # 3. Get WS Feed URL & Token
        async with self._http_client.get(
            f"{self._base_url}/auth/feed-token",
            headers=headers,
            params={"sessionId": self._session_id},
            timeout=10.0
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise Exception(f"Failed to get WS feed token (status={resp.status}): {body}")
            feed_data = await resp.json()
            self._ws_url = feed_data["ws_url"]
            logger.info("AMDPProvider: Retrieved WebSocket connection URL")

    async def _connect_and_listen(self) -> None:
        """Background loop to connect to WebSocket, listen for ticks, and reconnect if needed."""
        backoff = 1.0
        while self._running:
            try:
                self._status = ProviderStatus.CONNECTING
                # Perform HTTP authentication and session setup
                await self._authenticate_and_create_session()

                # Connect to WebSocket
                logger.info(f"AMDPProvider: Connecting to WS: {self._ws_url}")
                async with self._http_client.ws_connect(self._ws_url) as ws:
                    self._ws_client = ws
                    self._status = ProviderStatus.CONNECTED
                    backoff = 1.0  # Reset backoff on success
                    logger.info("AMDPProvider: WebSocket connected and active")

                    # Subscribe to existing symbols
                    if self._subscribed_symbols:
                        await ws.send_json({
                            "action": "subscribe",
                            "symbols": list(self._subscribed_symbols)
                        })
                        logger.info(f"AMDPProvider: Resubscribed to {len(self._subscribed_symbols)} symbols")

                    # Listen for messages
                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_ws_message(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"AMDPProvider: WebSocket closed/error: {msg.data}")
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AMDPProvider connection error: {e}", exc_info=True)
                self._status = ProviderStatus.ERROR
            
            # Clean up WS connection
            self._ws_client = None
            
            if self._running:
                self._reconnect_count += 1
                logger.info(f"AMDPProvider: Reconnecting in {backoff} seconds (retry #{self._reconnect_count})...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)  # Max backoff of 30s

    async def _handle_ws_message(self, text_data: str) -> None:
        """Process tick messages from WebSocket."""
        try:
            import json
            data = json.loads(text_data)
            
            # AMDP message format verification
            if data.get("type") == "tick" and "symbol" in data:
                self._last_tick_at = time.time()
                
                # Map AMDP tick format to standard Quote format keys
                mapped_tick = {
                    "symbol": data["symbol"],
                    "exchange": data.get("exchange", "NSE"),
                    "price": data.get("ltp", 0.0),
                    "volume": data.get("volume", 0),
                    "bid_price": data.get("bid"),
                    "ask_price": data.get("ask"),
                    "bid_qty": data.get("bidQty"),
                    "ask_qty": data.get("askQty"),
                    "oi": data.get("openInterest"),
                    "timestamp": data.get("timestamp"),
                }
                
                # Dispatch tick to system
                await market_publisher.publish_tick(mapped_tick)
            elif data.get("type") == "error":
                logger.warning(f"AMDPProvider: WebSocket error message: {data.get('message')}")
        except Exception as e:
            logger.debug(f"AMDPProvider: Failed to parse WS message: {e}")
