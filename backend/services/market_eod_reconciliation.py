"""
Official EOD close reconciliation — replaces stale websocket ticks after market close.

At OPEN → CLOSED transition, fetches Zebu EOD/historical closes and writes authoritative
Redis snapshots (last_price, price, snapshot:price) with source=official_eod_close.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from engines.market_session import MarketState, market_session
from services.market_data import (
    INDIAN_INDICES,
    POPULAR_COMMODITIES,
    POPULAR_INDIAN_STOCKS,
    _format_symbol,
    normalize_history_candles,
)

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

OFFICIAL_EOD_SOURCE = "official_eod_close"

# Live websocket ticks older than this after close are never served as display quotes.
STALE_LIVE_WS_MAX_AGE_CLOSED_SECONDS = 30 * 60

_RECONCILE_LOCK = asyncio.Lock()
_last_reconciled_ist_date: Optional[str] = None
_reconciliation_inflight: Optional[asyncio.Task] = None


def get_reconciliation_ist_date() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def is_official_eod_quote(quote: Any) -> bool:
    if not isinstance(quote, Mapping):
        return False
    src = str(quote.get("source") or "").lower()
    return src == OFFICIAL_EOD_SOURCE or bool(quote.get("official"))


def is_rejected_live_tick_for_closed_market(quote: Any) -> bool:
    """Stale live_ws ticks must never be primary display quotes when market is closed."""
    if not isinstance(quote, Mapping):
        return True

    if is_official_eod_quote(quote):
        return False

    src = str(quote.get("source") or "").lower()
    if src in ("history_snapshot", "eod"):
        return False

    live_sources = {
        "live_ws",
        "live",
        "live_zebu",
        "zebu",
        "market_data_worker",
        "poll",
        "worker",
        "rest",
        "provider",
        "frozen",
    }
    if src not in live_sources and not src.startswith("live"):
        return False

    state = market_session.get_current_state()
    if state == MarketState.OPEN:
        return False

    from services.market_data import _parse_quote_timestamp

    ts = _parse_quote_timestamp(
        quote.get("timestamp")
        or quote.get("last_trade_time")
        or quote.get("exchange_timestamp")
        or quote.get("ft")
    )
    if ts is None:
        return True

    age = time.time() - ts
    if age > STALE_LIVE_WS_MAX_AGE_CLOSED_SECONDS:
        logger.debug(
            "[STALE LIVE TICK REJECTED] %s source=%s age=%.0fs",
            quote.get("symbol"),
            src,
            age,
        )
        return True

    # Any live-derived tick during non-open session is not authoritative for display.
    if state in (
        MarketState.CLOSED,
        MarketState.CLOSING,
        MarketState.AFTER_MARKET,
        MarketState.WEEKEND,
        MarketState.HOLIDAY,
    ):
        logger.debug(
            "[STALE LIVE TICK REJECTED] %s source=%s session=%s",
            quote.get("symbol"),
            src,
            state.value,
        )
        return True

    return False


def map_session_phase(state: MarketState) -> str:
    """Map NSE state to transition phases used by the session engine."""
    if state == MarketState.OPEN:
        return "OPEN"
    if state in (MarketState.CLOSING, MarketState.AFTER_MARKET):
        return "PRE_CLOSE"
    if state in (MarketState.CLOSED, MarketState.WEEKEND, MarketState.HOLIDAY):
        return "CLOSED"
    return "POST_CLOSE"


async def collect_active_symbols() -> set[str]:
    """Symbols that need official close reconciliation."""
    symbols: set[str] = set()

    for stock in POPULAR_INDIAN_STOCKS:
        symbols.add(_format_symbol(stock["symbol"]))
    for idx in INDIAN_INDICES:
        symbols.add(_format_symbol(idx["symbol"]))
    for item in POPULAR_COMMODITIES:
        symbols.add(_format_symbol(item.get("symbol") or ""))

    try:
        from cache.redis_client import get_redis

        cache = await get_redis()
        if cache.is_connected:
            symbols.update(await cache.get_subscriptions())
            all_prices = await cache.get_all_prices()
            symbols.update(all_prices.keys())
    except Exception as e:
        logger.debug(f"[EOD RECONCILIATION] Redis symbol collect failed: {e}")

    try:
        from workers.market_worker import market_data_worker

        for sym in market_data_worker._subscribed_symbols:
            symbols.add(_format_symbol(sym))
    except Exception as e:
        logger.debug(f"[EOD RECONCILIATION] worker symbols collect failed: {e}")

    try:
        from market.quote_coordinator import quote_coordinator

        symbols.update(quote_coordinator.get_tracked_symbols())
    except Exception as e:
        logger.debug(f"[EOD RECONCILIATION] coordinator symbols collect failed: {e}")

    return {s for s in symbols if s}


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed > 0 else None


def _build_quote_from_candles(
    symbol: str,
    candles: list[dict],
) -> Optional[dict]:
    normalized = normalize_history_candles(candles or [])
    if not normalized:
        return None

    last = normalized[-1]
    close = _safe_float(last.get("close"))
    if close is None:
        return None

    prev_close = None
    if len(normalized) >= 2:
        prev_close = _safe_float(normalized[-2].get("close"))

    change = None
    change_percent = None
    if prev_close:
        change = round(close - prev_close, 2)
        change_percent = round((change / prev_close) * 100.0, 2)

    ts = last.get("time")
    if ts is not None:
        try:
            ts = int(float(ts))
        except (TypeError, ValueError):
            ts = int(time.time())
    else:
        ts = int(time.time())

    base_name = str(symbol).replace(".NS", "").replace(".BO", "").replace("^", "")
    now = time.time()

    return {
        "symbol": symbol,
        "name": base_name,
        "price": round(close, 2),
        "change": change,
        "change_percent": change_percent,
        "prev_close": round(prev_close, 2) if prev_close else None,
        "open": round(_safe_float(last.get("open")) or close, 2),
        "high": round(_safe_float(last.get("high")) or close, 2),
        "low": round(_safe_float(last.get("low")) or close, 2),
        "volume": int(_safe_float(last.get("volume")) or 0),
        "timestamp": ts,
        "source": OFFICIAL_EOD_SOURCE,
        "market_session": "closed",
        "official_close": round(close, 2),
        "official_close_timestamp": ts,
        "official": True,
        "frozen": True,
        "frozen_at": now,
    }


async def _fetch_official_eod_from_provider(symbol: str, provider) -> Optional[dict]:
    """Fetch latest daily EOD candle from Zebu historical API."""
    try:
        candles = await provider.get_historical_data(symbol, period="5d", interval="1d")
        quote = _build_quote_from_candles(symbol, candles)
        if quote:
            return quote
    except Exception as e:
        logger.debug(f"[EOD RECONCILIATION] provider EOD failed for {symbol}: {e}")
    return None


def _candle_timestamp_recent_enough(ts: Any, max_age_seconds: int = 5 * 86400) -> bool:
    """Reject candles older than a few sessions — stale Redis must not become official close."""
    try:
        candle_ts = int(float(ts))
    except (TypeError, ValueError):
        return False
    if candle_ts > 1_000_000_000_000:
        candle_ts //= 1000
    return (time.time() - candle_ts) <= max_age_seconds


async def _fetch_official_eod_from_redis_history(symbol: str) -> Optional[dict]:
    """Fallback: daily candles only (never intraday — those stay stale overnight)."""
    try:
        from cache.redis_client import get_history, get_last_history
    except Exception:
        return None

    for period, interval in (("5d", "1d"), ("1mo", "1d")):
        candles = None
        try:
            candles = await get_history(symbol, period, interval)
        except Exception:
            pass
        if not candles:
            try:
                candles = await get_last_history(symbol, period, interval)
            except Exception:
                pass

        normalized = normalize_history_candles(candles or [])
        if not normalized:
            continue

        last = normalized[-1]
        if not _candle_timestamp_recent_enough(last.get("time")):
            logger.debug(
                "[EOD RECONCILIATION] skip stale redis daily candle for %s ts=%s",
                symbol,
                last.get("time"),
            )
            continue

        quote = _build_quote_from_candles(symbol, normalized)
        if quote:
            return quote

    return None


async def fetch_official_eod_close(symbol: str, provider=None) -> Optional[dict]:
    """Resolve official close: live Zebu EOD API → validated Redis daily → None."""
    sym = _format_symbol(symbol)
    if not sym:
        return None

    if provider is not None:
        quote = await _fetch_official_eod_from_provider(sym, provider)
        if quote:
            return quote

    if provider is None:
        try:
            from services.market_data import get_historical_data_live_only

            candles = await get_historical_data_live_only(
                sym, period="5d", interval="1d", allow_recover=True
            )
            quote = _build_quote_from_candles(sym, candles)
            if quote:
                return quote
        except Exception as e:
            logger.debug(
                "[EOD RECONCILIATION] live history fallback failed for %s: %s",
                sym,
                e,
            )

    return await _fetch_official_eod_from_redis_history(sym)


async def _write_official_close_to_redis(symbol: str, quote: dict) -> bool:
    try:
        from cache.redis_client import get_redis

        cache = await get_redis()
        if not cache.is_connected:
            return False
        ok = await cache.set_authoritative_close(symbol, quote)
        if ok:
            logger.info(
                "[OFFICIAL CLOSE WRITTEN] %s price=%s",
                symbol,
                quote.get("price"),
            )
        return ok
    except Exception as e:
        logger.warning(f"[EOD RECONCILIATION] Redis write failed for {symbol}: {e}")
        return False


async def reconcile_market_close_prices(
    *,
    force: bool = False,
    reason: str = "transition",
) -> dict[str, Any]:
    """
    Reconcile all active symbols to official EOD close in Redis.
    Runs at most once per IST session date unless force=True.
    """
    global _last_reconciled_ist_date

    ist_date = get_reconciliation_ist_date()
    if not force and _last_reconciled_ist_date == ist_date:
        logger.debug("[EOD RECONCILIATION] skipped — already reconciled for %s", ist_date)
        return {"skipped": True, "date": ist_date, "reason": reason}

    async with _RECONCILE_LOCK:
        if not force and _last_reconciled_ist_date == ist_date:
            return {"skipped": True, "date": ist_date, "reason": reason}

        logger.info("[EOD RECONCILIATION] start reason=%s date=%s", reason, ist_date)

        provider = None
        try:
            from services.market_data import _get_any_provider

            provider = _get_any_provider()
        except Exception:
            logger.warning(
                "[EOD RECONCILIATION] no broker session — using Redis history fallback only"
            )

        symbols = sorted(await collect_active_symbols())
        updated = 0
        failed = 0

        sem = asyncio.Semaphore(8)

        async def _reconcile_one(sym: str) -> None:
            nonlocal updated, failed
            async with sem:
                quote = await fetch_official_eod_close(sym, provider)
                if not quote:
                    failed += 1
                    return
                if await _write_official_close_to_redis(sym, quote):
                    updated += 1
                    logger.debug("[EOD SNAPSHOT UPDATED] %s", sym)
                else:
                    failed += 1

        await asyncio.gather(*[_reconcile_one(s) for s in symbols], return_exceptions=True)

        _last_reconciled_ist_date = ist_date
        try:
            await refresh_ticker_and_indices_caches()
        except Exception as e:
            logger.warning(f"[EOD RECONCILIATION] ticker cache refresh failed: {e}")

        summary = {
            "date": ist_date,
            "reason": reason,
            "symbols": len(symbols),
            "updated": updated,
            "failed": failed,
        }
        logger.info("[EOD RECONCILIATION] complete %s", summary)
        return summary


async def refresh_ticker_and_indices_caches() -> int:
    """
    Rewrite Redis ticker/indices snapshots from reconciled official closes.
    Prevents header ticker / market cards from serving week-old snapshot:ticker data.
    """
    from cache.redis_client import set_indices, set_ticker
    from services.market_data import (
        INDIAN_INDICES,
        POPULAR_INDIAN_STOCKS,
        _get_frozen_quote_snapshot,
    )

    items: list[dict] = []

    for idx in INDIAN_INDICES:
        quote = await _get_frozen_quote_snapshot(idx["symbol"])
        if quote:
            items.append({**quote, "name": idx["name"], "kind": "index"})

    for stock in POPULAR_INDIAN_STOCKS:
        quote = await _get_frozen_quote_snapshot(stock["symbol"])
        if quote:
            items.append(
                {
                    **quote,
                    "name": stock.get("name") or stock["symbol"],
                    "kind": "stock",
                }
            )

    if not items:
        return 0

    await set_ticker(items)
    await set_indices([i for i in items if i.get("kind") == "index"])
    logger.info("[EOD SNAPSHOT UPDATED] ticker/indices cache (%d items)", len(items))
    return len(items)


async def _halt_zeroloss_for_closed_session() -> None:
    """Stop all persisted Alpha Auto users when NSE is not in live OPEN session."""
    if market_session.is_live_trading_session():
        return
    try:
        from strategies.zeroloss.manager import zeroloss_manager

        for uid in await zeroloss_manager._get_all_persisted_enabled_user_ids():
            try:
                await zeroloss_manager.disable(uid, close_positions=False)
                logger.info("[ZEROLOSS] auto-stopped — market session closed (user %s)", uid[:8])
            except Exception as e:
                logger.debug("ZeroLoss disable failed for %s: %s", uid, e)
    except Exception as e:
        logger.debug("ZeroLoss session halt failed: %s", e)


def schedule_reconcile_market_close(*, reason: str = "transition") -> None:
    """Fire-and-forget reconciliation (deduped in-flight task)."""
    global _reconciliation_inflight

    if _reconciliation_inflight and not _reconciliation_inflight.done():
        return

    async def _run():
        try:
            await reconcile_market_close_prices(reason=reason)
        except Exception as e:
            logger.exception(f"[EOD RECONCILIATION] failed: {e}")

    _reconciliation_inflight = asyncio.create_task(_run())


class MarketSessionTransitionEngine:
    """
    Detects OPEN → CLOSED (and related) transitions and triggers EOD reconciliation once per day.
    """

    POLL_INTERVAL_SECONDS = 30.0

    def __init__(self) -> None:
        self._running = False
        self._last_phase: Optional[str] = None
        self._task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        self._running = True
        logger.info("Market session transition engine started")
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.debug(f"Session transition tick error: {e}")
            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _tick(self) -> None:
        state = market_session.get_current_state()
        phase = map_session_phase(state)
        prev = self._last_phase
        self._last_phase = phase

        if prev is None:
            if phase != "OPEN":
                schedule_reconcile_market_close(reason="startup_closed")
                await _halt_zeroloss_for_closed_session()
            return

        if prev == "OPEN" and phase in ("PRE_CLOSE", "CLOSED", "POST_CLOSE"):
            logger.info(
                "[MARKET SESSION TRANSITION] OPEN → %s (%s)",
                phase,
                state.value,
            )
            schedule_reconcile_market_close(reason="open_to_closed")
            await _halt_zeroloss_for_closed_session()

        elif prev == "PRE_CLOSE" and phase == "CLOSED":
            logger.info(
                "[MARKET SESSION TRANSITION] PRE_CLOSE → CLOSED (%s)",
                state.value,
            )
            schedule_reconcile_market_close(reason="pre_close_to_closed")


market_session_transition = MarketSessionTransitionEngine()
