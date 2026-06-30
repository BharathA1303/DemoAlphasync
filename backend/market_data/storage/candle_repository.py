# candle_repository.py - Aggregate historical tick data into OHLCV candles for charts
"""
Queries the historical_ticks PostgreSQL table and aggregates them into OHLCV
candles at the requested interval (1m, 5m, 15m, 30m, 1h, 1d).

Returns a list of dicts compatible with TradingView Lightweight Charts:
    [{"time": unix_ts, "open": o, "high": h, "low": l, "close": c, "volume": v}]
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from database.connection import async_session_factory

logger = logging.getLogger(__name__)

# Interval → SQL truncation string (PostgreSQL date_trunc / custom)
_INTERVAL_SECONDS: Dict[str, int] = {
    "1m":  60,
    "2m":  120,
    "3m":  180,
    "5m":  300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h":  3600,
    "2h":  7200,
    "4h":  14400,
    "1d":  86400,
    "1w":  604800,
    # Aliases used by charts
    "D":   86400,
    "W":   604800,
}


class CandleRepository:
    """
    Aggregates historical_ticks rows into OHLCV candles.

    Uses a single efficient SQL query with time-bucketing via
    ``date_trunc`` / ``width_bucket`` — no Python-side aggregation loop.
    Falls back gracefully when the table is empty or the symbol is unknown.
    """

    async def get_candles(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 500,
        before_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV candles for *symbol* at the requested *interval*.

        Args:
            symbol:      Canonical symbol (e.g. "RELIANCE.NS", "^NSEI", "GOLD")
            interval:    Candle width: "1m", "5m", "15m", "30m", "1h", "1d", …
            limit:       Maximum number of candles to return (newest *limit* candles)
            before_time: If given, only ticks before this UTC time are considered

        Returns:
            List of {"time", "open", "high", "low", "close", "volume"} dicts,
            sorted ascending by time.  Empty list if no data.
        """
        bucket_secs = _INTERVAL_SECONDS.get(interval, 86400)

        # Determine time window: go back far enough to fill *limit* candles
        if before_time is None:
            before_time = datetime.now(timezone.utc)

        since = before_time - timedelta(seconds=bucket_secs * limit * 2)

        try:
            async with async_session_factory() as db:
                # Use PostgreSQL epoch bucketing for arbitrary intervals
                rows = await db.execute(
                    text("""
                        SELECT
                            (FLOOR(EXTRACT(EPOCH FROM timestamp) / :bucket) * :bucket)::BIGINT AS bucket_ts,
                            (ARRAY_AGG(price ORDER BY timestamp ASC))[1]   AS open,
                            MAX(price)                                       AS high,
                            MIN(price)                                       AS low,
                            (ARRAY_AGG(price ORDER BY timestamp DESC))[1]  AS close,
                            MAX(volume) - COALESCE(MIN(volume), 0)          AS volume
                        FROM historical_ticks
                        WHERE symbol   = :sym
                          AND timestamp >= :since
                          AND timestamp <  :before
                        GROUP BY bucket_ts
                        ORDER BY bucket_ts DESC
                        LIMIT :lim
                    """),
                    {
                        "bucket": bucket_secs,
                        "sym":    symbol,
                        "since":  since,
                        "before": before_time,
                        "lim":    limit,
                    },
                )
                rows = rows.fetchall()

        except Exception as e:
            logger.warning(f"CandleRepository: DB query failed for {symbol} ({interval}): {e}")
            return []

        if not rows:
            return []

        candles = []
        for row in rows:
            o = float(row.open  or 0)
            h = float(row.high  or 0)
            l = float(row.low   or 0)
            c = float(row.close or 0)
            v = int(row.volume  or 0)
            if o <= 0:
                continue
            if h < l:
                h, l = l, h  # defensive swap
            candles.append({
                "time":   int(row.bucket_ts),
                "open":   round(o, 2),
                "high":   round(h, 2),
                "low":    round(l, 2),
                "close":  round(c, 2),
                "volume": v,
            })

        # Return chronologically ascending (we fetched DESC above)
        candles.sort(key=lambda x: x["time"])
        return candles

    async def get_latest_close(self, symbol: str) -> Optional[float]:
        """Return the most recent close price for a symbol (from tick table)."""
        try:
            async with async_session_factory() as db:
                row = await db.execute(
                    text("""
                        SELECT price
                        FROM   historical_ticks
                        WHERE  symbol = :sym
                        ORDER  BY timestamp DESC
                        LIMIT  1
                    """),
                    {"sym": symbol},
                )
                row = row.fetchone()
                return float(row.price) if row else None
        except Exception as e:
            logger.warning(f"CandleRepository.get_latest_close: {e}")
            return None

    async def list_symbols(self) -> List[str]:
        """Return all distinct symbols that have tick data in the DB."""
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    text("SELECT DISTINCT symbol FROM historical_ticks ORDER BY symbol")
                )
                return [r[0] for r in result.fetchall()]
        except Exception as e:
            logger.warning(f"CandleRepository.list_symbols: {e}")
            return []


candle_repository = CandleRepository()
