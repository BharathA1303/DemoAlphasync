#!/usr/bin/env python3
# nse_downloader.py — Downloads REAL NSE Bhavcopy data for simulation base prices
"""
Downloads official NSE/BSE EOD Bhavcopy CSV files and:
  1. Extracts real OHLCV prices for all Nifty50 / popular stocks
  2. Generates realistic intraday tick data from real price levels
  3. Inserts into historical_ticks PostgreSQL table
  4. Returns a price map {symbol -> close_price} for runtime use

NSE Bhavcopy sources:
  - Equity EQ: https://nsearchives.nseindia.com/content/historical/EQUITIES/
  - Indices: Derived from constituent data
  - MCX: Approximated from commodity reference prices

Usage (standalone):
    python nse_downloader.py          # downloads today's data
    python nse_downloader.py 2026-06-27   # specific date

Usage (in-process):
    from market_data.downloader.nse_downloader import nse_downloader
    prices = await nse_downloader.fetch_and_seed()
"""

import asyncio
import io
import logging
import os
import random
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NSE data URLs (delayed / publicly available)
# ---------------------------------------------------------------------------

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}

# NSE Bhavcopy URL patterns
_NSE_BHAVCOPY_NEW_URL = (
    "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
)
_NSE_BHAVCOPY_LEGACY_URL = (
    "https://nsearchives.nseindia.com/content/historical/EQUITIES/"
    "{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip"
)
# NSE indices CSV
_NSE_INDICES_URL = (
    "https://nsearchives.nseindia.com/content/indices/ind_close_all_{ddmmyyyy}.csv"
)

# ---------------------------------------------------------------------------
# Symbol mapping: canonical → NSE trading symbol
# ---------------------------------------------------------------------------

NSE_SYMBOL_MAP: Dict[str, str] = {
    # Indices (special handling)
    "^NSEI":        "__INDEX__NIFTY 50",
    "^NSEBANK":     "__INDEX__NIFTY BANK",
    "^BSESN":       "__INDEX__NIFTY 500",   # proxy
    "^NSMIDCP":     "__INDEX__NIFTY MIDCAP 50",
    # Nifty50 equities
    "RELIANCE.NS":  "RELIANCE",
    "TCS.NS":       "TCS",
    "HDFCBANK.NS":  "HDFCBANK",
    "INFY.NS":      "INFY",
    "ICICIBANK.NS": "ICICIBANK",
    "SBIN.NS":      "SBIN",
    "WIPRO.NS":     "WIPRO",
    "AXISBANK.NS":  "AXISBANK",
    "KOTAKBANK.NS": "KOTAKBANK",
    "LT.NS":        "LT",
    "HCLTECH.NS":   "HCLTECH",
    "ASIANPAINT.NS":"ASIANPAINT",
    "MARUTI.NS":    "MARUTI",
    "SUNPHARMA.NS": "SUNPHARMA",
    "BAJFINANCE.NS":"BAJFINANCE",
    "BAJAJFINSV.NS":"BAJAJFINSV",
    "ADANIENT.NS":  "ADANIENT",
    "ADANIPORTS.NS":"ADANIPORTS",
    "HINDUNILVR.NS":"HINDUNILVR",
    "NESTLEIND.NS": "NESTLEIND",
    "TITAN.NS":     "TITAN",
    "ULTRACEMCO.NS":"ULTRACEMCO",
    "GRASIM.NS":    "GRASIM",
    "TECHM.NS":     "TECHM",
    "DRREDDY.NS":   "DRREDDY",
    "CIPLA.NS":     "CIPLA",
    "DIVISLAB.NS":  "DIVISLAB",
    "BHARTIARTL.NS":"BHARTIARTL",
    "COALINDIA.NS": "COALINDIA",
    "JSWSTEEL.NS":  "JSWSTEEL",
    "TATASTEEL.NS": "TATASTEEL",
    "HINDALCO.NS":  "HINDALCO",
    "EICHERMOT.NS": "EICHERMOT",
    "BAJAJ-AUTO.NS":"BAJAJ-AUTO",
    "HEROMOTOCO.NS":"HEROMOTOCO",
    "M&M.NS":       "M&M",
    "TATACONSUM.NS":"TATACONSUM",
    "ITC.NS":       "ITC",
    "BPCL.NS":      "BPCL",
    "INDUSINDBK.NS":"INDUSINDBK",
    "APOLLOHOSP.NS":"APOLLOHOSP",
    "SBILIFE.NS":   "SBILIFE",
    "HDFCLIFE.NS":  "HDFCLIFE",
    "ONGC.NS":      "ONGC",
    "NTPC.NS":      "NTPC",
    "POWERGRID.NS": "POWERGRID",
}

# MCX commodity reference prices (approximate — MCX does not have free public CSV)
MCX_REFERENCE_PRICES: Dict[str, float] = {
    "GOLD":       73500.0,
    "GOLDM":      73520.0,
    "SILVER":     92000.0,
    "SILVERM":    92050.0,
    "CRUDEOIL":    6750.0,
    "NATURALGAS":   225.0,
    "COPPER":       870.0,
    "ZINC":         265.0,
    "LEAD":         195.0,
    "ALUMINIUM":    245.0,
    "NICKEL":      1960.0,
}

# Intraday regime: (hour, minute) → (drift, volatility_mult)
_REGIMES = [
    ((9, 15),  (0.0,   2.5)),
    ((9, 45),  (0.0003,1.8)),
    ((10, 30), (0.0,   1.2)),
    ((12, 30), (0.0,   0.6)),
    ((13, 30), (0.0,   1.0)),
    ((14, 30), (0.0002,1.4)),
    ((15, 0),  (0.0,   1.8)),
]


def _regime(t: datetime) -> tuple:
    hm = (t.hour, t.minute)
    sel = _REGIMES[0][1]
    for (rh, rm), p in _REGIMES:
        if hm >= (rh, rm):
            sel = p
    return sel


# ---------------------------------------------------------------------------
# NSE Bhavcopy downloader
# ---------------------------------------------------------------------------

class NSEDownloader:
    """
    Downloads NSE Bhavcopy CSV to get real EOD prices,
    then seeds the historical_ticks database with realistic
    intraday simulation data based on those real prices.
    """

    def __init__(self):
        self._last_prices: Dict[str, Dict] = {}   # nse_sym → {open,high,low,close,volume}
        self._canonical_prices: Dict[str, float] = {}  # canonical_sym → close

    # ── Public API ─────────────────────────────────────────────────────

    async def fetch_and_seed(
        self,
        target_date: Optional[date] = None,
        seed_db: bool = True,
    ) -> Dict[str, float]:
        """
        1. Download NSE Bhavcopy for target_date (default: most recent trading day)
        2. Parse OHLCV for all Nifty50 stocks
        3. (Optional) seed historical_ticks with intraday simulation data
        4. Return {canonical_symbol: close_price}
        """
        session_date = target_date or self._last_trading_day()
        logger.info(f"NSEDownloader: fetching data for {session_date}")

        # Try to download real NSE data
        eq_data = await self._download_equity_bhavcopy(session_date)
        idx_data = await self._download_index_data(session_date)

        all_data = {**eq_data, **idx_data}

        # Build canonical price map
        prices: Dict[str, float] = {}
        for canonical, nse_sym in NSE_SYMBOL_MAP.items():
            if nse_sym.startswith("__INDEX__"):
                idx_name = nse_sym[9:]
                if idx_name in all_data:
                    prices[canonical] = all_data[idx_name]["close"]
            elif nse_sym in all_data:
                prices[canonical] = all_data[nse_sym]["close"]

        # Add MCX commodities (reference prices, not real-time)
        for sym, px in MCX_REFERENCE_PRICES.items():
            prices[sym] = px

        if prices:
            logger.info(f"NSEDownloader: got {len(prices)} real prices from NSE")
        else:
            logger.warning("NSEDownloader: no prices from NSE, using catalogue defaults")

        self._canonical_prices = prices

        if seed_db and prices:
            await self._seed_historical_ticks(prices, session_date)

        return prices

    def get_price(self, canonical: str) -> Optional[float]:
        """Return the last fetched close price for a symbol."""
        return self._canonical_prices.get(canonical)

    def get_all_prices(self) -> Dict[str, float]:
        return dict(self._canonical_prices)

    # ── NSE Bhavcopy download ───────────────────────────────────────────

    async def _download_equity_bhavcopy(self, d: date) -> Dict[str, Dict]:
        """Download and parse NSE equity Bhavcopy CSV for date d."""
        # Try new-format full security bhav data
        ddmmyyyy = d.strftime("%d%m%Y")
        url_new = _NSE_BHAVCOPY_NEW_URL.format(ddmmyyyy=ddmmyyyy)
        data = await self._try_download(url_new, is_zip=False)
        if data:
            parsed = self._parse_equity_csv_new(data)
            if parsed:
                logger.info(f"NSEDownloader: parsed {len(parsed)} equities (new format)")
                return parsed

        # Try legacy ZIP format
        yyyy = d.strftime("%Y")
        mmm  = d.strftime("%b").upper()
        dd   = d.strftime("%d")
        url_zip = _NSE_BHAVCOPY_LEGACY_URL.format(yyyy=yyyy, mmm=mmm, dd=dd)
        data_zip = await self._try_download(url_zip, is_zip=True)
        if data_zip:
            parsed = self._parse_equity_csv_legacy(data_zip)
            if parsed:
                logger.info(f"NSEDownloader: parsed {len(parsed)} equities (legacy format)")
                return parsed

        logger.warning(f"NSEDownloader: equity Bhavcopy unavailable for {d}")
        return {}

    async def _download_index_data(self, d: date) -> Dict[str, Dict]:
        """Download and parse NSE index close CSV."""
        ddmmyyyy = d.strftime("%d%m%Y")
        url = _NSE_INDICES_URL.format(ddmmyyyy=ddmmyyyy)
        data = await self._try_download(url, is_zip=False)
        if not data:
            return {}
        return self._parse_index_csv(data)

    async def _try_download(self, url: str, is_zip: bool) -> Optional[str]:
        """Attempt HTTP download with NSE headers. Returns text content or None."""
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(headers=_NSE_HEADERS, timeout=timeout) as session:
                # First hit the NSE homepage to get cookies
                try:
                    await session.get("https://www.nseindia.com/", ssl=False)
                except Exception:
                    pass

                async with session.get(url, ssl=False) as resp:
                    if resp.status != 200:
                        logger.debug(f"NSEDownloader: {url} → HTTP {resp.status}")
                        return None

                    raw = await resp.read()
                    if is_zip:
                        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                            # Find the CSV inside the ZIP
                            csv_name = next(
                                (n for n in zf.namelist() if n.endswith(".csv")),
                                None,
                            )
                            if not csv_name:
                                return None
                            return zf.read(csv_name).decode("utf-8", errors="replace")
                    else:
                        return raw.decode("utf-8", errors="replace")

        except asyncio.TimeoutError:
            logger.warning(f"NSEDownloader: timeout downloading {url}")
        except Exception as e:
            logger.warning(f"NSEDownloader: download failed ({url}): {e}")
        return None

    # ── CSV parsers ────────────────────────────────────────────────────

    def _parse_equity_csv_new(self, text: str) -> Dict[str, Dict]:
        """
        Parse the new NSE full sec_bhavdata_full_DDMMYYYY.csv format.
        Columns: SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,...
        """
        result = {}
        lines = text.strip().splitlines()
        if not lines:
            return result

        header = [h.strip().upper() for h in lines[0].split(",")]
        try:
            si = header.index("SYMBOL")
            ser_i = header.index("SERIES")
            oi = header.index("OPEN")
            hi = header.index("HIGH")
            li = header.index("LOW")
            ci = header.index("CLOSE")
            vi = header.index("TOTTRDQTY")
        except ValueError:
            return result

        for line in lines[1:]:
            cols = [c.strip() for c in line.split(",")]
            if len(cols) <= max(si, ser_i, oi, hi, li, ci, vi):
                continue
            if cols[ser_i] != "EQ":
                continue
            try:
                sym = cols[si]
                result[sym] = {
                    "open":   float(cols[oi]),
                    "high":   float(cols[hi]),
                    "low":    float(cols[li]),
                    "close":  float(cols[ci]),
                    "volume": int(float(cols[vi])),
                }
            except (ValueError, IndexError):
                continue
        return result

    def _parse_equity_csv_legacy(self, text: str) -> Dict[str, Dict]:
        """
        Parse legacy NSE Bhavcopy CSV (cm{DD}{MMM}{YYYY}bhav.csv).
        Columns: SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,...
        """
        return self._parse_equity_csv_new(text)   # same column names

    def _parse_index_csv(self, text: str) -> Dict[str, Dict]:
        """
        Parse NSE ind_close_all_DDMMYYYY.csv.
        Columns: Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,...
        """
        result = {}
        lines = text.strip().splitlines()
        if not lines:
            return result

        header = [h.strip().upper() for h in lines[0].split(",")]
        try:
            ni  = header.index("INDEX NAME")
            oi  = header.index("OPEN INDEX VALUE")
            hi  = header.index("HIGH INDEX VALUE")
            li  = header.index("LOW INDEX VALUE")
            ci  = header.index("CLOSING INDEX VALUE")
        except ValueError:
            return result

        for line in lines[1:]:
            cols = [c.strip() for c in line.split(",")]
            if len(cols) <= max(ni, oi, hi, li, ci):
                continue
            try:
                name = cols[ni].strip()
                result[name] = {
                    "open":   float(cols[oi].replace(",", "")),
                    "high":   float(cols[hi].replace(",", "")),
                    "low":    float(cols[li].replace(",", "")),
                    "close":  float(cols[ci].replace(",", "")),
                    "volume": 0,
                }
            except (ValueError, IndexError):
                continue
        return result

    # ── Tick seeding ────────────────────────────────────────────────────

    async def _seed_historical_ticks(
        self, prices: Dict[str, float], session_date: date
    ) -> int:
        """
        Generate realistic intraday tick data from real close prices
        and insert into historical_ticks. Uses a simplified OHLCV model:
          open  ≈ prev_close ± 0.5%
          close = real close (anchor to real price)
          high, low = open ± intraday range
        """
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            from database.connection import async_session_factory, init_db
            from models.historical_ticks import HistoricalTick
            from sqlalchemy import text
        except ImportError as e:
            logger.warning(f"NSEDownloader: DB import failed, skipping seed: {e}")
            return 0

        from datetime import datetime as dt_cls
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")

        start_ist = dt_cls(session_date.year, session_date.month, session_date.day,
                           9, 15, 0, tzinfo=IST)
        end_ist   = dt_cls(session_date.year, session_date.month, session_date.day,
                           15, 30, 0, tzinfo=IST)
        start_utc = start_ist.astimezone(timezone.utc)
        end_utc   = end_ist.astimezone(timezone.utc)

        # Per-symbol state
        states = {}
        for canonical, close_px in prices.items():
            gap = close_px * random.uniform(-0.005, 0.005)
            open_px = round(close_px + gap, 2)
            states[canonical] = {
                "price": open_px,
                "open":  open_px,
                "high":  open_px,
                "low":   open_px,
                "volume": 0,
                "oi": 0,
                "close_target": close_px,   # We'll drift toward this
            }

        ticks = []
        current = start_utc
        market_drift = 0.0

        while current < end_utc:
            # regime
            sim_ist = current.astimezone(IST)
            drift_bias, vol_mult = _regime(sim_ist)

            step_ms = random.randint(80, 250) if vol_mult > 1.0 else random.randint(150, 400)
            current += timedelta(milliseconds=step_ms)
            if current >= end_utc:
                break

            market_drift += random.normalvariate(drift_bias, 0.00008)
            market_drift = max(-0.012, min(0.012, market_drift))

            # How far through the day are we? (0.0 = open, 1.0 = close)
            elapsed = (current - start_utc).total_seconds()
            total   = (end_utc   - start_utc).total_seconds()
            progress = elapsed / total  # 0→1

            n = random.randint(1, 3)
            syms = random.sample(list(prices.keys()), min(n, len(prices)))

            for sym in syms:
                state = states[sym]
                close_target = state["close_target"]

                # Base volatility from symbol kind
                if "^" in sym or "FUT" in sym:
                    vol = 0.00015
                elif any(x in sym for x in ("CE", "PE")):
                    vol = 0.00120
                elif sym in MCX_REFERENCE_PRICES:
                    vol = 0.00045
                else:
                    vol = 0.00035

                eff_vol = vol * vol_mult

                # Pull toward close_target as day progresses
                pull_strength = progress * 0.003
                pull = (close_target - state["price"]) / max(state["price"], 0.01) * pull_strength

                drift = market_drift * 0.55 + random.normalvariate(0.0, eff_vol) + pull
                new_px = max(0.05, state["price"] * (1.0 + drift))
                new_px = round(new_px, 2)

                state["price"] = new_px
                state["high"]  = max(state["high"], new_px)
                state["low"]   = min(state["low"],  new_px)

                sp = max(0.05, round(new_px * 0.0003, 2))
                bid = round(new_px - sp / 2, 2)
                ask = round(new_px + sp / 2, 2)

                if "^" not in sym:
                    state["volume"] += random.randint(50, 500)

                # Determine exchange
                if sym in MCX_REFERENCE_PRICES:
                    exch = "MCX"
                elif "FUT" in sym or "CE" in sym or "PE" in sym:
                    exch = "NFO"
                else:
                    exch = "NSE"

                ticks.append(HistoricalTick(
                    symbol    = sym,
                    timestamp = current,
                    price     = Decimal(str(new_px)),
                    volume    = state["volume"],
                    oi        = state["oi"],
                    bid_price = Decimal(str(bid)),
                    ask_price = Decimal(str(ask)),
                    bid_qty   = random.randint(100, 3000),
                    ask_qty   = random.randint(100, 3000),
                    exchange  = exch,
                ))

        logger.info(f"NSEDownloader: generated {len(ticks)} ticks for {session_date}")

        # Bulk insert
        chunk = 5000
        async with async_session_factory() as db:
            try:
                await db.execute(
                    text("DELETE FROM historical_ticks WHERE DATE(timestamp AT TIME ZONE 'UTC') = :d"),
                    {"d": session_date},
                )
                await db.commit()

                for i in range(0, len(ticks), chunk):
                    db.add_all(ticks[i: i + chunk])
                    await db.commit()

                logger.info(f"NSEDownloader: seeded {len(ticks)} ticks into DB for {session_date}")
                return len(ticks)
            except Exception as e:
                await db.rollback()
                logger.error(f"NSEDownloader: DB seed failed: {e}")
                return 0

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _last_trading_day() -> date:
        """Return the most recent trading weekday (skip weekends)."""
        today = date.today()
        d = today
        if today.weekday() == 0:     # Monday → go to Friday
            d = today - timedelta(days=3)
        elif today.weekday() == 6:   # Sunday → go to Friday
            d = today - timedelta(days=2)
        elif today.weekday() == 5:   # Saturday → go to Friday
            d = today - timedelta(days=1)
        # If before 3:30 PM IST today, use yesterday
        else:
            from zoneinfo import ZoneInfo
            now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
            if now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute < 30):
                d = today - timedelta(days=1)
                if d.weekday() == 6:
                    d -= timedelta(days=2)
                elif d.weekday() == 5:
                    d -= timedelta(days=1)
        return d


# Module-level singleton
nse_downloader = NSEDownloader()


# ---------------------------------------------------------------------------
# Entry point for standalone use
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    target = None
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Usage: python nse_downloader.py [YYYY-MM-DD]")
            sys.exit(1)

    # Add backend to path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from database.connection import init_db
    await init_db()

    prices = await nse_downloader.fetch_and_seed(target_date=target, seed_db=True)
    print(f"\nFetched {len(prices)} symbols:")
    for sym, px in sorted(prices.items())[:20]:
        print(f"  {sym:<30} ₹{px:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
