"""Orchestrates a one-off/periodic import of REAL historical EOD candles
from Zebu (MYNT API) into price_data, using the exact same versioned-upsert
pipeline (`save_records_to_db`) as the mock NSE/BSE bhavcopy ingestion.

This never runs as a live feed: it's triggered manually (or periodically)
by an admin action, fetches historical daily bars for the platform's seed
symbol universe, and writes them once. The internal Brownian-bridge tick
simulator then generates ticks from these real anchors on subsequent days,
exactly as it already does for mock-seeded data — no other part of the
pipeline changes.
"""
import asyncio
import csv
import io
import logging
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5


async def _resolve_nse_tokens(client, symbols: List[str]) -> Dict[str, str]:
    """Download the NSE symbol master and map bare TradingSymbol (without
    the "-EQ" suffix) -> Zebu instrument token, for the given symbol set."""
    raw = await asyncio.to_thread(client.download_symbol_master, "NSE")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".txt")]
        if not names:
            raise RuntimeError("NSE symbol master zip contained no .txt file")
        with z.open(names[0]) as f:
            text = f.read().decode("utf-8", errors="ignore")

    wanted = set(symbols)
    token_map: Dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        trading_symbol = str(row.get("TradingSymbol") or "").strip()
        bare = trading_symbol[:-3] if trading_symbol.endswith("-EQ") else trading_symbol
        if bare in wanted and bare not in token_map:
            token = str(row.get("Token") or "").strip()
            if token:
                token_map[bare] = token

    missing = wanted - set(token_map)
    if missing:
        logger.warning(f"Zebu symbol master: no token found for {len(missing)} symbols: {sorted(missing)[:20]}...")
    return token_map


def _collapse_to_daily_bars(candles: list) -> Dict[date, dict]:
    """TPSeries returns fine-grained bars; collapse to one true daily OHLCV
    bar per calendar day (open=first, high=max, low=min, close=last,
    volume=sum) since that's all price_data / the simulator seed needs."""
    from datetime import datetime

    by_day: Dict[date, list] = defaultdict(list)
    for c in candles:
        raw_time = c.get("time")
        if not raw_time:
            continue
        dt = None
        # Per official docs (zebumyntapi.web.app/Base/MarketQuotes/), TPSeries
        # "time" is "DD/MM/CCYY hh:mm:ss" — try that first, then fall back to
        # other formats observed across Noren-family brokers just in case.
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(raw_time, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(raw_time)
            except ValueError:
                continue
        by_day[dt.date()].append(c)

    bars: Dict[date, dict] = {}
    for day, rows in by_day.items():
        rows.sort(key=lambda r: r.get("time") or "")
        bars[day] = {
            "open": rows[0]["open"],
            "high": max(r["high"] for r in rows),
            "low": min(r["low"] for r in rows),
            "close": rows[-1]["close"],
            "volume": sum(r["volume"] for r in rows),
        }
    return bars


_FETCH_CONCURRENCY = 12  # bounded parallel TPSeries calls; ~100 symbols
# sequentially at up to 15s/call could take 20+ minutes and look "stuck" —
# fetching concurrently keeps a full import to roughly total_time / this
# factor instead.


async def run_zebu_backfill(client, days: int, progress_cb=None) -> Dict[str, int]:
    """Given an already-logged-in ZebuClient, resolve tokens for the seed
    symbol universe, pull `days` trailing trading days of real EOD history
    per symbol, and upsert into price_data.

    TPSeries fetches (network I/O, one blocking `requests` call per symbol
    via `asyncio.to_thread`) run with bounded concurrency so ~100 symbols
    don't serialize into a many-minute wait. DB writes stay sequential on a
    single AsyncSession, since SQLAlchemy sessions aren't safe for
    concurrent use — that part was never the bottleneck anyway.

    `progress_cb`, if given, is awaited as `progress_cb(done, total)` after
    each symbol's fetch completes, so a caller can persist live progress
    (e.g. for polling UI) instead of only a terminal state.

    Returns a dict with `rows_written`, `symbols_found` (had a resolvable
    Zebu instrument token), and `symbols_total` (the full seed universe) —
    a bare row count alone can't distinguish "0 rows because nothing
    changed vs. mock data" from "0 rows because token resolution silently
    found nothing," so callers need all three to show a trustworthy result.
    """
    from data_layer.ingestion.nse_bhavcopy import _NSE_MOCK_ANCHORS
    from data_layer.ingestion.run_ingestion import save_records_to_db
    from database.connection import async_session

    symbols = sorted(_NSE_MOCK_ANCHORS.keys())
    token_map = await _resolve_nse_tokens(client, symbols)

    end_date = date.today()
    start_date = end_date - timedelta(days=int(days * 1.6) + 10)  # pad for weekends/holidays

    semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def _fetch(symbol: str, token: str):
        async with semaphore:
            try:
                return symbol, await asyncio.to_thread(
                    client.get_time_price_series,
                    exchange="NSE", token=token, start=start_date, end=end_date,
                )
            except Exception as e:
                logger.warning(f"Zebu TPSeries failed for {symbol} (token={token}): {e}")
                return symbol, None

    tasks = [asyncio.create_task(_fetch(symbol, token)) for symbol, token in token_map.items()]

    total_written = 0
    done = 0
    async with async_session() as db:
        for coro in asyncio.as_completed(tasks):
            symbol, candles = await coro
            done += 1
            if progress_cb is not None:
                try:
                    await progress_cb(done, len(tasks))
                except Exception:
                    logger.warning("Zebu import progress_cb raised — ignoring.", exc_info=True)

            if not candles:
                continue

            daily_bars = _collapse_to_daily_bars(candles)
            records = [
                {
                    "symbol": symbol,
                    "exchange": "NSE",
                    "segment": "EQ",
                    "market_timestamp": day,
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"],
                }
                for day, bar in daily_bars.items()
                if _is_trading_day(day)
            ]
            if not records:
                continue

            written = await save_records_to_db(db, records)
            total_written += written

        await db.commit()

    logger.info(
        f"Zebu historical import: {total_written} rows written across "
        f"{len(token_map)}/{len(symbols)} symbols (token resolved/total)"
    )
    return {
        "rows_written": total_written,
        "symbols_found": len(token_map),
        "symbols_total": len(symbols),
    }
