"""
Yahoo Finance Service — Real market data via yfinance.

Used as a fallback data source when no Zebu broker session is configured,
providing real NSE/BSE prices instead of generated demo data.

Priority chain in market_data.py:
  1. Zebu live broker (if credentials configured)
  2. Yahoo Finance (this module — real but slightly delayed data)
  3. Demo data generator (fake data, last resort)

yfinance uses the same SYMBOL.NS / SYMBOL.BO notation that AlphaSync uses,
so no symbol translation is needed.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── In-memory cache ──────────────────────────────────────────────────────────
# Quotes: 30 s TTL (matches Zebu polling cadence)
# History: 5 min TTL (candles don't change that fast)
_QUOTE_TTL = 30
_HISTORY_TTL = 300

_quote_cache: dict[str, tuple[dict, float]] = {}   # symbol → (quote, ts)
_history_cache: dict[str, tuple[list, float]] = {}  # cache_key → (candles, ts)

# ── Period / interval maps ───────────────────────────────────────────────────
# yfinance accepts the same period/interval strings AlphaSync uses.
# Some intraday periods are capped by yfinance (e.g. 1m data only 7 days back).
_PERIOD_MAP: dict[str, str] = {
    "1d": "1d", "5d": "5d", "1mo": "1mo", "3mo": "3mo",
    "6mo": "6mo", "1y": "1y", "2y": "2y", "3y": "3y",
    "5y": "5y", "max": "max",
}

_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m", "2m": "2m", "3m": "5m",   # yfinance has no 3m, map to 5m
    "5m": "5m", "10m": "5m",               # no 10m, map to 5m
    "15m": "15m", "30m": "30m",
    "1h": "60m", "2h": "60m", "4h": "60m",
    "1d": "1d", "1wk": "1wk", "1mo": "1mo",
}


def _is_cache_fresh(cache: dict, key: str, ttl: float) -> bool:
    entry = cache.get(key)
    if entry is None:
        return False
    _, ts = entry
    return (time.time() - ts) < ttl


def _yf_import():
    """Lazy import yfinance — avoids startup cost if Zebu is configured."""
    import yfinance as yf  # noqa: PLC0415
    return yf


def _fetch_quote_sync(symbol: str) -> Optional[dict]:
    """Fetch a real-time quote from Yahoo Finance (synchronous)."""
    try:
        yf = _yf_import()
        ticker = yf.Ticker(symbol)
        fi = ticker.fast_info

        price = getattr(fi, "last_price", None)
        if price is None or price <= 0:
            return None

        prev_close = getattr(fi, "previous_close", None) or price
        open_p = getattr(fi, "open", None) or price
        day_high = getattr(fi, "day_high", None) or price
        day_low = getattr(fi, "day_low", None) or price
        volume = getattr(fi, "last_volume", None) or 0

        change = round(price - prev_close, 2) if prev_close else 0.0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

        base_name = symbol.replace(".NS", "").replace(".BO", "").replace("^", "")

        return {
            "symbol": symbol,
            "name": base_name,
            "price": round(float(price), 2),
            "change": change,
            "change_percent": change_pct,
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "open": round(float(open_p), 2) if open_p else None,
            "high": round(float(day_high), 2) if day_high else None,
            "low": round(float(day_low), 2) if day_low else None,
            "volume": int(volume),
            "timestamp": int(time.time()),
            "source": "yahoo",
            "market_status": "open",
        }
    except Exception as e:
        logger.debug(f"yfinance quote fetch failed for {symbol}: {e}")
        return None


def _fetch_history_sync(symbol: str, period: str, interval: str) -> list[dict]:
    """Fetch historical OHLCV candles from Yahoo Finance (synchronous)."""
    try:
        yf = _yf_import()

        yf_period = _PERIOD_MAP.get(period, "3mo")
        yf_interval = _INTERVAL_MAP.get(interval, "1d")

        # Intraday data: yfinance caps 1m at 7 days, others at 60 days
        intraday = interval not in ("1d", "1wk", "1mo")
        if intraday and period not in ("1d", "5d"):
            yf_period = "5d"

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=yf_period, interval=yf_interval, auto_adjust=True)

        if df is None or df.empty:
            return []

        candles: list[dict] = []
        for idx, row in df.iterrows():
            try:
                # idx is a timezone-aware Timestamp
                if hasattr(idx, "timestamp"):
                    epoch = int(idx.timestamp())
                else:
                    epoch = int(datetime.fromisoformat(str(idx)).timestamp())

                o = float(row["Open"])
                h = float(row["High"])
                lo = float(row["Low"])
                c = float(row["Close"])
                v = int(row.get("Volume", 0) or 0)

                if not all(x > 0 for x in [o, h, lo, c]):
                    continue

                candles.append({
                    "time": epoch,
                    "open": round(o, 2),
                    "high": round(max(h, o, lo, c), 2),
                    "low": round(min(lo, o, h, c), 2),
                    "close": round(c, 2),
                    "volume": max(0, v),
                })
            except Exception:
                continue

        return candles
    except Exception as e:
        logger.debug(f"yfinance history fetch failed for {symbol} {period}/{interval}: {e}")
        return []


async def get_quote(symbol: str) -> Optional[dict]:
    """
    Async wrapper: fetch real quote from Yahoo Finance.
    Returns None if symbol is unknown or Yahoo is unreachable.
    """
    if _is_cache_fresh(_quote_cache, symbol, _QUOTE_TTL):
        return _quote_cache[symbol][0]

    try:
        quote = await asyncio.wait_for(
            asyncio.to_thread(_fetch_quote_sync, symbol),
            timeout=5.0,
        )
        if quote:
            _quote_cache[symbol] = (quote, time.time())
        return quote
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug(f"yfinance async quote failed for {symbol}: {e}")
        # Return stale cache rather than None
        stale = _quote_cache.get(symbol)
        return stale[0] if stale else None


async def get_history(symbol: str, period: str, interval: str) -> list[dict]:
    """
    Async wrapper: fetch real OHLCV candles from Yahoo Finance.
    Returns [] if symbol is unknown or Yahoo is unreachable.
    """
    cache_key = f"{symbol}:{period}:{interval}"
    if _is_cache_fresh(_history_cache, cache_key, _HISTORY_TTL):
        return _history_cache[cache_key][0]

    try:
        candles = await asyncio.wait_for(
            asyncio.to_thread(_fetch_history_sync, symbol, period, interval),
            timeout=10.0,
        )
        if candles:
            _history_cache[cache_key] = (candles, time.time())
        return candles
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug(f"yfinance async history failed for {symbol}: {e}")
        # Return stale cache rather than []
        stale = _history_cache.get(cache_key)
        return stale[0] if stale else []


async def get_batch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Fetch quotes for multiple symbols concurrently."""
    tasks = {sym: get_quote(sym) for sym in symbols}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    out = {}
    for sym, result in zip(tasks.keys(), results):
        if isinstance(result, dict):
            out[sym] = result
    return out
