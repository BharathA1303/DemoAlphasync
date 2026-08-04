"""
Options routes — the internal simulation engine-only option chain data.

All live option-chain and expiry data is sourced from active the internal simulation engine data feed sessions.
"""

import logging
import re
import asyncio
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional

from services.market_data import get_system_quote_live_only
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

@router.get("/history")
async def option_history(
    tsym: str = Query(..., description="Option contract trading symbol, e.g. NIFTY26JUL22000CE"),
    token: str = Query("", description="Unused — retained for frontend backward compatibility"),
    exchange: str = Query("NFO", description="NFO/BFO — retained for frontend backward compatibility"),
    period: str = Query("1mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|3y|5y|max)$"),
    interval: str = Query(
        "5m", pattern="^(1m|2m|3m|5m|10m|15m|30m|1h|2h|4h|1d|1wk|1mo)$"
    ),
):
    """
    Options-only historical candles, sourced from the internal simulation engine's EOD price/range
    endpoint for the underlying's current option contract.

    Why this exists:
    - `/api/market/history` resolves symbols through the global symbol
      registry, which can treat derivative contract symbols as equities
      (`.NS`) and fail resolution.
    - The options desk parses expiry/strike/option_type directly out of the
      contract trading symbol (`tsym`) instead.

    This endpoint does NOT change shared market routes, Redis schemas, or WS behavior.
    """
    from services.internal_sim_client import get_configured_client

    trading_symbol = str(tsym or "").strip().upper()
    if not trading_symbol:
        raise HTTPException(status_code=400, detail="tsym is required.")

    option_type = _extract_option_side(trading_symbol)
    strike = _extract_strike_from_tsym(trading_symbol)
    expiry = _extract_expiry_from_tsym(trading_symbol)
    base_symbol = None
    for idx_sym in _SUPPORTED_INDICES:
        if trading_symbol.startswith(idx_sym):
            base_symbol = idx_sym
            break
    if not base_symbol:
        match = re.match(r"^([A-Z&]+)", trading_symbol)
        base_symbol = match.group(1) if match else trading_symbol

    if not option_type or strike is None or not expiry:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse expiry/strike/option_type from tsym={trading_symbol!r}.",
        )

    client = await get_configured_client()
    if not client:
        raise HTTPException(status_code=503, detail="the internal simulation engine data feed is not configured/enabled.")

    days = _HISTORY_PERIOD_DAYS.get(period, 30)
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)

    try:
        from services.market_data import get_historical_data
        candles = await get_historical_data(trading_symbol, period=period, interval=interval)
        if candles:
            return {
                "trading_symbol": trading_symbol,
                "period": period,
                "interval": interval,
                "candles": candles,
            }
    except Exception as e:
        logger.warning(f"Options history fetch failed for {trading_symbol}: {e}")

    return {
        "trading_symbol": trading_symbol,
        "period": period,
        "interval": interval,
        "candles": [],
    }

    candles = [
        {
            "time": row.get("market_timestamp"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
        }
        for row in (rows if isinstance(rows, list) else [])
    ]

    return {"symbol": trading_symbol, "candles": candles, "count": len(candles)}


async def _internal_sim_option_expiries(symbol: str) -> list[str]:
    """Fetch real available option expiry dates for a symbol from the internal simulation engine.

    the internal simulation engine doesn't expose a dedicated "expiries for symbol" endpoint, so
    this resolves the latest eligible EOD record (no expiry/strike/option_type
    filters) and returns its expiry — same single-expiry granularity the
    live chain endpoint below works with (the nearest/current contract).
    """
    from services.internal_sim_client import get_configured_client

    client = await get_configured_client()
    if not client:
        return []

    sym = symbol.upper().strip()
    try:
        record = await client.get_latest_price(exchange="NSE", symbol=sym, segment="OPT")
    except Exception as e:
        logger.debug(f"the internal simulation engine option expiry fetch failed for {sym}: {e}")
        return []

    if not record:
        return []

    expiry = str(record.get("expiry") or "").strip()
    return [expiry] if expiry else []


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


def _normalize_internal_sim_option_record(
    record: Optional[dict], option_type: str, strike: float, expiry: str
) -> Optional[dict]:
    """Map a the internal simulation engine /v1/price EOD record for one option leg to the
    canonical option-side quote shape the frontend expects."""
    if not record:
        return None
    ltp = _safe_float(record.get("close"))
    prev_close = _safe_float(record.get("open"))
    change = ltp - prev_close if ltp > 0 and prev_close > 0 else 0.0
    change_pct = (change / prev_close * 100.0) if prev_close > 0 else 0.0
    return {
        "strike": strike,
        "expiry": expiry,
        "option_type": option_type,
        "tsym": f"{record.get('symbol', '')}",
        "token": "",
        "ltp": ltp,
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "volume": int(record.get("volume") or 0),
        "oi": int(record.get("open_interest") or 0),
        "oi_change": None,
        "bid": 0.0,
        "ask": 0.0,
        "iv": 0.0,
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
    }


async def _internal_sim_option_chain(
    symbol: str, expiry: Optional[str], strikes: int
) -> Optional[dict]:
    """Build a live option chain from real the internal simulation engine EOD option records.

    the internal simulation engine addresses each option leg individually via
    GET /v1/price/NSE/{symbol}?segment=OPT&expiry=&strike=&option_type=CE|PE
    (see api_integration_guide.md Section 1b/4B) rather than exposing a
    bulk option-chain endpoint, so this fans out one request per
    strike/option_type around the current spot price.
    """
    from services.internal_sim_client import get_configured_client

    sym = symbol.upper().strip()
    client = await get_configured_client()
    if not client:
        logger.warning("the internal simulation engine not configured/enabled — no live option chain")
        return None

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

    strike_step = _OPTION_STRIKE_STEP.get(sym, 50)
    center_strike = int(round((spot or 0.0) / strike_step) * strike_step)
    if center_strike <= 0:
        center_strike = strike_step

    requested_expiry = _parse_expiry_date(expiry) if expiry else None
    resolved_expiries = await _internal_sim_option_expiries(sym)
    selected_expiry = requested_expiry or _nearest_expiry(resolved_expiries) or requested_expiry
    if not selected_expiry:
        logger.warning(f"No the internal simulation engine option expiry available for {sym}")
        return None

    width = max(1, int(strikes))
    strike_list = [
        center_strike + (i * strike_step) for i in range(-width, width + 1)
    ]
    strike_list = [s for s in strike_list if s > 0]

    quote_semaphore = asyncio.Semaphore(24)

    async def _fetch_leg(strike: int, option_type: str):
        async with quote_semaphore:
            try:
                record = await asyncio.wait_for(
                    client.get_latest_price(
                        exchange="NSE",
                        symbol=sym,
                        segment="OPT",
                        expiry=selected_expiry,
                        strike=strike,
                        option_type=option_type,
                    ),
                    timeout=5.0,
                )
            except Exception as exc:
                logger.debug(f"the internal simulation engine option leg fetch failed for {sym} {strike}{option_type}: {exc}")
                return strike, option_type, None
        return strike, option_type, _normalize_internal_sim_option_record(
            record, option_type, float(strike), selected_expiry
        )

    tasks = [_fetch_leg(strike, optt) for strike in strike_list for optt in ("CE", "PE")]
    leg_results = await asyncio.gather(*tasks, return_exceptions=True)

    grouped: dict[float, dict] = {}
    for item in leg_results:
        if isinstance(item, Exception):
            continue
        strike, optt, side = item
        row = grouped.setdefault(
            float(strike),
            {"strike": float(strike), "expiry": selected_expiry, "CE": None, "PE": None},
        )
        if side:
            row[optt] = side

    rows = [grouped[k] for k in sorted(grouped.keys())]
    rows = [row for row in rows if row.get("CE") or row.get("PE")]
    if not rows:
        logger.warning(f"No live the internal simulation engine option quotes returned for {sym} {selected_expiry}")
        return None

    return {
        "symbol": sym,
        "underlying_price": float(spot),
        "expiry_dates": resolved_expiries or [selected_expiry],
        "selected_expiry": selected_expiry,
        "chain": rows,
        "stream_symbols": [],
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "tickalpha",
    }


async def _generate_simulated_option_chain(symbol: str, expiry: Optional[str], strikes: int) -> dict:
    """
    Generates a realistic simulated option chain with weekly expiries and strikes.
    """
    import random
    from datetime import datetime, timedelta, timezone
    from market_data.replay.simulation_clock import simulation_clock

    sym = symbol.upper().strip()
    
    # 1. Determine Spot Price
    from data_layer.simulator.brownian_bridge import _resolve_realistic_base_price
    spot_price = _resolve_realistic_base_price(sym, "EQ")

    # Try to get live quote from QuoteCoordinator if available
    try:
        from market.quote_coordinator import quote_coordinator
        lookup_keys = [sym, f"{sym}.NS", f"NSE:EQ:{sym}", f"BSE:EQ:{sym}"]
        if sym in ("NIFTY", "NIFTY50"):
            lookup_keys.extend(["^NSEI", "NSE:IDX:NIFTY50", "NIFTY50.NS"])
        elif sym in ("BANKNIFTY", "NIFTYBANK"):
            lookup_keys.extend(["^NSEBANK", "NSE:IDX:BANKNIFTY", "BANKNIFTY.NS"])
        elif sym == "FINNIFTY":
            lookup_keys.extend(["^CNXFIN", "NSE:IDX:FINNIFTY"])
        elif sym == "SENSEX":
            lookup_keys.extend(["^BSESN", "BSE:IDX:SENSEX"])

        for lookup_key in lookup_keys:
            quote = await quote_coordinator.get_quote(lookup_key)
            if quote and (quote.get("price") or quote.get("ltp")):
                p = float(quote.get("price") or quote.get("ltp"))
                if p > 0:
                    spot_price = p
                    break
    except Exception:
        pass

    # 2. Determine Expiry Dates (next 4 Thursdays)
    now = simulation_clock.now()
    expiry_dates = []
    
    # Find next Thursdays
    current = now
    while len(expiry_dates) < 4:
        current += timedelta(days=1)
        if current.weekday() == 3:  # Thursday
            # Format as DD-MMM-YYYY (e.g. 02-Jul-2026)
            expiry_dates.append(current.strftime("%d-%b-%Y"))

    selected_expiry = expiry if expiry else expiry_dates[0]

    # 3. Determine Strike Price Parameters
    strike_step = 50
    if sym == "BANKNIFTY" or sym == "SENSEX":
        strike_step = 100
    elif sym == "NIFTY" or sym == "FINNIFTY":
        strike_step = 50
    elif spot_price > 5000:
        strike_step = 100
    elif spot_price > 1000:
        strike_step = 50
    elif spot_price > 500:
        strike_step = 10
    else:
        strike_step = 5

    center_strike = int(round(spot_price / strike_step) * strike_step)
    
    # Generate strikes around ATM
    chain = []
    stream_symbols = []
    
    # Render option contracts
    # E.g. NIFTY26JUL22000CE
    # Format expiry for contract symbol (e.g. 26JUL)
    try:
        exp_dt = datetime.strptime(selected_expiry, "%d-%b-%Y")
        expiry_sym_str = exp_dt.strftime("%y%b").upper() # e.g. 26JUL
        # Option contract symbol format: NIFTY26JUL22000CE
    except Exception:
        expiry_sym_str = "26JUL"

    for i in range(-strikes, strikes + 1):
        strike = center_strike + (i * strike_step)
        if strike <= 0:
            continue

        ce_symbol = f"{sym}{expiry_sym_str}{strike}CE"
        pe_symbol = f"{sym}{expiry_sym_str}{strike}PE"
        
        # Calculate theoretical prices (simple intrinsic + time value)
        dist_from_atm = abs(spot_price - strike)
        time_value = max(5.0, 150.0 - (dist_from_atm * 0.8)) if sym in ("NIFTY", "BANKNIFTY", "SENSEX") else max(1.0, 25.0 - (dist_from_atm * 0.8))
        
        ce_intrinsic = max(0.0, spot_price - strike)
        pe_intrinsic = max(0.0, strike - spot_price)
        
        ce_ltp = round(ce_intrinsic + time_value, 2)
        pe_ltp = round(pe_intrinsic + time_value, 2)
        
        # Bid/Ask spreads
        ce_bid = round(ce_ltp - 0.15, 2)
        ce_ask = round(ce_ltp + 0.15, 2)
        pe_bid = round(pe_ltp - 0.15, 2)
        pe_ask = round(pe_ltp + 0.15, 2)

        # Build row
        row = {
            "strike": strike,
            "CE": {
                "symbol": ce_symbol,
                "token": ce_symbol,
                "ltp": ce_ltp,
                "price": ce_ltp,
                "change": round(random.uniform(-5, 5), 2),
                "change_percent": round(random.uniform(-3, 3), 2),
                "oi": random.randint(10000, 2500000),
                "volume": random.randint(5000, 1000000),
                "bid_price": ce_bid,
                "ask_price": ce_ask,
                "bid_qty": random.randint(100, 5000),
                "ask_qty": random.randint(100, 5000),
                "exchange": "NFO",
            },
            "PE": {
                "symbol": pe_symbol,
                "token": pe_symbol,
                "ltp": pe_ltp,
                "price": pe_ltp,
                "change": round(random.uniform(-5, 5), 2),
                "change_percent": round(random.uniform(-3, 3), 2),
                "oi": random.randint(10000, 2500000),
                "volume": random.randint(5000, 1000000),
                "bid_price": pe_bid,
                "ask_price": pe_ask,
                "bid_qty": random.randint(100, 5000),
                "ask_qty": random.randint(100, 5000),
                "exchange": "NFO",
            }
        }
        
        chain.append(row)
        stream_symbols.extend([ce_symbol, pe_symbol])

    return {
        "symbol": sym,
        "underlying_price": spot_price,
        "expiry_dates": expiry_dates,
        "selected_expiry": selected_expiry,
        "chain": chain,
        "stream_symbols": stream_symbols,
        "timestamp": now.isoformat() + "Z",
        "source": "simulated",
    }


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
            1. the internal simulation engine live option chain

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
            "source": "tickalpha_cache",
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
            _internal_sim_option_chain(sym, expiry, strikes),
            timeout=22.0,
        )
    except Exception as e:
        logger.debug(f"the internal simulation engine option chain fetch failed for {sym}: {e}")

    # Fallback to simulated option chain in simulation mode or if live fetch failed
    if not result:
        logger.info(f"Generating simulated option chain for {sym}")
        result = await _generate_simulated_option_chain(sym, expiry, strikes)

    if result:
        result["source"] = "tickalpha"


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
        logger.warning(f"the internal simulation engine chain for {sym} returned no live LTP — not caching zeros")

    # Do not serve stale zero-quote snapshots — force a fresh the internal simulation engine fetch or error.
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
                cached["source"] = "tickalpha_cache"
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
            "The internal simulation engine data feed is not currently connected."
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
        dates = await asyncio.wait_for(_internal_sim_option_expiries(sym), timeout=8.0)
        if dates:
            source = "tickalpha"
    except Exception as e:
        logger.debug(f"Options expiry fetch failed for {sym}: {e}")

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
