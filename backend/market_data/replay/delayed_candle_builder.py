import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class DelayedCandleBuilder:
    """Builds real 1m/5m/15m OHLCV candles from delayed raw ticks up to cutoff.
    Matches exact exchange price dynamics, time-shifted by delay_seconds.
    """

    @staticmethod
    def build_candles_from_ticks(
        ticks: list,
        timeframe_minutes: int = 1,
    ) -> List[Dict]:
        """Aggregate raw ticks (with real_timestamp and ltp) into OHLCV candles."""
        if not ticks:
            return []

        candles_map: Dict[datetime, Dict] = {}

        for t in ticks:
            ts = getattr(t, "real_timestamp", None) or t.get("real_timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if not ts:
                continue

            ltp = float(getattr(t, "ltp", 0) or t.get("ltp", 0))
            volume = int(getattr(t, "volume", 0) or t.get("volume", 0))

            # Bucket timestamp by timeframe_minutes
            minute_bucket = ts.replace(
                minute=(ts.minute // timeframe_minutes) * timeframe_minutes,
                second=0,
                microsecond=0,
            )

            if minute_bucket not in candles_map:
                candles_map[minute_bucket] = {
                    "timestamp": minute_bucket.isoformat(),
                    "open": ltp,
                    "high": ltp,
                    "low": ltp,
                    "close": ltp,
                    "volume": volume,
                    "count": 1,
                }
            else:
                c = candles_map[minute_bucket]
                c["high"] = max(c["high"], ltp)
                c["low"] = min(c["low"], ltp)
                c["close"] = ltp
                c["volume"] += volume
                c["count"] += 1

        # Return sorted list of candles
        return [candles_map[k] for k in sorted(candles_map.keys())]
