import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
import httpx
import websockets
from config.settings import settings

logger = logging.getLogger(__name__)

ZEBU_PROD_URL = "https://go.mynt.in"
ZEBU_WS_PROD_URL = "wss://go.mynt.in/NorenWSTP/"


class ZebuOAuthClient:
    """Client for Zebu MYNT OAuth authentication, token management, and REST API calls."""

    def __init__(self, base_url: str = None, ws_url: str = None):
        self.base_url = (base_url or getattr(settings, "ZEBU_OAUTH_BASE_URL", None) or ZEBU_PROD_URL).rstrip("/")
        self.ws_url = ws_url or ZEBU_WS_PROD_URL

    def build_authorize_url(self, client_id: str) -> str:
        """Construct the MYNT browser login URL for the admin redirect flow."""
        return f"{self.base_url}/OAuthlogin/authorize/oauth?client_id={client_id}"

    async def exchange_code_for_token(self, client_id: str, secret_key: str, code: str) -> dict:
        """Exchange the OAuth authorization code for access and refresh tokens.
        
        Noren API GenAcsTok requires checksum = sha256(client_id + secret_key + code)
        """
        raw_str = f"{client_id}{secret_key}{code}"
        checksum = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

        url = f"{self.base_url}/NorenWClientAPI/GenAcsTok"
        payload = {
            "code": code,
            "checksum": checksum,
            "client_id": client_id,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Noren API accepts jData payload format: jData={"code": ..., "checksum": ...}
            response = await client.post(url, data={"jData": json.dumps(payload)})
            response.raise_for_request()

            res_json = response.json()
            if isinstance(res_json, str):
                res_json = json.loads(res_json)

            stat = res_json.get("stat") or res_json.get("status")
            if stat and stat.lower() == "not_ok":
                emsg = res_json.get("emsg") or res_json.get("message") or "Failed to exchange auth code"
                raise ValueError(f"Zebu OAuth GenAcsTok Error: {emsg}")

            access_token = res_json.get("access_token") or res_json.get("susertoken") or res_json.get("token")
            refresh_token = res_json.get("refresh_token") or ""
            expires_in = int(res_json.get("expires_in") or 3600)

            if not access_token:
                raise ValueError(f"No access_token returned by Zebu: {res_json}")

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
                "raw": res_json,
            }

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """Refresh an expired OAuth access token."""
        url = f"{self.base_url}/NorenWClientAPI/RefreshToken"
        payload = {"refresh_token": refresh_token}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, data={"jData": json.dumps(payload)})
            response.raise_for_request()

            res_json = response.json()
            if isinstance(res_json, str):
                res_json = json.loads(res_json)

            stat = res_json.get("stat") or res_json.get("status")
            if stat and stat.lower() == "not_ok":
                emsg = res_json.get("emsg") or "Token refresh failed"
                raise ValueError(f"Zebu RefreshToken Error: {emsg}")

            access_token = res_json.get("access_token") or res_json.get("susertoken")
            expires_in = int(res_json.get("expires_in") or 3600)

            return {
                "access_token": access_token,
                "expires_in": expires_in,
                "raw": res_json,
            }

    async def download_master_zip(self, exchange: str, access_token: str) -> bytes:
        """Download exchange symbol master zip file using Bearer auth."""
        url = f"{self.base_url}/{exchange.upper()}_symbols.txt.zip"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.get(url, headers=headers)
            res.raise_for_request()
            return res.content


class ZebuLiveFeed:
    """Async WebSocket client for Zebu live tick ingestion (NorenWSTP)."""

    def __init__(
        self,
        ws_url: str,
        client_code: str,
        access_token: str,
        on_tick_callback=None,
        on_error_callback=None,
    ):
        self.ws_url = ws_url
        self.client_code = client_code
        self.access_token = access_token
        self.on_tick_callback = on_tick_callback
        self.on_error_callback = on_error_callback

        self._ws = None
        self._is_running = False
        self._subscribed_scrips = set()
        self._listen_task = None
        self._reconnect_attempts = 0

    async def start(self):
        """Connect to WebSocket and start listening for ticks."""
        self._is_running = True
        self._listen_task = asyncio.create_task(self._connection_loop())

    async def stop(self):
        """Close WebSocket session."""
        self._is_running = False
        if self._listen_task:
            self._listen_task.cancel()
        if self._ws:
            await self._ws.close()

    async def subscribe(self, scrip_list: list[str]):
        """Subscribe to scrip batch (format: ['NSE|22', 'BSE|508123', 'NFO|156871'])."""
        for s in scrip_list:
            self._subscribed_scrips.add(s)

        if self._ws and self._ws.open:
            await self._send_subscribe(scrip_list)

    async def _send_subscribe(self, scrips: list[str]):
        """Send 't: t' touchline subscribe message in batches of ~200 scrips."""
        batch_size = 200
        for i in range(0, len(scrips), batch_size):
            chunk = scrips[i : i + batch_size]
            k_val = "#".join(chunk)
            msg = {"t": "t", "k": k_val}
            await self._ws.send(json.dumps(msg))

    async def _connection_loop(self):
        """Connection loop with 1s base -> 60s max exponential backoff."""
        base_delay = 1.0
        max_delay = 60.0

        while self._is_running:
            try:
                logger.info(f"Connecting to Zebu WebSocket: {self.ws_url}")
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    self._reconnect_attempts = 0

                    # 1. Connect Handshake
                    connect_msg = {
                        "t": "c",
                        "uid": self.client_code,
                        "actid": self.client_code,
                        "source": "API",
                        "susertoken": self.access_token,
                    }
                    await ws.send(json.dumps(connect_msg))
                    resp = await ws.recv()
                    res_json = json.loads(resp)

                    if res_json.get("s") != "OK":
                        emsg = res_json.get("emsg") or "WebSocket connect handshake failed"
                        if self.on_error_callback:
                            await self.on_error_callback(emsg)
                        raise ConnectionError(emsg)

                    logger.info("Zebu WebSocket handshake successful")

                    # 2. Resubscribe scrips
                    if self._subscribed_scrips:
                        await self._send_subscribe(list(self._subscribed_scrips))

                    # 3. Read loop
                    async for raw_msg in ws:
                        if not self._is_running:
                            break
                        data = json.loads(raw_msg)
                        t = data.get("t")
                        if t in ("tf", "df") and self.on_tick_callback:
                            await self.on_tick_callback(data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._reconnect_attempts += 1
                delay = min(base_delay * (2 ** (self._reconnect_attempts - 1)), max_delay)
                logger.warning(f"Zebu WS disconnected ({e}). Reconnecting in {delay:.1f}s (attempt {self._reconnect_attempts})...")
                if self.on_error_callback:
                    await self.on_error_callback(str(e))
                await asyncio.sleep(delay)
