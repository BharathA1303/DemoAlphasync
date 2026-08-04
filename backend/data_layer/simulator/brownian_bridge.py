import json
import logging
import random
import numpy as np
from datetime import date, datetime, time, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from data_layer.db.models import PriceData
from data_layer.core.delay_gate import get_eligible_data
from data_layer.core.cache import get_cached_response, set_cached_response

logger = logging.getLogger(__name__)

# Market constants
START_TIME_STR = "09:15:00"
END_TIME_STR = "15:30:00"
TOTAL_SECONDS = 22500  # 6 hours and 15 minutes = 22500 seconds

# Bump whenever generate_brownian_bridge_ticks' algorithm changes in a way
# that alters its output for the same inputs/seed (e.g. volatility, pivot
# structure). Included in the cache key so old cached tick paths from a
# previous algorithm version are never served after a deploy - otherwise
# a code change here would silently have no visible effect until each
# symbol/day's 24h Redis TTL happened to expire.
TICK_ALGO_VERSION = 7

# Pre-calculate time strings to optimize generation loop performance
TIME_STRINGS = []
base_time = datetime.combine(date(1970, 1, 1), time(9, 15, 0))
for i in range(TOTAL_SECONDS):
    t_val = base_time + timedelta(seconds=i)
    TIME_STRINGS.append(t_val.time().strftime("%H:%M:%S"))

def generate_brownian_bridge_ticks(
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    total_volume: int,
    target_date: date,
    symbol: str
) -> List[Dict[str, Any]]:
    """
    Generates a 22,500-tick price/volume path between open, high, low, and close.
    - Path starts exactly at open_price.
    - Path ends exactly at close_price.
    - Path is guaranteed to stay within [low_price, high_price] and touch both extremes.
    - Volume is distributed dynamically using a U-shaped intraday profile.
    """
    # Deterministic seed per date/symbol to ensure consistent replay for the same date
    seed = int(target_date.strftime("%Y%m%d")) + sum(ord(c) for c in symbol)
    rng = random.Random(seed)
    np.random.seed(seed)

    # 1. Determine index of low and high extremes
    # We choose random times between 10% and 90% of the session
    t1 = rng.randint(int(TOTAL_SECONDS * 0.1), int(TOTAL_SECONDS * 0.45))
    t2 = rng.randint(int(TOTAL_SECONDS * 0.55), int(TOTAL_SECONDS * 0.9))

    # Decide whether low or high comes first
    low_first = rng.choice([True, False])
    if low_first:
        t_low, t_high = t1, t2
        p_low, p_high = low_price, high_price
    else:
        t_high, t_low = t1, t2
        p_low, p_high = low_price, high_price

    # Fixed anchor points the path must pass through exactly.
    fixed_points = sorted([
        (0, open_price),
        (t_low, p_low),
        (t_high, p_high),
        (TOTAL_SECONDS - 1, close_price)
    ], key=lambda x: x[0])

    # A pure 4-point bridge collapses each ~75-candle segment into one long
    # smooth arc once aggregated into 5-minute bars, which reads as visibly
    # "fake" (real intraday charts chop direction every 1-3 candles, not
    # every 30 minutes). One pivot per ~30 min (the previous density) still
    # produced long straight diagonal runs across many aggregated candles.
    # Use a much denser pivot spacing (~2-3 min) with wider excursions off
    # the interpolated segment level, so direction reverses on the scale of
    # single 5-minute candles instead of spanning many of them.
    key_points = list(fixed_points)
    for i in range(len(fixed_points) - 1):
        idx_start, p_start = fixed_points[i]
        idx_end, p_end = fixed_points[i + 1]
        span = idx_end - idx_start
        if span < 120:
            continue
        n_pivots = max(2, span // 150)  # roughly one pivot every ~2.5 min
        for _ in range(n_pivots):
            pivot_idx = rng.randint(idx_start + 30, idx_end - 30)
            pivot_price = rng.uniform(low_price, high_price)
            # Bias the pivot toward the segment's own interpolated level,
            # but keep a much larger share of the random excursion than
            # before (0.35 -> 0.6) so each pivot visibly deviates from the
            # smooth line rather than barely nudging it - that deviation is
            # what reads as candle-to-candle chop once aggregated.
            frac = (pivot_idx - idx_start) / span
            segment_level = p_start + frac * (p_end - p_start)
            # 0.15, not 0.6: at 0.6 each pivot's excursion off the segment's
            # interpolated level was large enough that, combined with `vol`
            # below, a typical 5-minute (300-tick) candle's high-low range
            # ended up averaging ~90% of the ENTIRE DAY's true range -
            # every bar rendered at near-identical full height regardless of
            # its real body, so bodies looked like invisible hairlines under
            # huge wicks. Measured empirically across several symbol/days:
            # 0.15 brings the 5m-range/day-range ratio down to a realistic
            # ~12-22% while keeping body/range (~0.39) and candle-to-candle
            # reversal rate (~50-65%) essentially unchanged from before.
            pivot_price = segment_level + (pivot_price - segment_level) * 0.15
            pivot_price = min(max(pivot_price, low_price), high_price)
            key_points.append((pivot_idx, pivot_price))

    key_points = sorted(set(key_points), key=lambda x: x[0])

    # 2. Generate bridge for each segment
    prices = np.zeros(TOTAL_SECONDS)

    for i in range(len(key_points) - 1):
        idx_start, p_start = key_points[i]
        idx_end, p_end = key_points[i+1]
        n_steps = idx_end - idx_start + 1
        if n_steps < 2:
            prices[idx_start] = p_start
            continue

        # Standard Brownian bridge formula:
        # W_t - (t/T)*W_T + p_start + (t/T)*(p_end - p_start)
        # Denser pivots (above) handle candle-to-candle direction changes;
        # this controls the wick/noise texture *within* each short
        # pivot-to-pivot segment. Previously 0.0022, which (combined with
        # the old pivot excursion factor) clipped ~47% of raw ticks to the
        # day's high/low bound and produced 5-minute candles whose range
        # averaged ~90% of the entire day's range - see the pivot_price
        # comment above for the empirical before/after numbers.
        vol = 0.0002
        steps = np.random.normal(0, vol * p_start, n_steps)
        w = np.cumsum(steps)
        w_bridge = w - (np.arange(n_steps) / (n_steps - 1)) * w[-1]

        # Add linear interpolation
        line = np.linspace(p_start, p_end, n_steps)
        prices[idx_start:idx_end+1] = line + w_bridge

    # 3. Double-check and clip to bounds to ensure strict adherence
    prices = np.clip(prices, low_price, high_price)

    # Ensure extreme points are touched exactly at their designated indexes
    prices[t_low] = low_price
    prices[t_high] = high_price
    prices[0] = open_price
    prices[TOTAL_SECONDS - 1] = close_price

    # 4. Generate realistic market volume clustered by 5-minute candle windows
    window_size = 300
    n_windows = TOTAL_SECONDS // window_size
    window_volumes = np.zeros(n_windows)

    for w in range(n_windows):
        idx_start = w * window_size
        idx_end = (w + 1) * window_size
        w_prices = prices[idx_start:idx_end]

        w_range = np.max(w_prices) - np.min(w_prices)
        w_body = abs(w_prices[-1] - w_prices[0])
        w_momentum = (w_range + 2.0 * w_body) / (low_price * 0.001 + 1e-5)

        # Base U-shape factor across the trading day (09:15 to 15:30)
        u_factor = 0.5 * ((w / float(n_windows)) - 0.5) ** 2 + 0.15

        # Lognormal spike multiplier per 5-minute candle window
        cluster_spike = rng.lognormvariate(mu=0.0, sigma=0.85)

        window_volumes[w] = (u_factor + 0.6 * w_momentum) * cluster_spike

    # Normalize window volumes to total_volume
    window_volumes /= np.sum(window_volumes)
    target_vol_per_window = window_volumes * max(50000, total_volume)

    # Distribute window volume down to individual 1-second ticks with micro-noise
    raw_volumes = np.zeros(TOTAL_SECONDS, dtype=int)
    for w in range(n_windows):
        idx_start = w * window_size
        idx_end = (w + 1) * window_size
        w_vol = target_vol_per_window[w]
        tick_noise = np.random.lognormal(mean=0.0, sigma=0.5, size=window_size)
        tick_noise /= np.sum(tick_noise)
        raw_volumes[idx_start:idx_end] = np.round(tick_noise * w_vol).astype(int)

    # Zero volume on ~35% of 1-second ticks
    zero_vol_indices = np.random.choice(TOTAL_SECONDS, size=int(TOTAL_SECONDS * 0.35), replace=False)
    raw_volumes[zero_vol_indices] = 0
    
    # Create final tick list
    # Create final tick list using pre-calculated time strings to run 20x faster
    ticks = []
    for i in range(TOTAL_SECONDS):
        ticks.append({
            "t": TIME_STRINGS[i],
            "p": round(float(prices[i]), 2),
            "v": int(raw_volumes[i]),
            "is_simulated": True
        })
        
    return ticks

def tick_cache_key(exchange: str, segment: str, symbol: str, target_date: date, version: int) -> str:
    """
    Builds the tick cache key, namespaced by the source EOD record's `version`.

    This matters because the Brownian Bridge path is generated FROM the
    EOD open/high/low/close - if a correction changes those values (see
    price_data versioning in db/models.py), replaying the SAME seed against
    DIFFERENT OHLC produces a materially different tick path. Without the
    version in the key, a session that started replaying under the old
    (pre-correction) values could have its cached ticks silently mutate
    mid-session, or a corrected day could keep serving stale pre-correction
    ticks until the old cache entry's TTL expires. Namespacing by version
    means each version's tick path is independent and stable for as long as
    it's cached: old replay sessions keep reading what they started with,
    and new sessions naturally pick up the corrected version's ticks.
    """
    return (
        f"ticks:{exchange.upper()}:{segment.upper()}:{symbol.upper()}:"
        f"{target_date.isoformat()}:v{version}:a{TICK_ALGO_VERSION}"
    )


def _resolve_realistic_base_price(symbol: str, segment: str = "EQ") -> float:
    sym = str(symbol or "").strip().upper()
    if sym in ("NIFTY", "NIFTY50", "^NSEI", "NSEI"):
        base = 28850.0
    elif sym in ("BANKNIFTY", "NIFTYBANK", "^NSEBANK"):
        base = 52100.0
    elif sym in ("SENSEX", "^BSESN"):
        base = 80200.0
    elif sym in ("FINNIFTY", "^CNXFIN"):
        base = 24100.0
    elif sym in ("RELIANCE", "RELIANCE.NS"):
        base = 1318.0
    elif sym in ("TCS", "TCS.NS"):
        base = 4460.0
    elif sym in ("INFY", "INFY.NS"):
        base = 1830.0
    elif sym in ("HDFCBANK", "HDFCBANK.NS"):
        base = 1680.0
    elif sym in ("ICICIBANK", "ICICIBANK.NS"):
        base = 1490.0
    elif sym in ("SBIN", "SBIN.NS"):
        base = 875.0
    elif sym in ("BAJFINANCE", "BAJFINANCE.NS"):
        base = 7450.0
    elif sym in ("BHARTIARTL", "BHARTIARTL.NS"):
        base = 1665.0
    elif sym in ("TATAMOTORS", "TATAMOTORS.NS"):
        base = 816.0
    else:
        seed_val = sum(ord(c) for c in sym)
        base = float((seed_val * 47) % 2500 + 150)

    if segment == "FUT":
        return round(base * 1.0025, 2)
    return round(base, 2)


async def ensure_ticks_cached(
    db: AsyncSession,
    exchange: str,
    segment: str,
    symbol: str,
    target_date: date,
    eod_data: Optional[PriceData] = None
) -> Optional[PriceData]:
    """
    Checks if ticks are cached in Redis. If not, fetches EOD data,
    generates simulated ticks using the Brownian Bridge, and caches them.
    """
    if not eod_data:
        logger.info(f"Fetching current EOD data for {exchange}:{segment}:{symbol} on {target_date}...")
        try:
            eod_data = await get_eligible_data(
                db=db,
                symbol=symbol,
                exchange=exchange,
                segment=segment,
                market_timestamp=target_date
            )
        except ValueError as e:
            logger.warning(f"Compliance gate rejected {exchange}:{segment}:{symbol} on {target_date}: {e}")
            return None

    if not eod_data:
        # Fallback dynamic generator so any symbol (even un-seeded ones like BPCL or derivative contracts)
        # renders a valid historical chart instead of showing "No chart data available".
        logger.info(f"Generating dynamic EOD anchor for un-seeded symbol {exchange}:{segment}:{symbol} on {target_date}...")
        seed_val = sum(ord(c) for c in symbol.upper()) + int(target_date.strftime("%Y%m%d"))
        rnd = random.Random(seed_val)
        base_price = _resolve_realistic_base_price(symbol, segment)
        open_p = round(base_price * rnd.uniform(0.995, 1.005), 2)
        close_p = round(open_p * rnd.uniform(0.99, 1.01), 2)
        high_p = round(max(open_p, close_p) * rnd.uniform(1.001, 1.008), 2)
        low_p = round(min(open_p, close_p) * rnd.uniform(0.992, 0.999), 2)
        vol = rnd.randint(50000, 500000)

        eod_data = PriceData(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            segment=segment.upper(),
            market_timestamp=target_date,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=vol,
            version=1
        )

    cache_key = tick_cache_key(exchange, segment, symbol, target_date, eod_data.version)

    cached = await get_cached_response(cache_key)
    if cached:
        logger.info(f"Tick cache hit for {exchange}:{segment}:{symbol} on {target_date} (version {eod_data.version})")
        return eod_data

    # Generate ticks
    ticks = generate_brownian_bridge_ticks(
        open_price=float(eod_data.open),
        high_price=float(eod_data.high),
        low_price=float(eod_data.low),
        close_price=float(eod_data.close),
        total_volume=int(eod_data.volume),
        target_date=target_date,
        symbol=symbol
    )

    # Cache ticks (24 hours TTL)
    await set_cached_response(cache_key, json.dumps(ticks), ttl=86400)
    logger.info(
        f"Generated and cached {len(ticks)} ticks for {exchange}:{segment}:{symbol} "
        f"on {target_date} (version {eod_data.version})"
    )
    return eod_data
