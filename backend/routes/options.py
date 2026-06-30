"""
Options routes — Zebu-only option chain data.

All live option-chain and expiry data is sourced from active Zebu sessions.
"""

import logging
import io
import zipfile
import re
import asyncio
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional

import httpx

from services.market_data import get_system_quote_live_only
from services.broker_session import broker_session_manager
from providers.symbol_mapper import load_zebu_contracts
from config.settings import settings

router = APIRouter(prefix="/api/options", tags=["Options"])
logger = logging.getLogger(__name__)

# Supported index underlyings
_SUPPORTED_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
]

_ZEBU_OPT_URLS = {
    "NFO": [
        "https://go.mynt.in/NFO_symbols.txt.zip",
        "https://api.zebull.in/NFO_symbols.txt.zip",
    ],
    "BFO": [
        "https://go.mynt.in/BFO_symbols.txt.zip",
        "https://api.zebull.in/BFO_symbols.txt.zip",
    ],
}

_ZEBU_OPT_CACHE: dict[str, dict] = {}
_SPOT_MAP = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "^CNXFIN",
    "MIDCPNIFTY": "^CNXMIDCAP",
    "NIFTYNXT50": "^CNXJUNIOR",
    "SENSEX": "^BSESN",
}

_OPTION_STRIKE_STEP = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "NIFTYNXT50": 50,
    "SENSEX": 100,
}

_ZEBU_PROVIDER_RETRY_SECONDS = 6.0
_ZEBU_PROVIDER_RETRY_SLEEP = 1.0


def _snapshot_epoch_ms(value) -> int:
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    if value is None:
        return now_ms
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1_000_000_000_000:
            return int(v)
        if v > 1_000_000_000:
            return int(v * 1000)
        return int(v * 1000)
    if isinstance(value, str):
        try:
            return int(
                datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                * 1000
            )
        except Exception:
            return now_ms
    return now_ms


def _snapshot_envelope(data: dict, stream_symbols: list, snapshot_ts, snapshot: bool) -> dict:
    ts_ms = _snapshot_epoch_ms(snapshot_ts)
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    return {
        "snapshot": snapshot,
        "snapshot_ts": ts_ms,
        "stale_ms": max(0, now_ms - ts_ms),
        "stream_symbols": stream_symbols or [],
        "data": data or {},
    }


def _register_options_hot(symbols: list[str]) -> None:
    """Promote active option legs to HOT tier for unthrottled WS emit (options desk only)."""
    try:
        from market.quote_coordinator import quote_coordinator
        from market.symbol_priority_engine import PriorityTier, symbol_priority_engine

        for raw in symbols or []:
            sym = str(raw or "").strip().upper()
            if not sym:
                continue
            symbol_priority_engine.register(sym, PriorityTier.HOT)
            quote_coordinator.register_hot(sym)
    except Exception as exc:
        logger.debug(f"Options HOT registration skipped: {exc}")


async def _set_redis_options_cache(key: str, payload: dict, ttl_seconds: int) -> None:
    try:
        from cache.redis_client import get_redis
        from config.settings import settings as _settings

        redis = await get_redis(_settings.REDIS_URL)
        await redis.setex(key, ttl_seconds, json.dumps(payload))
    except Exception:
        return


async def _get_redis_options_cache(key: str) -> Optional[dict]:
    try:
        from cache.redis_client import get_redis
        from config.settings import settings as _settings

        redis = await get_redis(_settings.REDIS_URL)
        cached = await redis.get(key)
        if not cached:
            return None
        return json.loads(cached)
    except Exception:
        return None


async def _get_active_zebu_provider(wait_seconds: float = _ZEBU_PROVIDER_RETRY_SECONDS):
    """Return a live Zebu provider, waiting briefly for startup/session recovery."""
    deadline = asyncio.get_event_loop().time() + max(0.0, wait_seconds)
    provider = broker_session_manager.get_any_session()
    if provider is not None:
        return provider

    try:
        from services.master_session import master_session_service

        await master_session_service.initialize()
    except Exception as e:
        logger.debug(f"Master-session recovery failed for options provider: {e}")

    while asyncio.get_event_loop().time() < deadline:
        provider = broker_session_manager.get_any_session()
        if provider is not None:
            return provider
        await asyncio.sleep(_ZEBU_PROVIDER_RETRY_SLEEP)
        try:
            from services.master_session import master_session_service

            await master_session_service.initialize()
        except Exception:
            pass

    return broker_session_manager.get_any_session()


def _parse_expiry_date(value: str) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d%b%Y", "%d-%m-%Y", "%d-%b-%y"]:
        try:
            return datetime.strptime(raw.upper(), fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def _extract_option_side(tsym: str) -> Optional[str]:
    t = str(tsym or "").upper().strip()
    if t.endswith("CE"):
        return "CE"
    if t.endswith("PE"):
        return "PE"
    return None


def _extract_strike_from_tsym(tsym: str) -> Optional[float]:
    t = str(tsym or "").upper().strip()
    # Common format: NIFTY24APR2523000CE -> strike 23000
    match = re.search(r"(\d+(?:\.\d+)?)\s*(CE|PE)$", t)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _extract_expiry_from_tsym(tsym: str) -> Optional[str]:
    t = str(tsym or "").upper().strip()
    # Common option contract pattern includes DDMMMYY, e.g. 24APR25
    match = re.search(r"(\d{2}[A-Z]{3}\d{2})", t)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d%b%y").strftime("%Y-%m-%d")
    except Exception:
        return None


def _safe_float(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed == parsed else 0.0


def _normalize_zebu_quote_payload(raw: Optional[dict]) -> dict:
    """Map Zebu GetQuotes / GetOptionChain leg fields to canonical quote keys."""
    if not raw or not isinstance(raw, dict):
        return {}

    lower = {str(k).lower(): v for k, v in raw.items()}

    def pick(*keys: str):
        for key in keys:
            val = lower.get(key.lower())
            if val not in (None, ""):
                return val
        return None

    ltp = _safe_float(
        pick("lp", "ltp", "last_price", "price", "ls", "lastprice", "last_traded_price")
    )
    prev_close = _safe_float(pick("c", "close", "prev_close", "pdc", "previous_close"))
    change = pick("cng", "change", "net_change", "ch")
    change_pct = pick("pc", "change_percent", "change_pct", "pchange", "per")
    oi = _safe_float(pick("oi", "open_interest"))
    poi = _safe_float(pick("poi", "prev_oi"))
    oi_change_raw = pick("oi_change", "oichange", "oi_chg")
    if oi > 0 and poi > 0:
        oi_change = oi - poi
    elif oi_change_raw not in (None, ""):
        oi_change = _safe_float(oi_change_raw)
    else:
        oi_change = None

    if change is None and prev_close > 0 and ltp > 0:
        change = ltp - prev_close
    change_val = _safe_float(change)
    change_pct_val = _safe_float(change_pct)
    if change_pct_val == 0 and prev_close > 0 and change_val != 0:
        change_pct_val = (change_val / prev_close) * 100.0

    tsym = str(pick("tsym", "symbol", "trading_symbol") or raw.get("tsym") or "").upper()
    token = str(pick("token") or raw.get("token") or "").strip()

    return {
        "tsym": tsym,
        "token": token,
        "ltp": ltp,
        "price": ltp,
        "lp": ltp,
        "change": change_val,
        "change_percent": round(change_pct_val, 2),
        "change_pct": round(change_pct_val, 2),
        "volume": int(_safe_float(pick("v", "volume", "vol"))),
        "oi": int(oi) if oi > 0 else int(_safe_float(pick("oi"))),
        "oi_change": int(oi_change) if oi_change is not None else None,
        "bid": _safe_float(pick("bp1", "bid", "bid_price", "b")),
        "ask": _safe_float(pick("sp1", "ask", "ask_price", "a")),
        "iv": _safe_float(pick("iv", "implied_volatility")),
        "delta": _safe_float(pick("delta", "d")),
        "gamma": _safe_float(pick("gamma", "g")),
        "theta": _safe_float(pick("theta", "t")),
        # IMPORTANT: do NOT alias vega to "v" — Zebu often uses "v" for volume.
        # This was producing exploded vega values (volume leaked into vega).
        "vega": _safe_float(pick("vega", "vg", "vga")),
    }


_HISTORY_PERIOD_DAYS = {
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

_INTRADAY_INTERVAL_MAP = {
    "1m": "1",
    "2m": "2",
    "3m": "3",
    "5m": "5",
    "10m": "10",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
}


@router.get("/history")
async def option_history(
    tsym: str = Query(..., description="Option contract trading symbol (Zebu tsym)"),
    token: str = Query(..., description="Zebu token for contract"),
    exchange: str = Query("NFO", description="Zebu exchange segment: NFO/BFO"),
    period: str = Query("1mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|3y|5y|max)$"),
    interval: str = Query(
        "5m", pattern="^(1m|2m|3m|5m|10m|15m|30m|1h|2h|4h|1d|1wk|1mo)$"
    ),
):
    """
    Options-only historical candles using token+exchange directly.

    Why this exists:
    - `/api/market/history` resolves symbols through the global symbol mapper normalization,
      which can treat derivative contract symbols as equities (`.NS`) and fail resolution.
    - The options desk already has authoritative `token`/`exchange` from contract-master.

    This endpoint does NOT change shared market routes, Redis schemas, or WS behavior.
    """
    provider = await _get_active_zebu_provider()
    if provider is None:
        raise HTTPException(status_code=503, detail="No active provider session for history.")

    exch = str(exchange or "NFO").strip().upper()
    tok = str(token or "").strip()
    trading_symbol = str(tsym or "").strip().upper()
    if not tok or not trading_symbol:
        raise HTTPException(status_code=400, detail="token and tsym are required.")

    days = _HISTORY_PERIOD_DAYS.get(period, 30)
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    st_epoch = int(start_time.timestamp())
    et_epoch = int(end_time.timestamp())

    # Daily+ uses EODChartData (needs trading symbol). Intraday uses TPSeries (needs token).
    try:
        if interval in _INTRADAY_INTERVAL_MAP:
            candles = await provider._fetch_tp_series(
                exch, tok, st_epoch, et_epoch, _INTRADAY_INTERVAL_MAP[interval]
            )
        else:
            candles = await provider._fetch_eod_data(exch, trading_symbol, st_epoch, et_epoch)
    except Exception as e:
        logger.warning(f"Options history fetch failed for {trading_symbol}: {e}")
        candles = []

    return {"symbol": trading_symbol, "candles": candles or [], "count": len(candles or [])}


def _to_option_side(
    quote: Optional[dict], option_type: str, strike: float, expiry: str
) -> Optional[dict]:
    if not quote:
        return None
    normalized = _normalize_zebu_quote_payload(quote)
    ltp_val = normalized.get("ltp") or 0.0
    if ltp_val <= 0:
        bid = normalized.get("bid") or 0.0
        ask = normalized.get("ask") or 0.0
        if bid > 0 and ask > 0:
            ltp_val = round((bid + ask) / 2.0, 2)
        elif bid > 0:
            ltp_val = bid
        elif ask > 0:
            ltp_val = ask
        else:
            ltp_val = 0.0
    tsym = normalized.get("tsym") or ""
    token = normalized.get("token") or ""
    if ltp_val <= 0 and not (tsym or token):
        return None
    return {
        "strike": strike,
        "expiry": expiry,
        "option_type": option_type,
        "tsym": tsym,
        "token": token,
        "ltp": ltp_val,
        "change": normalized.get("change") or 0,
        "change_pct": normalized.get("change_pct") or 0,
        "volume": normalized.get("volume") or 0,
        "oi": normalized.get("oi") or 0,
        "oi_change": normalized.get("oi_change") or 0,
        "bid": normalized.get("bid") or 0,
        "ask": normalized.get("ask") or 0,
        "iv": normalized.get("iv") or 0,
        "delta": normalized.get("delta"),
        "gamma": normalized.get("gamma"),
        "theta": normalized.get("theta"),
        "vega": normalized.get("vega"),
    }


async def _load_zebu_option_contracts(symbol: str) -> dict:
    sym = symbol.upper().strip()
    exch = "BFO" if sym == "SENSEX" else "NFO"
    cache_key = f"{exch}:{sym}"
    if cache_key in _ZEBU_OPT_CACHE:
        cached_mem = _ZEBU_OPT_CACHE.get(cache_key) or {}
        # Ignore poisoned empty cache entries from prior parse failures.
        if cached_mem:
            return cached_mem

    # Try Redis cache first — CDN zips are 20MB+ so we keep the parsed map
    # for the trading day to survive restarts and transient CDN outages.
    redis_key = f"options:contracts:{cache_key}"
    try:
        from cache.redis_client import get_redis
        from config.settings import settings as _settings
        import json as _json

        redis = await get_redis(_settings.REDIS_URL)
        cached = await redis.get(redis_key)
        if cached:
            parsed = _json.loads(cached)
            # JSON keys are strings — restore float strike keys
            restored: dict = {}
            for exp, strikes in parsed.items():
                restored[exp] = {float(k): v for k, v in strikes.items()}
            # Ignore poisoned empty Redis entries from prior parse failures.
            if restored:
                _ZEBU_OPT_CACHE[cache_key] = restored
                return restored
    except Exception as e:
        logger.debug(f"Options Redis cache read failed for {cache_key}: {e}")

    urls = _ZEBU_OPT_URLS.get(exch, [])
    raw_zip = None
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code == 200 and resp.content:
                    raw_zip = resp.content
                    break
        except Exception:
            continue

    if not raw_zip:
        return {}

    by_expiry: dict[str, dict[float, dict[str, dict[str, str]]]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
            if not txt_files:
                return {}

            with zf.open(txt_files[0]) as f:
                raw = f.read()
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    content = raw.decode("latin-1", errors="replace")

        lines = content.splitlines()
        if not lines:
            return {}

        delimiter = "," if "," in lines[0] else "|"
        header = [col.strip().lower() for col in lines[0].split(delimiter)]
        tsym_idx = next(
            (
                i
                for i, h in enumerate(header)
                if "tradingsymbol" in h.replace(" ", "") or h == "symbol"
            ),
            2,
        )
        expiry_idx = next((i for i, h in enumerate(header) if "expiry" in h), 4)
        strike_idx = next((i for i, h in enumerate(header) if "strike" in h), 5)
        opt_idx = next(
            (i for i, h in enumerate(header) if "option" in h or "optt" in h), 6
        )
        token_idx = next((i for i, h in enumerate(header) if "token" in h), 1)
        exch_idx = next((i for i, h in enumerate(header) if "exchange" in h), -1)

        contracts_to_register: list[dict] = []

        for line in lines[1:]:
            parts = line.split(delimiter)
            if len(parts) <= max(tsym_idx, expiry_idx, strike_idx, opt_idx, token_idx):
                continue

            tsym = parts[tsym_idx].strip().upper()
            if not tsym.startswith(sym):
                continue

            token = parts[token_idx].strip() if token_idx < len(parts) else ""
            exchange = (
                parts[exch_idx].strip().upper()
                if exch_idx >= 0 and exch_idx < len(parts)
                else exch
            )

            opt_type = parts[opt_idx].strip().upper() if opt_idx < len(parts) else ""
            if opt_type not in {"CE", "PE"}:
                opt_type = _extract_option_side(tsym) or ""
            if opt_type not in {"CE", "PE"}:
                continue

            raw_expiry = parts[expiry_idx].strip() if expiry_idx < len(parts) else ""
            expiry = _parse_expiry_date(raw_expiry) or _extract_expiry_from_tsym(tsym)
            if not expiry:
                continue

            try:
                strike_raw = (
                    parts[strike_idx].strip() if strike_idx < len(parts) else ""
                )
                strike = float(strike_raw) if strike_raw else None
            except Exception:
                strike = None

            if strike is None:
                strike = _extract_strike_from_tsym(tsym)
            if strike is None:
                continue

            instrument = {
                "symbol": tsym,
                "token": token,
                "exchange": exchange or exch,
            }
            by_expiry.setdefault(expiry, {}).setdefault(strike, {})[
                opt_type
            ] = instrument

            if token:
                contracts_to_register.append(
                    {
                        "symbol": tsym,
                        "canonical": tsym,
                        "trading_symbol": tsym,
                        "token": token,
                        "exchange": exchange or exch,
                    }
                )

        if contracts_to_register:
            load_zebu_contracts(contracts_to_register)

    except Exception as e:
        logger.warning(f"Failed to parse Zebu options contracts for {sym}: {e}")
        return {}

    if by_expiry:
        _ZEBU_OPT_CACHE[cache_key] = by_expiry

    # Persist the parsed map to Redis so restarts / transient CDN outages
    # don't force every caller to re-fetch the 20MB+ zip.
    try:
        from cache.redis_client import get_redis
        from config.settings import settings as _settings
        import json as _json

        redis = await get_redis(_settings.REDIS_URL)
        # Stringify float strike keys for JSON; restored on read.
        serializable = {
            exp: {str(k): v for k, v in strikes.items()}
            for exp, strikes in by_expiry.items()
        }
        if serializable:
            await redis.setex(redis_key, 6 * 3600, _json.dumps(serializable))
    except Exception as e:
        logger.debug(f"Options Redis cache write failed for {cache_key}: {e}")

    return by_expiry


def _nearest_expiry(expiry_dates: list[str]) -> Optional[str]:
    if not expiry_dates:
        return None

    today = datetime.utcnow().date()
    for exp in sorted(expiry_dates):
        try:
            if datetime.strptime(exp, "%Y-%m-%d").date() >= today:
                return exp
        except Exception:
            continue
    return sorted(expiry_dates)[0]


async def _zebu_contract_master_chain(
    provider,
    sym: str,
    expiry: Optional[str],
    strikes: int,
    spot: float,
    exch: str,
) -> Optional[dict]:
    """Build a live chain from Zebu contract master + Zebu quote endpoint."""
    if spot <= 0:
        logger.warning(
            f"Spot quote unavailable for {sym}; using strike-midpoint centering"
        )

    contracts_by_expiry = await _load_zebu_option_contracts(sym)
    if not contracts_by_expiry:
        logger.warning(f"No Zebu option contracts loaded for {sym}")
        return None

    expiry_dates = sorted(contracts_by_expiry.keys())
    requested_expiry = _parse_expiry_date(expiry) if expiry else None
    selected_expiry = requested_expiry or _nearest_expiry(expiry_dates)
    if not selected_expiry or selected_expiry not in contracts_by_expiry:
        logger.warning(
            f"Requested expiry unavailable for {sym}: {requested_expiry or expiry}"
        )
        return None

    strike_map = contracts_by_expiry.get(selected_expiry) or {}
    available_strikes = sorted(strike_map.keys())
    if not available_strikes:
        logger.warning(f"No strikes found for {sym} expiry {selected_expiry}")
        return None

    if spot > 0:
        atm_idx = min(
            range(len(available_strikes)),
            key=lambda idx: abs(float(available_strikes[idx]) - spot),
        )
        effective_spot = float(spot)
    else:
        atm_idx = len(available_strikes) // 2
        effective_spot = float(available_strikes[atm_idx])
    width = max(1, int(strikes))
    lo = max(0, atm_idx - width)
    hi = min(len(available_strikes), atm_idx + width + 1)
    selected_strikes = available_strikes[lo:hi]

    quote_semaphore = asyncio.Semaphore(24)

    async def _quote_leg(strike: float, optt: str, instrument: dict):
        token = str(instrument.get("token") or "").strip()
        exchange = str(instrument.get("exchange") or exch).strip().upper() or exch
        tsym = str(instrument.get("symbol") or "").upper().strip()
        if not token:
            return strike, optt, _to_option_side(
                {"tsym": tsym, "token": token}, optt, strike, selected_expiry
            ), tsym

        async with quote_semaphore:
            try:
                quote = await asyncio.wait_for(
                    provider._rest_post(
                        "/GetQuotes",
                        {
                            "exch": exchange,
                            "token": token,
                        },
                    ),
                    timeout=2.5,
                )
            except Exception as exc:
                logger.debug(f"GetQuotes failed for {tsym or token}: {exc}")
                return strike, optt, _to_option_side(
                    {"tsym": tsym, "token": token}, optt, strike, selected_expiry
                ), tsym

        if not quote or quote.get("stat") != "Ok":
            logger.debug(
                f"GetQuotes returned no live data for {tsym or token}: {quote}"
            )
            return strike, optt, _to_option_side(
                {"tsym": tsym, "token": token}, optt, strike, selected_expiry
            ), tsym

        return strike, optt, _to_option_side(quote, optt, strike, selected_expiry), tsym

    tasks = []
    prewarm_symbols: list[str] = []
    for strike in selected_strikes:
        legs = strike_map.get(strike) or {}
        for optt in ("CE", "PE"):
            instrument = legs.get(optt)
            if instrument:
                tsym = str(instrument.get("symbol") or "").upper().strip()
                if tsym:
                    prewarm_symbols.append(tsym)
                tasks.append(_quote_leg(strike, optt, instrument))

    if not tasks:
        return None

    prewarm_unique = list(dict.fromkeys(prewarm_symbols))
    if prewarm_unique:
        try:
            await provider.subscribe(prewarm_unique)
            _register_options_hot([*prewarm_unique, _SPOT_MAP.get(sym.upper().strip(), "^NSEI")])
        except Exception as exc:
            logger.debug(f"Option WS prewarm skipped/failed: {exc}")

    leg_results = await asyncio.gather(*tasks, return_exceptions=True)
    grouped: dict[float, dict] = {}
    subscription_symbols: list[str] = []

    for item in leg_results:
        if isinstance(item, Exception):
            continue
        strike, optt, side, tsym = item
        row = grouped.setdefault(
            strike,
            {
                "strike": strike,
                "expiry": selected_expiry,
                "CE": None,
                "PE": None,
            },
        )
        if side:
            row[optt] = side
        if tsym:
            subscription_symbols.append(tsym)

    rows = [grouped[strike] for strike in sorted(grouped.keys())]
    rows = [row for row in rows if row.get("CE") or row.get("PE")]
    if not rows:
        logger.warning(f"No live option quotes returned for {sym} {selected_expiry}")
        return None

    stream_unique = list(dict.fromkeys(subscription_symbols))
    if stream_unique:
        try:
            await provider.subscribe(stream_unique)
        except Exception as exc:
            logger.debug(f"Option WS subscribe skipped/failed: {exc}")
        spot_sym = _SPOT_MAP.get(sym.upper().strip(), "^NSEI")
        _register_options_hot([*stream_unique, spot_sym])

    return {
        "symbol": sym,
        "underlying_price": effective_spot,
        "expiry_dates": expiry_dates,
        "selected_expiry": selected_expiry,
        "chain": rows,
        "stream_symbols": stream_unique,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "zebu",
    }


async def _zebu_underlying_future_price(provider, sym: str, exch: str) -> float:
    """Fast spot proxy for indices whose direct Zebu index token is unavailable."""
    try:
        search = await asyncio.wait_for(
            provider._rest_post("/SearchScrip", {"exch": exch, "stext": sym}),
            timeout=3.0,
        )
    except Exception:
        return 0.0

    if not search or search.get("stat") != "Ok":
        return 0.0

    values = search.get("values") or []
    fut_candidates = []
    for item in values:
        tsym = str(item.get("tsym") or "").upper().strip()
        token = str(item.get("token") or "").strip()
        if token and tsym.startswith(sym) and tsym.endswith(("FUT", "F")):
            fut_candidates.append(item)

    if not fut_candidates:
        return 0.0

    def _sort_key(item: dict):
        parsed = _extract_expiry_from_tsym(str(item.get("tsym") or ""))
        return parsed or "9999-12-31"

    fut = sorted(fut_candidates, key=_sort_key)[0]
    token = str(fut.get("token") or "").strip()
    if not token:
        return 0.0

    try:
        quote = await asyncio.wait_for(
            provider._rest_post("/GetQuotes", {"exch": exch, "token": token}),
            timeout=2.5,
        )
    except Exception:
        return 0.0

    normalized = _normalize_zebu_quote_payload(quote if isinstance(quote, dict) else {})
    price = _safe_float(normalized.get("ltp"))
    return price if price > 0 else 0.0


async def _zebu_option_chain(
    symbol: str, expiry: Optional[str], strikes: int
) -> Optional[dict]:
    sym = symbol.upper().strip()
    provider = await _get_active_zebu_provider()
    if provider is None:
        logger.warning("No active provider session for Zebu option chain")
        return None

    exch = "BFO" if sym == "SENSEX" else "NFO"
    spot_symbol = _SPOT_MAP.get(sym, "^NSEI")
    spot_quote = await get_system_quote_live_only(spot_symbol, allow_recover=True)
    spot = 0.0
    if spot_quote:
        try:
            spot = float(
                spot_quote.get("ltp")
                or spot_quote.get("price")
                or spot_quote.get("lp")
                or 0
            )
        except Exception:
            spot = 0.0

    if spot <= 0:
        spot = await _zebu_underlying_future_price(provider, sym, exch)

    strike_step = _OPTION_STRIKE_STEP.get(sym, 50)
    center_strike = int(round((spot or 0.0) / strike_step) * strike_step)
    if center_strike <= 0:
        center_strike = strike_step

    requested_expiry = _parse_expiry_date(expiry) if expiry else None

    contract_master_result = await _zebu_contract_master_chain(
        provider,
        sym,
        expiry,
        strikes,
        spot,
        exch,
    )
    if contract_master_result:
        return contract_master_result

    async def _post(route: str, payload: dict, timeout_sec: float = 8.0):
        try:
            return await asyncio.wait_for(
                provider._rest_post(route, payload), timeout=timeout_sec
            )
        except Exception as e:
            logger.debug(f"Options {route} failed for {sym}: {e}")
            return None

    # Step A: SearchScrip -> identify a valid base futures tsym for GetOptionChain.
    search = None
    for _ in range(2):
        search = await _post("/SearchScrip", {"exch": exch, "stext": sym}, 6.0)
        if search and search.get("stat") == "Ok":
            break
        provider = await _get_active_zebu_provider()
        if provider is None:
            break
    if not search or search.get("stat") != "Ok":
        logger.warning(f"SearchScrip failed for {sym} on {exch}")
        return None

    values = search.get("values", []) or []
    fut_candidates = []
    for item in values:
        tsym = str(item.get("tsym") or "").upper().strip()
        if not tsym:
            continue
        if tsym.endswith(("FUT", "F")) and sym in tsym:
            fut_candidates.append(item)

    if not fut_candidates:
        logger.warning(f"No futures tsym candidate from SearchScrip for {sym}")
        return None

    def _expiry_from_tsym(tsym: str) -> Optional[str]:
        match = re.search(r"(\d{2}[A-Z]{3}\d{2,4})", tsym)
        if not match:
            return None
        raw = match.group(1)
        for fmt in ["%d%b%y", "%d%b%Y"]:
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        return None

    selected_fut = None
    if requested_expiry:
        for item in fut_candidates:
            tsym = str(item.get("tsym") or "").upper().strip()
            if _expiry_from_tsym(tsym) == requested_expiry:
                selected_fut = item
                break
    if selected_fut is None:
        # Nearest expiry approximation by parsed tsym date.
        def _fut_sort_key(item: dict):
            tsym = str(item.get("tsym") or "").upper().strip()
            parsed = _expiry_from_tsym(tsym)
            if not parsed:
                return "9999-12-31"
            return parsed

        fut_candidates = sorted(fut_candidates, key=_fut_sort_key)
        selected_fut = fut_candidates[0]

    fut_tsym = str(selected_fut.get("tsym") or "").upper().strip()
    if not fut_tsym:
        return None

    # Step B: GetOptionChain around ATM center strike.
    chain = None
    for _ in range(2):
        chain = await _post(
            "/GetOptionChain",
            {
                "exch": exch,
                "tsym": fut_tsym,
                "strprc": str(center_strike),
                "cnt": str(int(strikes)),
            },
            8.0,
        )
        if chain and chain.get("stat") == "Ok":
            break
        provider = await _get_active_zebu_provider()
        if provider is None:
            break
    if not chain or chain.get("stat") != "Ok":
        logger.warning(f"GetOptionChain failed for {sym} ({fut_tsym})")
        return None

    chain_values = chain.get("values") or []
    if not chain_values:
        return None

    quote_semaphore = asyncio.Semaphore(16)

    async def _quote_from_chain_leg(leg: dict) -> Optional[dict]:
        if not isinstance(leg, dict):
            return None
        token = str(leg.get("token") or "").strip()
        normalized = _normalize_zebu_quote_payload(leg)
        if normalized.get("ltp", 0) > 0:
            return normalized
        if not token:
            return normalized if normalized else None
        async with quote_semaphore:
            try:
                live = await asyncio.wait_for(
                    provider._rest_post(
                        "/GetQuotes",
                        {"exch": exch, "token": token},
                    ),
                    timeout=5.0,
                )
            except Exception:
                return normalized if normalized else None
        if not live or live.get("stat") != "Ok":
            return normalized if normalized else None
        return _normalize_zebu_quote_payload(live)

    leg_quotes = await asyncio.gather(
        *[_quote_from_chain_leg(leg) for leg in chain_values],
        return_exceptions=True,
    )

    grouped: dict[float, dict] = {}
    selected_expiry = None
    expiry_dates: set[str] = set()
    subscription_symbols: list[str] = []

    for leg, q in zip(chain_values, leg_quotes):
        tsym = str(leg.get("tsym") or "").upper().strip()
        token = str(leg.get("token") or "").strip()
        optt = str(leg.get("optt") or "").upper().strip() or _extract_option_side(tsym)
        if optt not in {"CE", "PE"}:
            continue

        strike = None
        try:
            if leg.get("strprc") is not None:
                strike = float(leg.get("strprc"))
        except Exception:
            strike = None
        if strike is None:
            strike = _extract_strike_from_tsym(tsym)
        if strike is None:
            continue

        leg_expiry = _parse_expiry_date(
            str(leg.get("exd") or "")
        ) or _extract_expiry_from_tsym(tsym)
        if leg_expiry:
            expiry_dates.add(leg_expiry)
            if requested_expiry and leg_expiry != requested_expiry:
                continue

        if selected_expiry is None and leg_expiry:
            selected_expiry = leg_expiry

        row = grouped.setdefault(
            strike,
            {
                "strike": strike,
                "expiry": leg_expiry or selected_expiry or requested_expiry,
            },
        )

        quote = q if isinstance(q, dict) else None
        row[optt] = _to_option_side(
            quote,
            optt,
            strike,
            leg_expiry or selected_expiry or requested_expiry or "",
        )

        if tsym:
            subscription_symbols.append(tsym)
        elif token:
            subscription_symbols.append(token)

    rows = [grouped[k] for k in sorted(grouped.keys())]
    if not rows:
        return None

    if not selected_expiry:
        selected_expiry = requested_expiry
    if not selected_expiry and expiry_dates:
        selected_expiry = sorted(expiry_dates)[0]

    stream_unique = list(dict.fromkeys(subscription_symbols))
    if stream_unique:
        try:
            await provider.subscribe(stream_unique)
        except Exception as e:
            logger.debug(f"Option WS subscribe skipped/failed: {e}")
        spot_sym = _SPOT_MAP.get(sym.upper().strip(), "^NSEI")
        _register_options_hot([*stream_unique, spot_sym])

    return {
        "symbol": sym,
        "underlying_price": float(spot),
        "expiry_dates": (
            sorted(expiry_dates)
            if expiry_dates
            else ([selected_expiry] if selected_expiry else [])
        ),
        "selected_expiry": selected_expiry,
        "chain": rows,
        "stream_symbols": stream_unique,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "zebu",
    }


async def _zebu_expiry_dates(symbol: str) -> list[str]:
    sym = symbol.upper().strip()

    provider = broker_session_manager.get_any_session()
    if provider is None:
        try:
            from services.master_session import master_session_service

            if await master_session_service.initialize():
                provider = broker_session_manager.get_any_session()
        except Exception as e:
            logger.debug(f"Master-session recovery failed for options expiry: {e}")

    if provider is None:
        return []

    exch = "BFO" if sym == "SENSEX" else "NFO"

    async def _post(route: str, payload: dict, timeout_sec: float = 6.0):
        try:
            return await asyncio.wait_for(
                provider._rest_post(route, payload), timeout=timeout_sec
            )
        except Exception as e:
            logger.debug(f"Options expiry {route} failed for {sym}: {e}")
            return None

    search = await _post("/SearchScrip", {"exch": exch, "stext": sym}, 6.0)
    if not search or search.get("stat") != "Ok":
        return []

    values = search.get("values") or []
    expiry_dates = set()

    for item in values:
        tsym = str(item.get("tsym") or "").upper().strip()
        if not tsym or sym not in tsym:
            continue

        # Prefer explicit exchange date field when available.
        exd = _parse_expiry_date(str(item.get("exd") or ""))
        if exd:
            expiry_dates.add(exd)
            continue

        # Fallback to tsym parsing for CE/PE/FUT contracts.
        parsed = _extract_expiry_from_tsym(tsym)
        if parsed:
            expiry_dates.add(parsed)

    return sorted(expiry_dates)


@router.get("/chain/{symbol}")
async def option_chain(
    symbol: str,
    expiry: Optional[str] = Query(
        None, description="Expiry date (e.g. 27-Mar-2025). Defaults to nearest."
    ),
    strikes: int = Query(
        20, ge=5, le=50, description="Number of strikes above/below ATM to return."
    ),
    snapshot: int = Query(0, ge=0, le=1, description="Return cached snapshot only"),
    reconcile: int = Query(0, ge=0, le=1, description="Return full live data for background reconcile"),
):
    """
    Live option chain for an index or stock.

        Source:
            1. Zebu live option chain

    Returns calls and puts for each strike around ATM for the selected expiry.
    Example: GET /api/options/chain/NIFTY?expiry=27-Mar-2025&strikes=15
    """
    sym = symbol.upper().strip()
    logger.info(f"Fetching option chain for {sym}")
    requested_expiry = _parse_expiry_date(expiry) if expiry else None
    cache_key = f"options:chain:{sym}:{requested_expiry or 'nearest'}:{int(strikes)}"
    latest_cache_key = f"options:chain:{sym}:latest"

    snapshot_enabled = bool(snapshot) and settings.ENABLE_PROGRESSIVE_OPTIONS
    reconcile_enabled = bool(reconcile) and settings.ENABLE_PROGRESSIVE_OPTIONS

    if snapshot_enabled:
        cached = await _get_redis_options_cache(cache_key)
        if not cached:
            cached = await _get_redis_options_cache(latest_cache_key)

        if cached and isinstance(cached, dict):
            stream_symbols = cached.get("stream_symbols") or []
            return _snapshot_envelope(
                cached,
                stream_symbols,
                cached.get("timestamp"),
                snapshot=True,
            )

        fallback = {
            "symbol": sym,
            "underlying_price": 0,
            "expiry_dates": [],
            "selected_expiry": requested_expiry,
            "chain": [],
            "stream_symbols": [],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "zebu_cache",
        }
        return _snapshot_envelope(
            fallback,
            [],
            fallback.get("timestamp"),
            snapshot=True,
        )

    result = None
    try:
        result = await asyncio.wait_for(
            _zebu_option_chain(sym, expiry, strikes),
            timeout=22.0,
        )
    except Exception as e:
        logger.debug(f"Zebu option chain fetch failed for {sym}: {e}")

    if result and not result.get("source"):
        result["source"] = "zebu"

    if result:
        chain_rows = result.get("chain") or []
        has_live_quotes = any(
            (row.get("CE") or {}).get("ltp", 0) > 0 or (row.get("PE") or {}).get("ltp", 0) > 0
            for row in chain_rows
            if isinstance(row, dict)
        )
        if has_live_quotes:
            await _set_redis_options_cache(cache_key, result, ttl_seconds=45)
            await _set_redis_options_cache(latest_cache_key, result, ttl_seconds=120)
            logger.debug(
                f"Option chain fetched for {sym}: {len(chain_rows)} strikes (live)"
            )
            if reconcile_enabled:
                return _snapshot_envelope(
                    result,
                    result.get("stream_symbols") or [],
                    result.get("timestamp"),
                    snapshot=False,
                )
            return result
        logger.warning(f"Zebu chain for {sym} returned no live LTP — not caching zeros")

    # Do not serve stale zero-quote snapshots — force fresh Zebu or error.
    cached = await _get_redis_options_cache(cache_key)
    if not cached:
        cached = await _get_redis_options_cache(latest_cache_key)
    if cached and isinstance(cached, dict):
        cached_rows = cached.get("chain") or []
        cached_has_ltp = any(
            (row.get("CE") or {}).get("ltp", 0) > 0 or (row.get("PE") or {}).get("ltp", 0) > 0
            for row in cached_rows
            if isinstance(row, dict)
        )
        if cached_has_ltp:
            if not cached.get("source"):
                cached["source"] = "zebu_cache"
            if reconcile_enabled:
                return _snapshot_envelope(
                    cached,
                    cached.get("stream_symbols") or [],
                    cached.get("timestamp"),
                    snapshot=False,
                )
            return cached

    logger.warning(f"Option chain data unavailable from all sources for {sym}")
    raise HTTPException(
        status_code=503,
        detail=(
            f"Option chain data unavailable for {sym}. "
            "Zebu live feed is unavailable right now."
        ),
    )


@router.get("/expiry/{symbol}")
async def expiry_dates(
    symbol: str,
):
    """
    Available option expiry dates for a symbol, sorted nearest-first.

    Example: GET /api/options/expiry/NIFTY
    """
    sym = symbol.upper().strip()
    cache_key = f"options:expiry:{sym}"
    dates = []
    source = None

    try:
        dates = await asyncio.wait_for(_zebu_expiry_dates(sym), timeout=8.0)
        if dates:
            source = "zebu"
    except Exception as e:
        logger.debug(f"Zebu expiry fetch failed for {sym}: {e}")

    if dates:
        await _set_redis_options_cache(
            cache_key,
            {"symbol": sym, "expiry_dates": dates, "source": source},
            ttl_seconds=300,
        )
        return {"symbol": sym, "expiry_dates": dates, "source": source}

    raise HTTPException(
        status_code=503,
        detail=f"No expiry dates available for {sym}.",
    )


@router.post("/promote-hot")
async def promote_options_hot(payload: Optional[dict] = Body(default=None)):
    """
    Promote active option-chain symbols to HOT priority for low-latency WS ticks.
    Called by the options desk after subscribe; does not alter global WS manager logic.
    """
    symbols = (payload or {}).get("symbols") or []
    normalized = [str(s or "").strip().upper() for s in symbols if str(s or "").strip()]
    _register_options_hot(normalized)
    return {"ok": True, "symbols": len(normalized)}


@router.get("/underlyings")
async def supported_underlyings():
    """
    List of index underlyings with live option chains available.
    """
    return {
        "underlyings": [
            {"symbol": "NIFTY", "name": "Nifty 50", "exchange": "NSE"},
            {"symbol": "BANKNIFTY", "name": "Bank Nifty", "exchange": "NSE"},
            {"symbol": "FINNIFTY", "name": "Fin Nifty", "exchange": "NSE"},
            {"symbol": "MIDCPNIFTY", "name": "Midcap Nifty", "exchange": "NSE"},
            {"symbol": "SENSEX", "name": "BSE Sensex", "exchange": "BSE"},
            {"symbol": "NIFTYNXT50", "name": "Nifty Next 50", "exchange": "NSE"},
        ]
    }
