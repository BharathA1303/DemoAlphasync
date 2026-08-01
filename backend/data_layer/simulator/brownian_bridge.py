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
TICK_ALGO_VERSION = 4

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

    # 4. Generate U-shaped volume distribution
    # Quadratic function of normalized time: weight = (x - 0.5)^2 + 0.1
    x = np.linspace(0, 1, TOTAL_SECONDS)
    weights = (x - 0.5) ** 2 + 0.08
    
    # Add random volume noise
    noise = np.random.uniform(0.5, 1.5, TOTAL_SECONDS)
    volume_weights = weights * noise
    
    # Normalize and scale
    volume_weights /= np.sum(volume_weights)
    raw_volumes = np.round(volume_weights * total_volume).astype(int)
    
    # Ensure some ticks have zero/low volume
    zero_vol_indices = np.random.choice(TOTAL_SECONDS, size=int(TOTAL_SECONDS * 0.4), replace=False)
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

    Returns the resolved PriceData row (truthy) if ticks are ready in cache,
    or None (falsy) if no EOD source data was found - `if await
    ensure_ticks_cached(...):` works exactly like the old bool-returning
    version. Callers that also need to know WHICH row was actually used
    (e.g. to read its `.version`) should use the return value directly
    rather than re-reading whatever `eod_data` they originally passed in:
    when `eod_data` is None, this function resolves its own row internally,
    so the caller's original (possibly None) local variable would be stale.
    """
    # Cache miss - fetch EOD data if not preloaded (needed for both the
    # version-namespaced cache key and, on a miss, tick generation itself).
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
            # get_eligible_data raises ValueError when target_date falls
            # within the restricted compliance window (e.g. a session's date
            # rolled into the delay-gate cutoff after the session was
            # created). Treat this the same as "no data" rather than letting
            # it propagate as an unhandled exception - callers already
            # handle a None return (see subscribe_symbols, which also
            # pre-checks the gate to give a clearer 400 message up front;
            # this is the defense-in-depth backstop for any caller that
            # doesn't pre-check).
            logger.warning(f"Compliance gate rejected {exchange}:{segment}:{symbol} on {target_date}: {e}")
            return None

    if not eod_data:
        logger.warning(f"No EOD data found for {exchange}:{segment}:{symbol} on {target_date}")
        return None

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
