import logging
import random
from datetime import date
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Bare underlying symbol (matches services/market_data.py::_INDEX_FUTURES_UNDERLYING
# convention) -> (exchange, anchor price at a fixed reference date). The internal
# sim engine resolves PriceData purely by (exchange, segment, symbol,
# market_timestamp), so these bare tickers - not the "^"-prefixed Yahoo-style
# symbols used on the frontend - are what must exist in price_data for index
# ticks to ever be generated.
_REFERENCE_DATE = date(2024, 1, 1)

INDEX_SEEDS: Dict[str, Dict[str, Any]] = {
    "NIFTY50": {"exchange": "NSE", "anchor_price": 21700.0, "daily_drift": 0.0003},
    "BANKNIFTY": {"exchange": "NSE", "anchor_price": 46000.0, "daily_drift": 0.00035},
    "FINNIFTY": {"exchange": "NSE", "anchor_price": 21000.0, "daily_drift": 0.0003},
    "SENSEX": {"exchange": "BSE", "anchor_price": 72000.0, "daily_drift": 0.0003},
}


def _base_price_for_date(symbol: str, target_date: date) -> float:
    """Deterministic base price for a symbol/date: a fixed anchor price
    compounded by a small daily drift, so any date can be computed
    independently (safe to backfill/re-run in any order) while still trending
    upward realistically over long ranges."""
    cfg = INDEX_SEEDS[symbol]
    days_elapsed = (target_date - _REFERENCE_DATE).days
    return cfg["anchor_price"] * ((1 + cfg["daily_drift"]) ** days_elapsed)


def generate_mock_index_data(target_date: date) -> List[Dict[str, Any]]:
    """Generates deterministic daily OHLCV rows for the tracked indices.

    Indices have no traded volume of their own; we synthesize a plausible
    index-level volume figure (proxying the combined activity of index
    futures/constituents) purely so PriceData.volume (NOT NULL) is satisfied
    and the Brownian-bridge simulator has a nonzero total_volume to spread
    across the trading day.
    """
    records = []
    for symbol, seed_cfg in INDEX_SEEDS.items():
        seed = int(target_date.strftime("%Y%m%d")) + sum(ord(c) for c in symbol)
        rng = random.Random(seed)

        base_price = _base_price_for_date(symbol, target_date)
        pct_change = rng.uniform(-0.015, 0.015)
        open_p = base_price * (1 + rng.uniform(-0.005, 0.005))
        close_p = open_p * (1 + pct_change)
        high_p = max(open_p, close_p) * (1 + rng.uniform(0, 0.008))
        low_p = min(open_p, close_p) * (1 - rng.uniform(0, 0.008))
        vol = rng.randint(50_000_000, 250_000_000)

        records.append({
            "symbol": symbol,
            "exchange": seed_cfg["exchange"],
            "segment": "IDX",
            "market_timestamp": target_date,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": vol,
        })

    return records


def get_index_data(target_date: date, use_mock: bool = True) -> List[Dict[str, Any]]:
    """Entry point mirroring nse_bhavcopy.get_nse_data. There is no public
    free bhavcopy for index-level OHLCV, so this always synthesizes data
    (deterministic per date) rather than downloading it."""
    if not use_mock:
        logger.info(
            "No external index bhavcopy source is configured; generating "
            "deterministic simulated index EOD data for %s instead.", target_date
        )
    return generate_mock_index_data(target_date)
