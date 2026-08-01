"""Minimal Zebu (MYNT API / NorenOMS) REST client.

Used ONLY to pull real historical EOD candles that seed the internal
Brownian-bridge tick simulator — never for order placement or a
continuous live session. Every call is synchronous (`requests`); callers
run this inside a background task / threadpool, not the event loop
directly.

API docs (rendered at https://zebumyntapi.web.app/Base/Users/ and
https://zebumyntapi.web.app/Base/MarketQuotes/) are served from a static
MkDocs/Firebase Hosting site — that domain is documentation only and is NOT
an API host; POSTing to it returns a Firebase Hosting response, not a
NorenOMS JSON payload (this was tried and produced a JSON-decode failure on
an effectively empty body). The docs' own code samples and the endpoint URL
printed on the page both point at the real API host:
https://go.mynt.in/NorenWClientTP — confirmed against the official Users
page and cross-checked against the vendored NorenRestApiPy SDK. Override via
DataFeedConfig.base_url if login fails against the default.

Important: Zebu's "factor2" second-factor login field is NOT a TOTP/
authenticator code (there is no TOTP concept in this API at all) — per the
official docs it's the account's "DOB or PAN as entered by the user" (DOB
must be DD-MM-YYYY). It's a static value, saved once like the password.
"""
import hashlib
import json
import logging
import time
from datetime import date, datetime
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://go.mynt.in/NorenWClientTP"
_TIMEOUT = 15
# Largest interval TPSeries supports (minutes) — there is no dedicated daily
# bucket, so 4-hour bars are requested and collapsed into true daily OHLCV
# bars by the caller (see zebu_import.py::_collapse_to_daily_bars).
MAX_TPSERIES_INTERVAL_MINUTES = 240


class ZebuAuthError(Exception):
    pass


class ZebuApiError(Exception):
    pass


def _parse_json_response(resp: "requests.Response", context: str) -> Any:
    """Parse a Zebu API response as JSON, raising ZebuApiError with the raw
    body on failure instead of an opaque `json.JSONDecodeError`.

    Two Noren-family quirks observed in the wild are handled here:
    - Some endpoints prefix the JSON body with a stray newline/whitespace.
    - Some endpoints return a JSON *string* (double-encoded) rather than a
      bare object, so a successful first parse that yields a str is decoded
      once more.
    """
    text = resp.text.strip()
    if not text:
        raise ZebuApiError(
            f"Zebu {context}: empty response body (HTTP {resp.status_code}). "
            f"Check base_url — the account/app may not be provisioned for "
            f"API access, or the endpoint path is wrong for this host."
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        snippet = text[:300]
        raise ZebuApiError(
            f"Zebu {context}: non-JSON response (HTTP {resp.status_code}): {e}. "
            f"Body started with: {snippet!r}"
        ) from e
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            pass
    return data


class ZebuClient:
    """Thin synchronous client for the subset of Zebu's API needed for
    a one-off/periodic historical EOD import: QuickAuth (login) + TPSeries
    (historical candles) + symbol master download."""

    def __init__(
        self,
        client_code: str,
        password: str,
        factor2: str,
        api_key: str,
        api_secret: str,
        vendor_code: str,
        base_url: str = DEFAULT_BASE_URL,
    ):
        """`factor2` is the account's DOB (DD-MM-YYYY) or PAN, exactly as
        registered with Zebu — this is what the API calls the second login
        factor; it is not a TOTP/authenticator code."""
        self.client_code = client_code
        self.password = password
        self.factor2 = factor2
        self.api_key = api_key
        self.api_secret = api_secret
        self.vendor_code = vendor_code
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        # Symbol-master files are served from the bare host, not under the
        # /NorenWClientTP API path — derive it once rather than re-parsing
        # base_url on every download call. Also strips a legacy
        # /NorenClientTP suffix from any old saved config.
        self.root_host = (
            self.base_url.split("/NorenWClientTP")[0]
            .split("/NorenClientTP")[0]
        )
        self._session_token: Optional[str] = None

    def login(self) -> str:
        """Authenticate and return the session token (`susertoken`).
        Raises ZebuAuthError on failure."""
        pwd_hash = hashlib.sha256(self.password.encode("utf-8")).hexdigest()
        app_key_hash = hashlib.sha256(
            f"{self.client_code}|{self.api_secret}".encode("utf-8")
        ).hexdigest()

        payload_obj = {
            "source": "API",
            "apkversion": "1.0.0",
            "uid": self.client_code,
            "pwd": pwd_hash,
            "factor2": self.factor2,
            "vc": self.vendor_code,
            "appkey": app_key_hash,
            "imei": "alphasync-history-import",
        }
        body = "jData=" + json.dumps(payload_obj)

        resp = requests.post(
            f"{self.base_url}/QuickAuth",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = _parse_json_response(resp, context="QuickAuth login")

        if str(data.get("stat", "")).lower() != "ok" or not data.get("susertoken"):
            raise ZebuAuthError(f"Zebu login failed: {data.get('emsg') or data}")

        self._session_token = data["susertoken"]
        logger.info(f"Zebu login succeeded for client {self.client_code}")
        return self._session_token

    def _post(self, path: str, payload_obj: dict) -> Any:
        if not self._session_token:
            raise ZebuAuthError("Not logged in — call login() first")
        body = "jData=" + json.dumps(payload_obj) + f"&jKey={self._session_token}"
        resp = requests.post(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = _parse_json_response(resp, context=path)
        if isinstance(data, dict) and str(data.get("stat", "")).lower() == "not_ok":
            raise ZebuApiError(f"Zebu API error on {path}: {data.get('emsg') or data}")
        return data

    def get_time_price_series(
        self, exchange: str, token: str, start: date, end: date,
        interval_minutes: int = MAX_TPSERIES_INTERVAL_MINUTES,
    ) -> List[Dict[str, Any]]:
        """Historical OHLCV candles for one instrument between two dates.

        TPSeries only supports interval buckets up to 240 minutes (no daily/
        EOD option) — rows are collapsed into one true daily bar per
        calendar day by the caller (see zebu_import.py).
        """
        st = int(time.mktime(datetime.combine(start, datetime.min.time()).timetuple()))
        et = int(time.mktime(datetime.combine(end, datetime.max.time()).timetuple()))

        data = self._post(
            "/TPSeries",
            {
                "uid": self.client_code,
                "exch": exchange,
                "token": token,
                "st": str(st),
                "et": str(et),
                "intrv": str(interval_minutes),
            },
        )
        if not isinstance(data, list):
            return []

        candles = []
        for row in data:
            try:
                candles.append({
                    "time": row.get("time"),
                    "open": float(row["into"]),
                    "high": float(row["inth"]),
                    "low": float(row["intl"]),
                    # "intv" = this bucket's own volume; "v" is a running
                    # cumulative total for the day, not per-bucket — using
                    # it here would massively over-count daily volume once
                    # summed across a day's buckets.
                    "close": float(row["intc"]),
                    "volume": int(float(row.get("intv") or 0)),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return candles

    def download_symbol_master(self, exchange: str) -> bytes:
        """Download the zipped, comma-delimited symbol master file for an
        exchange (NSE/BSE/NFO/BFO/CDS/MCX)."""
        url = f"{self.root_host}/{exchange.upper()}_symbols.txt.zip"
        resp = requests.get(
            url, headers={"Authorization": self._session_token or ""}, timeout=30
        )
        resp.raise_for_status()
        return resp.content
