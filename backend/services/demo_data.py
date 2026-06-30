"""
Demo Market Data Generator — Realistic simulated OHLCV for Indian stocks.

Used as a fallback when no Zebu broker session is configured, so the demo
platform always shows data even without real credentials.

Data is deterministic per symbol+day so history is stable across reloads.
Live quotes vary every 30 seconds to simulate price movement.
"""

import hashlib
import random
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NSE_OPEN_HOUR, NSE_OPEN_MIN = 9, 15
NSE_CLOSE_HOUR, NSE_CLOSE_MIN = 15, 30

# Approximate realistic last-traded prices (INR) for well-known Indian stocks
_BASE_PRICES: dict[str, float] = {
    # NSE Blue Chips
    "RELIANCE.NS": 1285.0,
    "TCS.NS": 3180.0,
    "HDFCBANK.NS": 1720.0,
    "INFY.NS": 1480.0,
    "ICICIBANK.NS": 1280.0,
    "HINDUNILVR.NS": 2290.0,
    "SBIN.NS": 795.0,
    "BHARTIARTL.NS": 1830.0,
    "ITC.NS": 418.0,
    "KOTAKBANK.NS": 2095.0,
    "LT.NS": 3350.0,
    "AXISBANK.NS": 1170.0,
    "WIPRO.NS": 295.0,
    "HCLTECH.NS": 1525.0,
    "TATAMOTORS.NS": 650.0,
    "SUNPHARMA.NS": 1680.0,
    "MARUTI.NS": 11850.0,
    "TITAN.NS": 3270.0,
    "BAJFINANCE.NS": 8850.0,
    "ADANIENT.NS": 2230.0,
    "ADANIPORTS.NS": 1180.0,
    "ULTRACEMCO.NS": 9650.0,
    "NESTLEIND.NS": 2380.0,
    "POWERGRID.NS": 305.0,
    "NTPC.NS": 358.0,
    "ONGC.NS": 268.0,
    "M&M.NS": 2950.0,
    "BAJAJFINSV.NS": 1720.0,
    "TECHM.NS": 1420.0,
    "DRREDDY.NS": 1290.0,
    "CIPLA.NS": 1520.0,
    "ASIANPAINT.NS": 2480.0,
    "TATASTEEL.NS": 148.0,
    "JSWSTEEL.NS": 925.0,
    "HINDALCO.NS": 670.0,
    "COALINDIA.NS": 395.0,
    "GRASIM.NS": 2680.0,
    "BPCL.NS": 312.0,
    "DIVISLAB.NS": 5350.0,
    "APOLLOHOSP.NS": 6920.0,
    "EICHERMOT.NS": 4820.0,
    "HEROMOTOCO.NS": 3950.0,
    "BRITANNIA.NS": 5180.0,
    "TATACONSUM.NS": 1095.0,
    "PIDILITIND.NS": 2820.0,
    "DABUR.NS": 538.0,
    "MARICO.NS": 618.0,
    # Indices
    "^NSEI": 22800.0,
    "^BSESN": 75200.0,
    "^NSEBANK": 48500.0,
    "^CNXIT": 35200.0,
    "^CNXPHARMA": 19800.0,
    "^CNXAUTO": 22400.0,
    "^CNXMETAL": 8950.0,
    "^CNXFMCG": 56200.0,
    "^CNXPSUBANK": 6350.0,
}


def _base_price(symbol: str) -> float:
    s = symbol.upper()
    if s in _BASE_PRICES:
        return _BASE_PRICES[s]
    # Deterministic fallback for unknown symbols: 200–3000 INR range
    h = int(hashlib.md5(s.encode()).hexdigest()[:8], 16)
    return round(200 + (h % 2800), 2)


def _sym_seed(symbol: str) -> int:
    return int(hashlib.md5(symbol.upper().encode()).hexdigest()[:8], 16)


def _trading_days_back(from_date: date, n: int) -> list[date]:
    """Return up to n trading days (Mon–Fri) ending at from_date, oldest first."""
    result: list[date] = []
    d = from_date
    while len(result) < n:
        if d.weekday() < 5:
            result.append(d)
        d -= timedelta(days=1)
    return list(reversed(result))


def _period_to_days(period: str) -> int:
    return {
        "1d": 1, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 132,
        "1y": 252, "2y": 504, "3y": 756, "5y": 1260, "max": 1260,
    }.get(period, 22)


def _interval_minutes(interval: str) -> int:
    return {
        "1m": 1, "2m": 2, "3m": 3, "5m": 5, "10m": 10,
        "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240,
        "1d": 1440, "1wk": 10080, "1mo": 43200,
    }.get(interval, 5)


def _make_candle(
    epoch: int, price: float, rng: random.Random,
    intraday: bool = True
) -> tuple[dict, float]:
    """Build one OHLCV candle, return (candle, close_price)."""
    vol_pct = 0.004 if intraday else 0.018
    pct = rng.gauss(0.0001, vol_pct)
    open_p = round(price, 2)
    close_p = round(max(0.01, price * (1 + pct)), 2)

    spread = abs(close_p - open_p) + price * rng.uniform(0.001, 0.005 if intraday else 0.015)
    high_p = round(max(open_p, close_p) + rng.uniform(0, spread * 0.6), 2)
    low_p = round(max(0.01, min(open_p, close_p) - rng.uniform(0, spread * 0.6)), 2)

    base_vol = _base_price_approx(price)
    vol = int(base_vol * rng.uniform(0.3, 2.0) * (1 if intraday else 500))

    candle = {
        "time": epoch,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": max(100, vol),
    }
    return candle, close_p


def _base_price_approx(price: float) -> float:
    """Estimate a reasonable daily volume scale from price level."""
    if price > 10000:
        return 5000
    if price > 1000:
        return 50000
    return 500000


def generate_demo_candles(
    symbol: str, period: str = "1d", interval: str = "5m"
) -> list[dict]:
    """
    Generate realistic simulated OHLCV candles for a symbol.

    Candles are deterministic (same symbol+period → same history) so the chart
    doesn't jump on every page reload. Only the last ~30s of quote data changes.
    """
    interval_mins = _interval_minutes(interval)
    is_intraday = interval_mins < 1440

    now_ist = datetime.now(IST)
    today = now_ist.date()

    # Seed: symbol + day bucket so history is stable per day
    day_bucket = today.toordinal()
    rng = random.Random(_sym_seed(symbol) ^ day_bucket)
    base = _base_price(symbol)

    # Walk the price backwards from base so recent data is near base price
    # (we'll reverse the generation order)
    candles: list[dict] = []

    if is_intraday:
        days_needed = max(1, _period_to_days(period))
        num_days = min(days_needed, 5)
        trading_days = _trading_days_back(today, num_days)

        # Start price near base with slight offset
        price = base * (1 + rng.uniform(-0.04, 0.04))

        for day in trading_days:
            session_start = datetime(
                day.year, day.month, day.day,
                NSE_OPEN_HOUR, NSE_OPEN_MIN, 0, tzinfo=IST
            )
            session_end = datetime(
                day.year, day.month, day.day,
                NSE_CLOSE_HOUR, NSE_CLOSE_MIN, 0, tzinfo=IST
            )

            t = session_start
            while t < session_end:
                epoch = int(t.timestamp())
                candle, price = _make_candle(epoch, price, rng, intraday=True)
                candles.append(candle)
                t += timedelta(minutes=interval_mins)

    else:
        days_needed = _period_to_days(period)
        if interval == "1wk":
            num_candles = max(5, days_needed // 5)
        elif interval == "1mo":
            num_candles = max(3, days_needed // 22)
        else:
            num_candles = days_needed

        trading_days = _trading_days_back(today, min(num_candles, 1260))

        price = base * (1 + rng.uniform(-0.30, 0.20))

        for day in trading_days:
            epoch = int(datetime(
                day.year, day.month, day.day, 0, 0, 0, tzinfo=IST
            ).timestamp())
            candle, price = _make_candle(epoch, price, rng, intraday=False)
            candles.append(candle)

    return candles


def generate_demo_quote(symbol: str) -> dict:
    """
    Generate a realistic demo quote for a symbol.
    Price shifts every 30 seconds to simulate live movement.
    """
    # Time bucket of 30s so price changes every 30 seconds
    time_bucket = int(time.time()) // 30
    rng = random.Random(_sym_seed(symbol) ^ time_bucket)

    base = _base_price(symbol)
    # Day-stable prev_close
    day_rng = random.Random(_sym_seed(symbol) ^ date.today().toordinal())
    prev_close = round(base * (1 + day_rng.uniform(-0.01, 0.01)), 2)

    # Current price moves from prev_close
    price = round(prev_close * (1 + rng.uniform(-0.025, 0.025)), 2)
    change = round(price - prev_close, 2)
    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

    open_p = round(prev_close * (1 + rng.uniform(-0.005, 0.012)), 2)
    high_p = round(max(price, open_p) * (1 + rng.uniform(0, 0.008)), 2)
    low_p = round(min(price, open_p) * (1 - rng.uniform(0, 0.008)), 2)
    vol = int(_base_price_approx(base) * rng.uniform(0.5, 3.0) * 10)

    base_name = (
        symbol.replace(".NS", "").replace(".BO", "").replace("^", "")
    )

    return {
        "symbol": symbol,
        "name": base_name,
        "price": price,
        "change": change,
        "change_percent": change_pct,
        "prev_close": prev_close,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "volume": max(1000, vol),
        "timestamp": int(time.time()),
        "source": "demo",
        "market_status": "demo",
    }
