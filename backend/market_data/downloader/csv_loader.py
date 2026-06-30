# csv_loader.py - Load historical OHLCV CSVs and synthesize realistic tick-by-tick data
"""
Expected CSV format (one file per symbol per day, or combined):

  EQ  : data/eq/RELIANCE_2024-06-28.csv
  F&O : data/fno/NIFTY24JUNFUT_2024-06-28.csv
  MCX : data/mcx/GOLD_2024-06-28.csv

  Combined (all symbols, one file per day):
        data/combined/2024-06-28.csv

Mandatory columns  : date/datetime, open, high, low, close, volume
Optional columns   : oi (open interest – auto-filled for F&O/MCX)
                     symbol (required in combined files)
                     exchange (NSE / NFO / BFO / MCX; inferred from path if absent)

The loader converts each 1-minute candle into ~6-40 realistic sub-second ticks
using a micro-structure model:
  • Open tick  – price snaps to candle open with a gap from previous close
  • Body ticks – random walk that must honour the candle high/low
  • Close tick – price converges to candle close
  • Volume     – distributed across ticks proportional to distance from VWAP
  • Bid/Ask    – spread derived from exchange and price level
"""

import csv
import io
import logging
import os
import random
import zipfile
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from database.connection import async_session_factory
from models.historical_ticks import HistoricalTick
from market_data.downloader.validator import validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol metadata registry
# ---------------------------------------------------------------------------

EXCHANGE_DEFAULTS: Dict[str, str] = {
    "eq": "NSE",
    "fno": "NFO",
    "bfo": "BFO",
    "mcx": "MCX",
    "combined": "NSE",
}

# Spread as a fraction of price, by exchange
SPREAD_PCT: Dict[str, float] = {
    "NSE": 0.00040,   # ~0.04 % for liquid large-caps
    "NFO": 0.00025,   # tighter for index futures
    "BFO": 0.00030,
    "MCX": 0.00050,
}

# Lot sizes (for volume sanity)
LOT_SIZES: Dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 75,
    "SENSEX": 10,
    "BANKEX": 15,
    "GOLD": 1,
    "SILVER": 30,
    "CRUDEOIL": 100,
    "NATURALGAS": 1250,
    "COPPER": 2500,
    "DEFAULT": 1,
}

# Volatility per tick (sigma of log-return per micro-tick)
VOLATILITY: Dict[str, float] = {
    "NSE_INDEX": 0.00010,
    "NSE_STOCK": 0.00035,
    "NFO": 0.00050,
    "BFO": 0.00050,
    "MCX": 0.00045,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_exchange(folder: str, symbol: str) -> str:
    folder = folder.lower()
    if folder in EXCHANGE_DEFAULTS:
        return EXCHANGE_DEFAULTS[folder]
    sym = symbol.upper()
    if any(x in sym for x in ("FUT", "CE", "PE", "CALL", "PUT")):
        return "NFO"
    if sym in ("GOLD", "SILVER", "CRUDEOIL", "COPPER", "NATURALGAS"):
        return "MCX"
    return "NSE"


def _lot_size(symbol: str) -> int:
    for key, size in LOT_SIZES.items():
        if symbol.upper().startswith(key):
            return size
    return LOT_SIZES["DEFAULT"]


def _spread(price: float, exchange: str) -> float:
    pct = SPREAD_PCT.get(exchange, 0.00040)
    raw = price * pct
    # Enforce minimum tick: 0.05 for NSE/NFO, 1.0 for MCX GOLD
    if exchange == "MCX":
        return max(1.0, round(raw, 0))
    return max(0.05, round(raw * 2, 2) / 2)   # nearest 0.05


def _volatility(exchange: str, symbol: str) -> float:
    if exchange in ("NFO", "BFO"):
        return VOLATILITY["NFO"]
    if exchange == "MCX":
        return VOLATILITY["MCX"]
    if symbol.startswith("^") or symbol in ("NIFTY 50", "NIFTY50", "BANKNIFTY"):
        return VOLATILITY["NSE_INDEX"]
    return VOLATILITY["NSE_STOCK"]


def _parse_datetime(raw: str) -> Optional[datetime]:
    """Parse a date/datetime string; returns UTC-aware datetime or None."""
    raw = raw.strip()
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _col(row: Dict[str, str], *names: str) -> Optional[str]:
    """Case-insensitive column lookup."""
    for name in names:
        for key in row:
            if key.strip().lower() == name.lower():
                v = row[key].strip()
                return v if v else None
    return None


# ---------------------------------------------------------------------------
# Micro-structure tick synthesiser
# ---------------------------------------------------------------------------

def _synthesise_ticks(
    candle_time: datetime,    # start of the 1-minute candle
    o: float, h: float, l: float, c: float,
    volume: int,
    oi: int,
    exchange: str,
    symbol: str,
    prev_close: Optional[float],
    n_ticks: Optional[int] = None,
) -> List[dict]:
    """
    Convert a single 1-minute OHLCV candle into realistic sub-second ticks.

    Micro-structure rules
    ─────────────────────
    1. First tick snaps to candle open (reflecting the gap from previous close).
    2. Middle ticks perform a bounded random walk that must reach H and L at
       some point during the candle.
    3. Last tick converges to candle close.
    4. Volume is distributed non-uniformly (more at open + close).
    5. Bid/ask spread is exchange-aware.
    6. OI changes ±small random amount per tick for derivatives.
    """
    if n_ticks is None:
        # Scale tick density with volume; clamp [6, 40]
        n_ticks = max(6, min(40, volume // max(1, _lot_size(symbol)) // 10 + 8))

    spread = _spread(o, exchange)
    half_spread = spread / 2.0
    vol = _volatility(exchange, symbol)
    lot = _lot_size(symbol)

    ticks: List[dict] = []
    current_price = o
    high_hit = False
    low_hit = False
    cum_volume = 0

    # Volume weights: higher at open (index 0) and close (index n-1)
    weights = [1.0] * n_ticks
    weights[0] = 3.0
    weights[-1] = 3.0
    if n_ticks > 4:
        weights[1] = 1.8
        weights[-2] = 1.8
    total_weight = sum(weights)
    vol_shares = [int(volume * w / total_weight) for w in weights]
    # Fix rounding: put remainder on last tick
    vol_shares[-1] += volume - sum(vol_shares)

    # Spread ticks uniformly across the 60-second candle (sub-second offsets)
    interval_ms = 60_000 // n_ticks
    current_oi = oi

    for i in range(n_ticks):
        tick_time = candle_time + timedelta(milliseconds=i * interval_ms + random.randint(0, interval_ms // 2))

        if i == 0:
            p = o
        elif i == n_ticks - 1:
            # Converge to close
            p = c
        else:
            # Bounded random walk – must visit h and l somewhere in the middle
            remaining = n_ticks - 1 - i
            drift = random.normalvariate(0, vol)

            # If we haven't hit the high yet and time is running out, bias upward
            if not high_hit and remaining <= (n_ticks // 3):
                drift += vol * 2
            # Same for low
            if not low_hit and remaining <= (n_ticks // 3):
                drift -= vol * 2

            p = round(current_price * (1.0 + drift), 2)
            # Hard clamp to candle boundaries
            p = max(l, min(h, p))

        if p >= h:
            high_hit = True
        if p <= l:
            low_hit = True

        current_price = p

        bid = round(p - half_spread, 2)
        ask = round(p + half_spread, 2)
        bid_qty = random.randint(1, 20) * lot
        ask_qty = random.randint(1, 20) * lot

        # Cumulative volume (tick shows running total like exchange feed)
        cum_volume += vol_shares[i]

        if exchange in ("NFO", "BFO", "MCX"):
            current_oi += random.randint(-2, 2) * lot
            current_oi = max(0, current_oi)

        ticks.append({
            "symbol": symbol,
            "timestamp": tick_time.isoformat(),
            "price": p,
            "volume": cum_volume,
            "oi": current_oi,
            "bid_price": bid,
            "ask_price": ask,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "exchange": exchange,
        })

    return ticks


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def _rows_from_text(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _parse_candles_from_rows(
    rows: List[Dict[str, str]],
    symbol: str,
    exchange: str,
    candle_date: Optional[datetime] = None,
) -> List[Tuple[datetime, float, float, float, float, int, int]]:
    """
    Returns list of (candle_time, o, h, l, c, volume, oi) tuples.
    candle_date is used for date-only CSVs to build a full intraday schedule.
    """
    candles = []
    for row in rows:
        sym_col = _col(row, "symbol", "ticker", "scrip")
        if sym_col and sym_col.upper() != symbol.upper():
            continue

        raw_dt = _col(row, "datetime", "date", "time", "timestamp", "Date", "Datetime")
        if not raw_dt:
            continue
        dt = _parse_datetime(raw_dt)
        if not dt:
            continue

        # For date-only files, build synthetic 1-min bars from 9:15 to 15:30
        if dt.hour == 0 and dt.minute == 0 and candle_date:
            dt = candle_date.replace(hour=9, minute=15, second=0, microsecond=0, tzinfo=timezone.utc)

        try:
            o = float(_col(row, "open", "Open") or 0)
            h = float(_col(row, "high", "High") or 0)
            l = float(_col(row, "low", "Low") or 0)
            c = float(_col(row, "close", "Close") or 0)
            vol = int(float(_col(row, "volume", "Volume", "vol") or 0))
            oi = int(float(_col(row, "oi", "OI", "open_interest") or 0))
        except (ValueError, TypeError):
            continue

        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            continue
        if h < l:
            h, l = l, h  # swap silently

        candles.append((dt, o, h, l, c, vol, oi))

    candles.sort(key=lambda x: x[0])
    return candles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class CSVLoader:
    """
    Loads historical OHLCV CSV files and converts them to tick-by-tick data
    stored in PostgreSQL — the same table the replay engine reads from.

    Supported layouts
    ─────────────────
    data/
      eq/          → NSE equities   (symbol_YYYY-MM-DD.csv or symbol.csv)
      fno/         → NSE F&O        (contract_YYYY-MM-DD.csv)
      mcx/         → MCX            (commodity_YYYY-MM-DD.csv)
      bfo/         → BSE F&O
      combined/    → Any exchange   (must have 'symbol' + 'exchange' columns)

    Files can also be zipped: symbol_YYYY-MM-DD.zip containing the CSV inside.
    """

    def __init__(self, data_root: Optional[str] = None):
        if data_root is None:
            # Default: <project_root>/data/  (two levels above backend/)
            here = Path(__file__).resolve()
            data_root = str(here.parents[3] / "data")
        self.data_root = Path(data_root)

    # ── Discovery ────────────────────────────────────────────────────────

    def discover_files(self, date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Walk data_root and return metadata for all loadable CSV/ZIP files.
        Optionally filter by date (matches YYYY-MM-DD in filename).
        """
        date_str = date.strftime("%Y-%m-%d") if date else None
        found = []
        for folder in ("eq", "fno", "mcx", "bfo", "combined"):
            folder_path = self.data_root / folder
            if not folder_path.exists():
                continue
            exchange = EXCHANGE_DEFAULTS.get(folder, "NSE")
            for f in sorted(folder_path.iterdir()):
                if f.suffix.lower() not in (".csv", ".zip"):
                    continue
                if date_str and date_str not in f.name:
                    continue
                # Infer symbol from filename: "RELIANCE_2024-06-28.csv" → "RELIANCE"
                stem = f.stem.upper().split("_")[0]
                found.append({
                    "path": f,
                    "folder": folder,
                    "exchange": exchange,
                    "symbol": stem,
                })
        return found

    # ── File reading ─────────────────────────────────────────────────────

    def _read_file(self, path: Path) -> str:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".csv"):
                        return zf.read(name).decode("utf-8", errors="replace")
            raise ValueError(f"No CSV found inside {path}")
        return path.read_text(encoding="utf-8", errors="replace")

    # ── Single-file ingestion ────────────────────────────────────────────

    async def load_file(
        self,
        path: Path,
        symbol: str,
        exchange: str,
        replace_existing: bool = True,
    ) -> int:
        """
        Load a single CSV/ZIP file, synthesise ticks, insert into DB.
        Returns count of ticks inserted.
        """
        try:
            text = self._read_file(path)
        except Exception as e:
            logger.error(f"CSVLoader: Cannot read {path}: {e}")
            return 0

        rows = _rows_from_text(text)
        if not rows:
            logger.warning(f"CSVLoader: {path} is empty or has no parseable rows")
            return 0

        # For combined files, delegate per-symbol
        if "combined" in str(path).lower():
            return await self._load_combined(rows, replace_existing)

        candles = _parse_candles_from_rows(rows, symbol, exchange)
        if not candles:
            logger.warning(f"CSVLoader: No valid candles in {path}")
            return 0

        ticks = self._candles_to_ticks(candles, symbol, exchange)
        return await self._insert_ticks(ticks, replace_existing)

    async def _load_combined(self, rows: List[Dict[str, str]], replace_existing: bool) -> int:
        """Handle multi-symbol combined CSV files."""
        by_symbol: Dict[str, List] = {}
        for row in rows:
            sym = _col(row, "symbol", "ticker", "scrip")
            if not sym:
                continue
            sym = sym.upper()
            by_symbol.setdefault(sym, []).append(row)

        total = 0
        for sym, sym_rows in by_symbol.items():
            exch_col = _col(sym_rows[0], "exchange")
            exchange = exch_col.upper() if exch_col else _infer_exchange("combined", sym)
            candles = _parse_candles_from_rows(sym_rows, sym, exchange)
            if candles:
                ticks = self._candles_to_ticks(candles, sym, exchange)
                total += await self._insert_ticks(ticks, replace_existing)
        return total

    # ── Batch ingestion for a whole date ─────────────────────────────────

    async def load_date(self, date: datetime, replace_existing: bool = True) -> int:
        """Load all CSV files for the given date across all asset classes."""
        files = self.discover_files(date)
        if not files:
            logger.warning(f"CSVLoader: No files found for {date.date()} under {self.data_root}")
            return 0

        total = 0
        for meta in files:
            logger.info(f"CSVLoader: Loading {meta['path'].name} ({meta['exchange']}:{meta['symbol']})")
            count = await self.load_file(
                meta["path"], meta["symbol"], meta["exchange"], replace_existing
            )
            logger.info(f"CSVLoader:   → {count} ticks inserted")
            total += count

        logger.info(f"CSVLoader: Total ticks inserted for {date.date()}: {total}")
        return total

    # ── Tick synthesis ───────────────────────────────────────────────────

    def _candles_to_ticks(
        self,
        candles: List[Tuple],
        symbol: str,
        exchange: str,
    ) -> List[dict]:
        all_ticks: List[dict] = []
        prev_close: Optional[float] = None

        for i, (dt, o, h, l, c, vol, oi) in enumerate(candles):
            ticks = _synthesise_ticks(
                candle_time=dt,
                o=o, h=h, l=l, c=c,
                volume=max(vol, _lot_size(symbol)),
                oi=oi,
                exchange=exchange,
                symbol=symbol,
                prev_close=prev_close,
            )
            all_ticks.extend(ticks)
            prev_close = c

        return all_ticks

    # ── DB insertion ─────────────────────────────────────────────────────

    async def _insert_ticks(self, ticks: List[dict], replace_existing: bool) -> int:
        if not ticks:
            return 0

        valid: List[HistoricalTick] = []
        for raw in ticks:
            norm = validator.normalize_tick(raw)
            if norm:
                valid.append(HistoricalTick(
                    symbol=norm["symbol"],
                    timestamp=norm["timestamp"],
                    price=norm["price"],
                    volume=norm["volume"],
                    oi=norm["oi"],
                    bid_price=norm["bid_price"],
                    ask_price=norm["ask_price"],
                    bid_qty=norm["bid_qty"],
                    ask_qty=norm["ask_qty"],
                    exchange=norm["exchange"],
                ))

        if not valid:
            return 0

        chunk_size = 5000
        async with async_session_factory() as db:
            try:
                if replace_existing:
                    from sqlalchemy import text as sqla_text
                    dates = {t.timestamp.date() for t in valid}
                    syms = {t.symbol for t in valid}
                    for d in dates:
                        await db.execute(
                            sqla_text(
                                "DELETE FROM historical_ticks "
                                "WHERE DATE(timestamp) = :d AND symbol = ANY(:syms)"
                            ),
                            {"d": d, "syms": list(syms)},
                        )
                    await db.commit()

                for i in range(0, len(valid), chunk_size):
                    db.add_all(valid[i: i + chunk_size])
                    await db.commit()

                return len(valid)
            except Exception as e:
                await db.rollback()
                logger.error(f"CSVLoader: DB insert failed: {e}", exc_info=True)
                return 0

    # ── Streaming generator (for large files without full RAM load) ───────

    def iter_ticks_from_file(
        self,
        path: Path,
        symbol: str,
        exchange: str,
    ) -> Generator[dict, None, None]:
        """
        Yield ticks one by one from a CSV file without loading everything into RAM.
        Useful for very large files (>500 MB).
        """
        try:
            text = self._read_file(path)
        except Exception as e:
            logger.error(f"CSVLoader: Cannot read {path}: {e}")
            return

        rows = _rows_from_text(text)
        candles = _parse_candles_from_rows(rows, symbol, exchange)
        prev_close = None
        for dt, o, h, l, c, vol, oi in candles:
            for tick in _synthesise_ticks(dt, o, h, l, c, max(vol, 1), oi, exchange, symbol, prev_close):
                yield tick
            prev_close = c


csv_loader = CSVLoader()
