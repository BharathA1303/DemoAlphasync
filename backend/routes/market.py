import logging
import asyncio
import time
from datetime import datetime, timezone, timedelta
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Query, Depends
from typing import Optional
from services import market_data
from routes.auth import get_current_user, get_current_user_optional
from models.user import User
from engines.market_session import market_session
from config.settings import settings
from cache.smart_cache import (
    quote_cache,
    history_cache,
    indices_cache,
    ticker_cache,
    search_cache,
)

router = APIRouter(prefix="/api/market", tags=["Market Data"])
logger = logging.getLogger(__name__)

_SESSION_RECOVER_COOLDOWN_SECONDS = 20
_last_session_recover_attempt = 0.0
_session_recover_lock = asyncio.Lock()

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


def _snapshot_epoch_ms(value) -> int:
    now_ms = int(time.time() * 1000)
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
    now_ms = int(time.time() * 1000)
    return {
        "snapshot": snapshot,
        "snapshot_ts": ts_ms,
        "stale_ms": max(0, now_ms - ts_ms),
        "stream_symbols": stream_symbols or [],
        "data": data or {},
    }


def _aggregate_calendar_candles(candles: list[dict], interval: str) -> list[dict]:
    """Aggregate daily candles into calendar week/month candles."""
    if interval not in {"1wk", "1mo"}:
        return candles or []
    if not candles:
        return []

    aggregated: list[dict] = []
    current_key = None
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

        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        if interval == "1wk":
            iso_year, iso_week, _ = dt.isocalendar()
            key = (iso_year, iso_week)
            bucket_start = dt - timedelta(
                days=dt.weekday(),
                hours=dt.hour,
                minutes=dt.minute,
                seconds=dt.second,
                microseconds=dt.microsecond,
            )
        else:
            key = (dt.year, dt.month)
            bucket_start = dt.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

        bucket_ts = int(bucket_start.timestamp())

        if current_key is None or key != current_key:
            if current is not None:
                aggregated.append(current)
            current_key = key
            current = {
                "time": bucket_ts,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(cl, 2),
                "volume": max(0, v),
            }
            continue

        current["high"] = round(max(float(current["high"]), h, o, cl, l), 2)
        current["low"] = round(min(float(current["low"]), l, o, cl, h), 2)
        current["close"] = round(cl, 2)
        current["volume"] = int(current.get("volume", 0)) + max(0, v)

    if current is not None:
        aggregated.append(current)

    return aggregated


def _minimum_history_candles(period: str, interval: str, is_intraday: bool) -> int:
    """Dynamic minimum-candle threshold — lowered to allow newly subscribed symbols."""
    if is_intraday:
        return 5

    days = _PERIOD_DAYS.get(period, 30)
    if interval == "1wk":
        expected = max(1, days // 7)
        return max(2, int(expected * 0.25))
    if interval == "1mo":
        expected = max(1, days // 30)
        return max(1, int(expected * 0.25))

    expected = max(1, days)
    return max(5, int(expected * 0.15))


def _is_fresh_cached_quote(quote: object) -> bool:
    if not isinstance(quote, dict):
        return False
    if quote.get("price") is None:
        return False
    if not quote.get("timestamp"):
        return False
    status = str(quote.get("market_status") or "").lower()
    # Frozen-market quotes are always considered valid snapshots.
    if status in {
        "pre_market",
        "closing",
        "after_market",
        "closed",
        "holiday",
        "weekend",
        "demo",
    }:
        return True
    return not market_data._is_quote_stale(quote)


def _build_market_unavailable_detail() -> dict:
    from services.broker_session import broker_session_manager
    from services.master_session import master_session_service

    master = master_session_service.get_status()
    active_sessions = broker_session_manager.session_count()

    reason = master.get("last_error")
    if not reason:
        if not master.get("configured"):
            reason = "Zebu master credentials are not configured"
        elif active_sessions == 0:
            reason = "No active Zebu session"
        else:
            reason = "Zebu provider temporarily unavailable"

    return {
        "reason": reason,
        "market_state": market_session.get_current_state().value,
        "active_sessions": active_sessions,
        "master_session": {
            "active": master.get("active"),
            "configured": master.get("configured"),
            "missing": master.get("missing") or [],
            "last_error": master.get("last_error"),
        },
    }


async def _try_recover_any_session() -> bool:
    """Try to recover a Zebu session with cooldown to avoid request storms."""
    global _last_session_recover_attempt

    from services.broker_session import broker_session_manager

    if broker_session_manager.get_any_session() is not None:
        return True

    now = time.time()
    if (now - _last_session_recover_attempt) < _SESSION_RECOVER_COOLDOWN_SECONDS:
        return False

    async with _session_recover_lock:
        if broker_session_manager.get_any_session() is not None:
            return True

        now = time.time()
        if (now - _last_session_recover_attempt) < _SESSION_RECOVER_COOLDOWN_SECONDS:
            return False

        _last_session_recover_attempt = now
        try:
            from services.master_session import master_session_service

            ok = await master_session_service.initialize()
            if ok and broker_session_manager.get_any_session() is not None:
                logger.info("Recovered Zebu session via master initialize")
                return True
        except Exception as e:
            logger.debug(f"Session recovery attempt failed: {e}")

    return broker_session_manager.get_any_session() is not None


@router.get("/session")
async def get_market_session():
    """Market session info — public, no auth required."""
    return market_session.get_session_info()


@router.get("/quote/{symbol}")
async def get_quote(
    symbol: str, user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Get quote for a symbol.
    SmartCache (in-memory) → Redis → Zebu provider.
    """
    fmt_symbol = market_data._format_symbol(symbol)
    quote = None
    try:
        quote = await market_data.get_quote_safe(fmt_symbol, user.id if user else "")
        if quote:
            quote = market_data._normalize_quote(quote)
    except Exception as e:
        logger.warning(f"Quote fetch failed for {fmt_symbol}: {e}")
    if _is_fresh_cached_quote(quote):
        return quote

    from services.broker_session import broker_session_manager

    if broker_session_manager.get_any_session() is None:
        recovered = await _try_recover_any_session()
        if recovered:
            try:
                retried = await market_data.get_quote_safe(
                    fmt_symbol, user.id if user else ""
                )
                retried = market_data._normalize_quote(retried) if retried else None
                if _is_fresh_cached_quote(retried):
                    return retried
            except Exception:
                pass

        state = market_session.get_current_state().value
        detail = _build_market_unavailable_detail()
        return {
            "symbol": fmt_symbol,
            "name": fmt_symbol.replace(".NS", "").replace(".BO", ""),
            "price": None,
            "change": None,
            "change_percent": None,
            "prev_close": None,
            "open": None,
            "high": None,
            "low": None,
            "volume": None,
            "timestamp": int(time.time()),
            "available": False,
            "unavailable": {
                **detail,
                "recovering": state == "open" and not recovered,
            },
        }

    detail = _build_market_unavailable_detail()
    return {
        "symbol": fmt_symbol,
        "name": fmt_symbol.replace(".NS", "").replace(".BO", ""),
        "price": None,
        "change": None,
        "change_percent": None,
        "prev_close": None,
        "open": None,
        "high": None,
        "low": None,
        "volume": None,
        "timestamp": int(time.time()),
        "available": False,
        "unavailable": {
            **detail,
            "recovering": market_session.get_current_state().value == "open",
        },
    }


@router.get("/search")
async def search_stocks(q: str = Query(..., min_length=1)):
    """Search is provider-independent — no auth required. Cached 5 min."""
    cache_key = f"search:{q.upper()}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached

    results = await market_data.search_stocks(q)
    response = {"results": results}
    search_cache.set(cache_key, response, ttl=300)
    return response


@router.get("/history/{symbol}")
async def get_history(
    symbol: str,
    period: str = Query("1mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|3y|5y|max)$"),
    interval: str = Query(
        "1d", pattern="^(1m|2m|3m|5m|10m|15m|30m|1h|2h|4h|1d|1wk|1mo)$"
    ),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Historical OHLCV — SmartCache → Redis → Zebu provider only."""
    fmt_symbol = market_data._format_symbol(symbol)
    is_commodity = market_data.is_commodity_symbol(fmt_symbol)
    intraday_intervals = {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "4h"}
    is_intraday = interval in intraday_intervals

    cache_key = f"hist:{fmt_symbol}:{period}:{interval}"
    try:
        if is_commodity:
            data = await market_data.get_historical_data_live_only(
                fmt_symbol,
                period,
                interval,
                user_id=user.id if user else None,
            )
        else:
            data = await market_data.get_historical_data(
                fmt_symbol,
                period,
                interval,
                user_id=user.id if user else None,
            )
        data = market_data.normalize_history_candles(data)
        data = _aggregate_calendar_candles(data, interval)
    except Exception as e:
        logger.warning(f"get_historical_data failed for {fmt_symbol}: {e}")
        data = []

    min_required = _minimum_history_candles(period, interval, is_intraday)
    if len(data) < min_required:
        # Keep partial intraday history so charts render for newly subscribed symbols.
        if is_intraday and len(data) >= 2:
            logger.debug(
                f"Using partial intraday history for {fmt_symbol} "
                f"({len(data)} candles, preferred min {min_required})"
            )
        else:
            logger.debug(
                f"Rejected short history payload for {fmt_symbol} "
                f"({len(data)} candles, min {min_required})"
            )
            data = []

    # Write to Redis for next caller (skip zero-volume index payloads — they poison charts).
    if data:
        skip_cache = (
            market_data._is_index_symbol(fmt_symbol)
            and is_intraday
            and not market_data._history_has_volume(data)
        )
        if not skip_cache:
            try:
                from cache.redis_client import set_history as redis_set_history

                await redis_set_history(fmt_symbol, period, interval, data)
            except Exception:
                pass
        if is_intraday:
            await _persist_history_ltp_snapshot(fmt_symbol, data)

    response = {"symbol": fmt_symbol, "candles": data, "count": len(data)}
    if not data:
        response["unavailable"] = _build_market_unavailable_detail()
    return response


def _closed_market_response_metadata() -> dict:
    """Response envelope for ticker/batch/indices market-session context."""
    from engines.market_session import market_session

    state = market_session.get_current_state()
    frozen = state.value != "open"
    meta = {
        "market_state": state.value.upper(),
        "frozen": frozen,
        "official": frozen,
    }
    meta["source"] = "official_eod_close" if frozen else "live"
    return meta


async def _persist_history_ltp_snapshot(symbol: str, candles: list[dict]) -> None:
    """Write the latest chart candle close into Redis closed-session price snapshots."""
    if market_session.get_current_state().value == "open" or not candles:
        return

    last = candles[-1]
    try:
        close_price = round(float(last.get("close")), 2)
    except (TypeError, ValueError):
        return
    if close_price <= 0:
        return

    try:
        ts = int(float(last.get("time") or time.time()))
    except (TypeError, ValueError):
        ts = int(time.time())

    # Derive prev_close / change / change_percent from the existing Redis authoritative
    # close so the intraday snapshot doesn't erase correctly computed EOD change data.
    prev_close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    try:
        from cache.redis_client import get_last_price as _redis_get_last_price

        existing = await _redis_get_last_price(symbol)
        if existing:
            _pc = existing.get("prev_close")
            if _pc is not None:
                try:
                    _pf = round(float(_pc), 2)
                    if _pf > 0:
                        prev_close = _pf
                        change = round(close_price - prev_close, 2)
                        change_percent = round((change / prev_close) * 100.0, 2)
                except (TypeError, ValueError):
                    pass
            # Carry over existing change values when prev_close is unavailable
            # (e.g. first boot before daily candles are cached in Redis).
            if prev_close is None:
                _ec = existing.get("change")
                _ep = existing.get("change_percent")
                if _ec is not None and _ep is not None:
                    try:
                        change = round(float(_ec), 2)
                        change_percent = round(float(_ep), 2)
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass

    quote = {
        "symbol": symbol,
        "name": symbol.replace(".NS", "").replace(".BO", "").replace("^", ""),
        "price": close_price,
        "ltp": close_price,
        "lp": close_price,
        "last_price": close_price,
        "change": change,
        "change_percent": change_percent,
        "prev_close": prev_close,
        "open": last.get("open"),
        "high": last.get("high"),
        "low": last.get("low"),
        "volume": last.get("volume") or 0,
        "timestamp": ts,
        "source": "history_snapshot",
        "market_session": "closed",
        "official_close": close_price,
        "official_close_timestamp": ts,
        "official": True,
        "frozen": True,
    }

    try:
        from cache.redis_client import set_authoritative_close

        enriched = await market_data._enrich_frozen_quote_day_change(symbol, quote)
        await set_authoritative_close(symbol, enriched or quote)
    except Exception as e:
        logger.debug(f"History LTP snapshot persist failed for {symbol}: {e}")


_OVERVIEW_FALLBACK = {
    "indices": [],
    "gainers": [],
    "losers": [],
    "sectors": [],
    "breadth": {"advances": 0, "declines": 0, "unchanged": 0, "total": 2854},
    "sentiment": {"score": 50, "label": "Neutral", "description": "Balanced market forces with no clear direction."}
}


@router.get("/overview")
async def get_market_overview(user: Optional[User] = Depends(get_current_user_optional)):
    """
    Get consolidated market overview data for the premium dashboard.
    """
    try:
        data = await asyncio.wait_for(
            market_data.get_market_overview_data(user.id if user else None),
            timeout=12.0,
        )
        return data
    except asyncio.TimeoutError:
        logger.warning("Market overview timed out after 12s, returning fallback")
        return _OVERVIEW_FALLBACK
    except Exception as e:
        logger.exception(f"Error fetching market overview data: {e}")
        return _OVERVIEW_FALLBACK


@router.get("/indices")
async def get_indices(user: Optional[User] = Depends(get_current_user_optional)):
    """
    Index quotes — official EOD close when market closed; live when open.
    """
    # 1. Try to read from cache first for fast response and reliability!
    cached = None
    try:
        from cache.redis_client import get_indices as redis_get_indices
        cached = await redis_get_indices()
    except Exception as e:
        logger.debug(f"Redis get_indices failed: {e}")

    if cached:
        # Enrich cached index quotes with advances/declines stats before returning!
        enriched_cached = []
        for idx in cached:
            if isinstance(idx, dict):
                try:
                    from services.market_data import get_index_advances_declines
                    stats = await get_index_advances_declines(
                        idx.get("symbol"),
                        price=idx.get("price"),
                        chg_pct=idx.get("change_percent")
                    )
                    idx.update(stats)
                except Exception:
                    pass
                enriched_cached.append(idx)
        return {"indices": enriched_cached or cached, **_closed_market_response_metadata()}

    # 2. Fall back to live fetch if not in Redis
    try:
        indices = await asyncio.wait_for(
            market_data.get_indices(user_id=user.id if user else None), timeout=2.5
        )
        if indices:
            response = {"indices": indices, **_closed_market_response_metadata()}
            # Also cache it in Redis so next requests are fast
            try:
                from cache.redis_client import set_indices as redis_set_indices
                await redis_set_indices(indices)
            except Exception:
                pass
            return response
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug(f"Indices fetch timeout/error: {e}")

    from services.broker_session import broker_session_manager
    response = {"indices": [], **_closed_market_response_metadata()}
    if broker_session_manager.get_any_session() is None:
        response["unavailable"] = _build_market_unavailable_detail()
    return response


@router.get("/ticker")
async def get_ticker(user: Optional[User] = Depends(get_current_user_optional)):
    """
    Ticker bar — SmartCache → Redis → Zebu provider.
    """
    try:
        items = await asyncio.wait_for(
            market_data.get_ticker_data(user_id=user.id if user else None), timeout=3.0
        )
        response = {"items": items, **_closed_market_response_metadata()}
        if not items:
            response["unavailable"] = _build_market_unavailable_detail()
        return response
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug(f"/api/market/ticker timeout/error (provider): {e}")
        recovered = await _try_recover_any_session()
        if recovered:
            try:
                items = await asyncio.wait_for(
                    market_data.get_ticker_data(user_id=user.id if user else None),
                    timeout=2.5,
                )
                if items:
                    return {"items": items, "source": "recovered_session"}
            except Exception:
                pass

        detail = _build_market_unavailable_detail()
        return {
            "items": [],
            "unavailable": {
                **detail,
                "recovering": market_session.get_current_state().value == "open"
                and not recovered,
            },
        }


@router.get("/ticker/public")
async def get_public_ticker():
    """
    Public ticker — NO auth required. SmartCache → Redis → Zebu provider.
    """
    items = await market_data.get_public_ticker_data()
    response = {"items": items}
    if not items:
        response["unavailable"] = _build_market_unavailable_detail()
    return response


@router.get("/popular")
async def get_popular_stocks():
    return {"stocks": market_data.POPULAR_INDIAN_STOCKS}


@router.get("/commodities")
async def get_commodities(
    user: Optional[User] = Depends(get_current_user_optional),
    snapshot: int = Query(0, ge=0, le=1, description="Return cached snapshot only"),
    reconcile: int = Query(0, ge=0, le=1, description="Return full live data for background reconcile"),
):
    """Get commodity quotes for all popular commodities — public, no auth required."""
    snapshot_enabled = bool(snapshot) and settings.ENABLE_PROGRESSIVE_COMMODITIES
    reconcile_enabled = bool(reconcile) and settings.ENABLE_PROGRESSIVE_COMMODITIES

    if snapshot_enabled:
        try:
            from cache.redis_client import get_redis

            redis = await get_redis()
            cached = await redis.get_commodities_with_source()
        except Exception:
            cached = None

        items = (cached or {}).get("items") or []
        source = (cached or {}).get("source")
        stream_symbols = [
            str(item.get("symbol") or "").upper().strip()
            for item in items
            if item.get("symbol")
        ]
        snapshot_ts = None
        if items:
            snapshot_ts = max(
                (_snapshot_epoch_ms(item.get("timestamp")) for item in items),
                default=None,
            )
        payload = {"commodities": items, "source": source}
        return _snapshot_envelope(payload, stream_symbols, snapshot_ts, snapshot=True)

    # Prefer fresh live fetch, but bound latency so UI does not hang.
    try:
        quotes = await asyncio.wait_for(
            market_data.get_commodity_quotes(str(user.id) if user else None),
            timeout=25.0,
        )
    except Exception as e:
        logger.debug(f"Live commodity fetch timed out/failed: {e}")
        quotes = []

    if quotes:
        source = str((quotes[0] or {}).get("source") or "live")
        payload = {"commodities": quotes, "source": source}
        if reconcile_enabled:
            stream_symbols = [
                str(item.get("symbol") or "").upper().strip()
                for item in quotes
                if item.get("symbol")
            ]
            snapshot_ts = max(
                (_snapshot_epoch_ms(item.get("timestamp")) for item in quotes),
                default=None,
            )
            return _snapshot_envelope(
                payload,
                stream_symbols,
                snapshot_ts,
                snapshot=False,
            )
        return payload

    response = {"commodities": [], "source": None}
    response["unavailable"] = _build_market_unavailable_detail()
    if reconcile_enabled:
        return _snapshot_envelope(response, [], None, snapshot=False)
    return response


@router.get("/commodities/search")
async def search_commodities(q: str = Query(..., min_length=1)):
    """Search commodities by name, symbol, or category."""
    results = await market_data.search_commodities(q)
    return {"results": results}


@router.get("/batch")
async def batch_quotes(
    symbols: str = Query(..., description="Comma-separated symbols"),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Batch quote endpoint — OPTIMIZED to return quickly.

    Request timeout: 5 seconds (prevents hanging)
    Redis batch pipeline: Single round-trip instead of per-symbol loops
    Parallel market_data lookup: Zebu provider batch only
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"quotes": {}}

    def _normalize_symbol(sym: str) -> str:
        """Normalize symbol: keep exchange suffix, default to .NS if absent."""
        if sym.startswith("^") or sym.endswith(".NS") or sym.endswith(".BO"):
            return sym
        return f"{sym}.NS"

    def _base_symbol(sym: str) -> str:
        """Strip exchange suffix from the end only."""
        if sym.endswith(".NS"):
            return sym[:-3]
        if sym.endswith(".BO"):
            return sym[:-3]
        return sym

    def _get_symbol_variants(sym: str) -> tuple[str, str]:
        """Return (normalized_symbol, base_symbol) for lookup."""
        normalized = _normalize_symbol(sym)
        base = _base_symbol(normalized)
        return (normalized, base)

    def _upsert_quote(target: dict, sym: str, quote: dict) -> None:
        """Store quote under normalized and base symbol."""
        if not quote:
            return
        normalized, base = _get_symbol_variants(sym)
        target[normalized] = quote
        target[base] = quote

    def _has_quote(target: dict, sym: str) -> bool:
        """Check if quote exists for this symbol (any variant)."""
        normalized, base = _get_symbol_variants(sym)
        return (normalized in target and target[normalized]) or (base in target and target[base])

    # Normalize all symbols first
    try:
        normalized_symbols = [_normalize_symbol(s) for s in symbol_list]
        results = {}

        try:
            live = await asyncio.wait_for(
                market_data.get_batch_quotes(
                    normalized_symbols,
                    user_id=user.id if user else None,
                ),
                timeout=3.0,
            )
            for sym, quote in (live or {}).items():
                _upsert_quote(results, sym, quote)
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Batch quotes timeout/error: {e}")

        # Normalize all final quotes to standard format before returning
        final_quotes = {}
        for sym, q in results.items():
            if q:
                normalized = market_data._normalize_quote(q)
                if normalized:
                    final_quotes[sym] = normalized
        response = {"quotes": final_quotes, **_closed_market_response_metadata()}
        if not final_quotes:
            response["unavailable"] = _build_market_unavailable_detail()
        return response
    except Exception as e:
        # Catch-all to avoid uncaught exceptions causing HTTP 500 responses.
        logger.exception(f"Unexpected error in /api/market/batch: {e}")
        resp = {"quotes": {}, **_closed_market_response_metadata()}
        resp["unavailable"] = _build_market_unavailable_detail()
        return resp


@router.get("/provider/health")
async def provider_health(user: User = Depends(get_current_user)):
    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_session(user.id)
    if not provider:
        return {
            "status": "not_connected",
            "message": "No personal broker connected — using master session",
        }
    try:
        health = await provider.health()
        return health.to_dict()
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/system/diagnostics")
async def system_diagnostics(user: Optional[User] = Depends(get_current_user_optional)):
    """
    Diagnostic endpoint to check data availability and connectivity.
    Helps troubleshoot why futures/options/commodities data might be unavailable.
    """
    from services.broker_session import broker_session_manager
    from services.master_session import master_session_service
    from services import futures_service

    # Check master session
    master_status = master_session_service.get_status()

    # Check user session
    user_session = None
    if user:
        try:
            user_session = broker_session_manager.get_session(user.id)
        except Exception:
            pass

    # Check general session availability
    any_session = broker_session_manager.get_any_session() is not None

    # Check futures contracts
    total_futures = (
        sum(len(v) for v in futures_service._futures_contracts.values())
        if futures_service._futures_contracts_loaded
        else 0
    )

    options_live_available = any_session or master_status.get("active", False)

    return {
        "timestamp": int(time.time()),
        "market_session": market_session.get_current_state().value,
        "data_sources": {
            "master_zebu": {
                "active": master_status.get("active", False),
                "configured": master_status.get("configured", False),
                "missing_config": master_status.get("missing", []),
                "last_error": master_status.get("last_error"),
            },
            "user_broker": {
                "connected": user_session is not None if user else False,
                "user_id": str(user.id)[:8] if user else None,
            },
            "any_broker": {
                "available": any_session,
                "active_sessions": broker_session_manager.session_count(),
            },
        },
        "availability": {
            "futures": {
                "contracts_loaded": futures_service._futures_contracts_loaded,
                "total_contracts": total_futures,
                "status": "enabled" if total_futures > 0 else "unavailable",
            },
            "options": {
                "source": "zebu",
                "broker_available": options_live_available,
                "status": "enabled" if options_live_available else "unavailable",
            },
            "commodities": {
                "broker_required": False,
                "broker_available": any_session or master_status.get("active", False),
                "fallback": "cache_only",
                "status": "enabled",
            },
        },
        "recommendations": _generate_recommendations(
            master_status, user_session, any_session, total_futures
        ),
    }


def _generate_recommendations(
    master_status, user_session, any_session, total_futures
) -> list:
    """Generate actionable recommendations based on diagnostic results."""
    recs = []

    if not any_session and not master_status.get("active"):
        recs.append(
            {
                "severity": "warning",
                "issue": "No active broker session for live market data",
                "recommendation": "Either connect a broker account (OAuth) or configure ZEBU_MASTER_USER_ID in .env",
            }
        )

    if master_status.get("missing"):
        recs.append(
            {
                "severity": "info",
                "issue": f"Master session not configured",
                "recommendation": f"Set these environment variables for live data: {', '.join(master_status['missing'])}",
            }
        )

    if total_futures == 0:
        recs.append(
            {
                "severity": "warning",
                "issue": "No futures contracts available",
                "recommendation": "Check Zebu CDN access or verify API credentials",
            }
        )

    if not (any_session or master_status.get("active")):
        recs.append(
            {
                "severity": "warning",
                "issue": "No active Zebu session for options",
                "recommendation": "Connect broker or restore master Zebu session to receive live options data",
            }
        )

    if not recs:
        recs.append(
            {
                "severity": "info",
                "issue": "All systems operational",
                "recommendation": "Futures, Options, and Commodities data sources are available",
            }
        )

    return recs
