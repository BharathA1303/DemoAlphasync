"""
NSE Options Service — Real option chain data from NSE India public API.

NSE provides a free, unauthenticated option chain API that returns live
call/put data for indices (NIFTY, BANKNIFTY, SENSEX, FINNIFTY) and
individual stocks.

Flow:
  1. Visit nseindia.com to obtain session cookies (required by NSE CDN).
  2. Hit the option-chain endpoint with those cookies.
  3. Parse and normalise the response into a consistent schema.

Data refreshed every 60 seconds (NSE updates ~1 min during market hours).
"""

import logging
import time
import asyncio
import csv
import io
import zipfile
from datetime import datetime, timedelta
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# ── NSE API config ─────────────────────────────────────────────────────────────
_NSE_BASE = "https://www.nseindia.com"
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}

# Index symbols supported by the indices endpoint
_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "NIFTYBANK",
    "SENSEX",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
}


def _parse_expiry_to_iso(value: str) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d%b%Y", "%d%b%y"]:
        try:
            return datetime.strptime(raw.upper(), fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def _expiry_sort_key(value: str):
    parsed = _parse_expiry_to_iso(value)
    if not parsed:
        return (1, str(value or ""))
    return (0, parsed)


# ── In-memory cache ──────────────────────────────────────────────────────────
_cache: dict = {}  # symbol → response dict
_cache_ts: dict = {}  # symbol → float epoch
_CACHE_TTL = 60  # seconds

_ARCHIVE_BASE = "https://archives.nseindia.com/content/historical/DERIVATIVES"
_ARCHIVE_LOOKBACK_DAYS = 21
_ARCHIVE_CACHE_TTL = 600
_archive_cache: dict = {}  # symbol -> response dict
_archive_cache_ts: dict = {}  # symbol -> float epoch

# ── Cookie cache (avoids re-visiting homepage on every request) ───────────────
_nse_cookies: dict = {}
_nse_cookies_ts: float = 0.0
_COOKIE_TTL = 300  # refresh cookies every 5 minutes


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _archive_url_for_date(day) -> str:
    month = day.strftime("%b").upper()
    day_token = day.strftime("%d%b%Y").upper()
    return f"{_ARCHIVE_BASE}/{day.strftime('%Y')}/{month}/fo{day_token}bhav.csv.zip"


def _parse_archive_timestamp(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ["%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(raw.upper(), fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return ""


async def _get_cookies() -> dict:
    """Visit nseindia.com homepage to obtain session cookies."""
    global _nse_cookies, _nse_cookies_ts
    import httpx

    now = time.time()
    if _nse_cookies and (now - _nse_cookies_ts) < _COOKIE_TTL:
        return _nse_cookies

    try:
        async with httpx.AsyncClient(
            headers=_NSE_HEADERS, follow_redirects=True, timeout=10
        ) as client:
            resp = await client.get(_NSE_BASE)
            _nse_cookies = dict(resp.cookies)
            _nse_cookies_ts = now
            logger.debug("NSE cookies refreshed (%d cookies)", len(_nse_cookies))
            return _nse_cookies
    except Exception as exc:
        logger.warning("NSE cookie fetch failed: %s", exc)
        return _nse_cookies  # return stale if available


async def _fetch_nse(endpoint: str) -> Optional[dict]:
    """Fetch a single NSE API endpoint with session cookies and enhanced retry logic."""
    import httpx

    url = f"{_NSE_BASE}/api/{endpoint}"

    for attempt in range(3):
        if attempt > 0:
            wait_time = 2**attempt  # 2s, 4s backoff
            logger.warning(
                f"Retrying NSE API {endpoint} after {wait_time}s (attempt {attempt + 1}/3)"
            )
            await asyncio.sleep(wait_time)
            # Refresh cookies on retry — they may have expired
            global _nse_cookies_ts
            _nse_cookies_ts = 0.0

        cookies = await _get_cookies()
        try:
            async with httpx.AsyncClient(
                headers=_NSE_HEADERS,
                cookies=cookies,
                follow_redirects=True,
                timeout=15,
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    logger.debug(
                        f"NSE API {endpoint} successful on attempt {attempt + 1}"
                    )
                    return resp.json()
                if resp.status_code in (503, 429):
                    logger.warning(
                        f"NSE API {endpoint} returned HTTP {resp.status_code} (attempt {attempt + 1}/3)"
                    )
                    continue
                logger.warning(f"NSE API {endpoint} returned HTTP {resp.status_code}")
                return None
        except asyncio.TimeoutError:
            logger.warning(f"NSE API {endpoint} timeout on attempt {attempt + 1}/3")
        except Exception as exc:
            logger.warning(
                f"NSE API fetch error ({endpoint}) attempt {attempt + 1}/3: {exc}"
            )

    logger.error(f"NSE API {endpoint} failed after 3 attempts")
    return None


def _normalise_strike(record: dict, option_type: str) -> Optional[dict]:
    """Extract and normalise a single call or put row from NSE option chain record."""
    data = record.get(option_type)
    if not data:
        return None
    return {
        "strike": record.get("strikePrice", 0),
        "expiry": _parse_expiry_to_iso(data.get("expiryDate", ""))
        or data.get("expiryDate", "")
        or "",
        "option_type": option_type,  # "CE" or "PE"
        "ltp": data.get("lastPrice", 0),
        "change": data.get("change", 0),
        "change_pct": data.get("pChange", 0),
        "volume": data.get("totalTradedVolume", 0),
        "oi": data.get("openInterest", 0),
        "oi_change": data.get("changeinOpenInterest", 0),
        "bid": data.get("bidprice", 0),
        "ask": data.get("askPrice", 0),
        "iv": data.get("impliedVolatility", 0),
        "delta": data.get("delta", None),
        "gamma": data.get("gamma", None),
        "theta": data.get("theta", None),
        "vega": data.get("vega", None),
    }


def _normalise_archive_option_row(row: dict, expiry_iso: str, option_type: str) -> dict:
    close = _safe_float(row.get("CLOSE"), 0.0)
    settle = _safe_float(row.get("SETTLE_PR"), 0.0)
    ltp = close if close > 0 else settle

    return {
        "strike": _safe_float(row.get("STRIKE_PR"), 0.0),
        "expiry": expiry_iso,
        "option_type": option_type,
        "ltp": ltp,
        "change": 0,
        "change_pct": 0,
        "volume": _safe_int(row.get("CONTRACTS"), 0),
        "oi": _safe_int(row.get("OPEN_INT"), 0),
        "oi_change": _safe_int(row.get("CHG_IN_OI"), 0),
        "bid": 0,
        "ask": 0,
        "iv": 0,
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
    }


def _build_archive_chain(symbol: str, csv_text: str) -> Optional[dict]:
    sym = symbol.upper().strip()

    strike_map: dict = {}
    expiry_dates: set[str] = set()
    fut_underlyings: dict[str, float] = {}
    timestamp = ""

    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        instrument = str(row.get("INSTRUMENT") or "").upper().strip()
        row_symbol = str(row.get("SYMBOL") or "").upper().strip()
        if row_symbol != sym:
            continue

        expiry_raw = row.get("EXPIRY_DT")
        expiry_iso = _parse_expiry_to_iso(expiry_raw)
        if not expiry_iso:
            continue

        ts = _parse_archive_timestamp(row.get("TIMESTAMP"))
        if ts:
            timestamp = ts

        if instrument == "FUTIDX":
            close = _safe_float(row.get("CLOSE"), 0.0)
            settle = _safe_float(row.get("SETTLE_PR"), 0.0)
            spot_guess = close if close > 0 else settle
            if spot_guess > 0:
                fut_underlyings[expiry_iso] = spot_guess
            continue

        if instrument != "OPTIDX":
            continue

        option_type = str(row.get("OPTION_TYP") or "").upper().strip()
        if option_type not in {"CE", "PE"}:
            continue

        strike = _safe_float(row.get("STRIKE_PR"), 0.0)
        if strike <= 0:
            continue

        expiry_dates.add(expiry_iso)
        key = (expiry_iso, strike)
        if key not in strike_map:
            strike_map[key] = {
                "strike": strike,
                "expiry": expiry_iso,
                "CE": None,
                "PE": None,
            }

        strike_map[key][option_type] = _normalise_archive_option_row(
            row, expiry_iso, option_type
        )

    if not strike_map:
        return None

    expiry_list = sorted(expiry_dates, key=_expiry_sort_key)
    underlying_price = 0.0
    for exp in expiry_list:
        price = fut_underlyings.get(exp)
        if price and price > 0:
            underlying_price = price
            break

    if underlying_price <= 0:
        rows_sorted = sorted(
            strike_map.values(), key=lambda r: (r["expiry"], r["strike"])
        )
        if rows_sorted:
            middle = rows_sorted[len(rows_sorted) // 2]
            underlying_price = float(middle.get("strike") or 0)

    chain = sorted(strike_map.values(), key=lambda r: (r["expiry"], r["strike"]))

    return {
        "symbol": sym,
        "underlying_price": float(underlying_price),
        "expiry_dates": expiry_list,
        "chain": chain,
        "timestamp": timestamp or datetime.utcnow().strftime("%Y-%m-%d"),
        "source": "nse_archive",
    }


async def _fetch_archive_option_chain(symbol: str) -> Optional[dict]:
    sym = symbol.upper().strip()

    now = time.time()
    if (
        sym in _archive_cache
        and (now - _archive_cache_ts.get(sym, 0)) < _ARCHIVE_CACHE_TTL
    ):
        return _archive_cache[sym]

    today = datetime.utcnow().date()
    candidate_days = [
        today - timedelta(days=offset) for offset in range(_ARCHIVE_LOOKBACK_DAYS + 1)
    ]

    for months_back in [30, 60, 90, 180, 365, 540, 730]:
        anchor = today - timedelta(days=months_back)
        for day_offset in range(0, 8):
            candidate_days.append(anchor - timedelta(days=day_offset))

    seen_urls = set()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for day in candidate_days:
                url = _archive_url_for_date(day)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                resp = await client.get(url)
                if resp.status_code != 200 or not resp.content:
                    continue

                try:
                    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                        csv_files = [
                            name
                            for name in zf.namelist()
                            if name.lower().endswith(".csv")
                        ]
                        if not csv_files:
                            continue
                        csv_bytes = zf.read(csv_files[0])

                    csv_text = csv_bytes.decode("utf-8", errors="replace")
                    parsed = _build_archive_chain(sym, csv_text)
                    if parsed:
                        _archive_cache[sym] = parsed
                        _archive_cache_ts[sym] = now
                        return parsed
                except Exception:
                    continue
    except Exception:
        return None

    return None


async def get_option_chain(symbol: str) -> Optional[dict]:
    """
    Fetch live option chain for an index or stock.

    Returns:
        {
          "symbol":           str,
          "underlying_price": float,
          "expiry_dates":     [str, ...],      # sorted nearest-first
          "chain":            [
            {
              "strike":       float,
              "expiry":       str,
              "CE": {...},    # call data (may be None)
              "PE": {...},    # put data (may be None)
            },
            ...
          ],
          "timestamp":        str,
        }
    """
    sym = symbol.upper().strip()

    # Cache check
    now = time.time()
    if sym in _cache and (now - _cache_ts.get(sym, 0)) < _CACHE_TTL:
        return _cache[sym]

    # Choose correct endpoint
    if sym in _INDEX_SYMBOLS or sym.startswith("NIFTY") or sym == "SENSEX":
        endpoint = f"option-chain-indices?symbol={sym}"
    else:
        endpoint = f"option-chain-equities?symbol={sym}"

    raw = await _fetch_nse(endpoint)
    if not raw:
        archive = await _fetch_archive_option_chain(sym)
        if archive:
            _cache[sym] = archive
            _cache_ts[sym] = now
            return archive

        stale = _cache.get(sym)
        if stale:
            return {
                **stale,
                "stale": True,
            }
        return None

    try:
        records = raw.get("records", {})
        filtered = raw.get("filtered", {})

        underlying_price = (
            records.get("underlyingValue") or filtered.get("underlyingValue") or 0
        )
        expiry_dates = sorted(
            {
                _parse_expiry_to_iso(expiry) or str(expiry or "").strip()
                for expiry in records.get("expiryDates", [])
                if str(expiry or "").strip()
            },
            key=_expiry_sort_key,
        )
        data_rows = records.get("data", [])

        # Build combined call+put rows per strike
        strike_map: dict = {}
        for row in data_rows:
            strike = row.get("strikePrice", 0)
            raw_expiry = (row.get("CE") or row.get("PE") or {}).get(
                "expiryDate", ""
            ) or ""
            expiry = _parse_expiry_to_iso(raw_expiry) or raw_expiry
            key = (expiry, strike)
            if key not in strike_map:
                strike_map[key] = {
                    "strike": strike,
                    "expiry": expiry,
                    "CE": None,
                    "PE": None,
                }
            ce = _normalise_strike(row, "CE")
            pe = _normalise_strike(row, "PE")
            if ce:
                strike_map[key]["CE"] = ce
            if pe:
                strike_map[key]["PE"] = pe

        chain = sorted(strike_map.values(), key=lambda r: (r["expiry"], r["strike"]))

        if not chain:
            archive = await _fetch_archive_option_chain(sym)
            if archive:
                _cache[sym] = archive
                _cache_ts[sym] = now
                return archive

        result = {
            "symbol": sym,
            "underlying_price": float(underlying_price),
            "expiry_dates": expiry_dates,
            "chain": chain,
            "timestamp": raw.get("records", {}).get("timestamp", ""),
            "source": "nse",
        }

        _cache[sym] = result
        _cache_ts[sym] = now
        return result

    except Exception as exc:
        logger.error(
            "NSE option chain parse failed for %s: %s", sym, exc, exc_info=True
        )
        archive = await _fetch_archive_option_chain(sym)
        if archive:
            _cache[sym] = archive
            _cache_ts[sym] = now
            return archive
        return None


async def get_expiry_dates(symbol: str) -> list:
    """Return available expiry dates for a symbol (nearest-first)."""
    chain = await get_option_chain(symbol)
    if chain:
        return chain.get("expiry_dates", [])
    return []


async def get_filtered_chain(
    symbol: str,
    expiry: Optional[str] = None,
    strikes_around_atm: int = 20,
) -> Optional[dict]:
    """
    Return option chain filtered to a single expiry and limited strikes around ATM.

    If expiry is None, the nearest available expiry is used.
    strikes_around_atm: number of strikes above AND below ATM to include.
    """
    full = await get_option_chain(symbol)
    if not full:
        return None

    expiry_dates = full["expiry_dates"]
    if not expiry_dates:
        return full

    target_expiry = expiry if expiry in expiry_dates else expiry_dates[0]
    spot = full["underlying_price"]

    rows = [r for r in full["chain"] if r["expiry"] == target_expiry]
    rows_sorted = sorted(rows, key=lambda r: r["strike"])

    # Find ATM index
    if spot and rows_sorted:
        atm_idx = min(
            range(len(rows_sorted)),
            key=lambda i: abs(rows_sorted[i]["strike"] - spot),
        )
        lo = max(0, atm_idx - strikes_around_atm)
        hi = min(len(rows_sorted), atm_idx + strikes_around_atm + 1)
        rows_sorted = rows_sorted[lo:hi]

    return {
        **full,
        "selected_expiry": target_expiry,
        "chain": rows_sorted,
    }
