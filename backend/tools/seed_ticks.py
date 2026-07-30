#!/usr/bin/env python3
# seed_ticks.py - Comprehensive historical tick seeder for AlphaSync simulation
"""
Seeds the historical_ticks table with a FULL trading day of realistic
tick-by-tick data for:
  • NSE Indices  (^NSEI, ^NSEBANK, ^BSESN, ^NSMIDCP)
  • Nifty 50 large-caps (RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, …)
  • MCX Commodities (GOLD, SILVER, CRUDEOIL, NATURALGAS, COPPER)
  • NFO Futures (NIFTYFUT, BANKNIFTYFUT, top-4 stock futures)
  • NFO Options (NIFTY ATM ± 4 strikes CE/PE for the nearest expiry)

Intraday regime model
──────────────────────
  09:15–09:45  Opening burst      (vol × 2.5, random direction)
  09:45–10:30  Early trend        (vol × 1.8, slight upward bias)
  10:30–12:30  Normal session     (vol × 1.2)
  12:30–13:30  Lunch lull         (vol × 0.6, minimal movement)
  13:30–14:30  Post-lunch revival (vol × 1.0)
  14:30–15:00  Pre-close build    (vol × 1.4, upward bias)
  15:00–15:30  Closing bell       (vol × 1.8, random spikes)

Usage:
  python seed_ticks.py [days_ago]          # default: 1 (yesterday)
  python seed_ticks.py 0                   # today
  python seed_ticks.py 2                   # 2 days ago

The script is safe to re-run: it deletes existing ticks for the chosen date
before inserting new ones.
"""

import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import init_db, async_session_factory
from models.historical_ticks import HistoricalTick
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Full Symbol Catalogue
# ---------------------------------------------------------------------------

SYMBOLS: dict = {
    # ── NSE Indices ──────────────────────────────────────────────────────
    "^NSEI":            {"price": 22500.0,  "vol": 0.00012, "exchange": "NSE", "lot": 1,    "kind": "index"},
    "^NSEBANK":         {"price": 48000.0,  "vol": 0.00018, "exchange": "NSE", "lot": 1,    "kind": "index"},
    "^BSESN":           {"price": 74000.0,  "vol": 0.00012, "exchange": "NSE", "lot": 1,    "kind": "index"},
    "^NSMIDCP":         {"price": 10500.0,  "vol": 0.00020, "exchange": "NSE", "lot": 1,    "kind": "index"},
    # ── Nifty 50 (EQ) ────────────────────────────────────────────────────
    "RELIANCE.NS":      {"price": 2950.0,   "vol": 0.00035, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "TCS.NS":           {"price": 3850.0,   "vol": 0.00030, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "HDFCBANK.NS":      {"price": 1620.0,   "vol": 0.00038, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "INFY.NS":          {"price": 1490.0,   "vol": 0.00032, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "ICICIBANK.NS":     {"price": 1260.0,   "vol": 0.00040, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "SBIN.NS":          {"price":  830.0,   "vol": 0.00045, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "WIPRO.NS":         {"price":  480.0,   "vol": 0.00038, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "AXISBANK.NS":      {"price": 1180.0,   "vol": 0.00042, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "KOTAKBANK.NS":     {"price": 1780.0,   "vol": 0.00035, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "LT.NS":            {"price": 3600.0,   "vol": 0.00033, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "HCLTECH.NS":       {"price": 1620.0,   "vol": 0.00030, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "ASIANPAINT.NS":    {"price": 3100.0,   "vol": 0.00028, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "MARUTI.NS":        {"price":10800.0,   "vol": 0.00030, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "SUNPHARMA.NS":     {"price": 1480.0,   "vol": 0.00035, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "BAJFINANCE.NS":    {"price": 7200.0,   "vol": 0.00050, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "ADANIENT.NS":      {"price": 3200.0,   "vol": 0.00060, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "ADANIPORTS.NS":    {"price": 1380.0,   "vol": 0.00055, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "HINDUNILVR.NS":    {"price": 2650.0,   "vol": 0.00025, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "TITAN.NS":         {"price": 3500.0,   "vol": 0.00040, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "BHARTIARTL.NS":    {"price": 1560.0,   "vol": 0.00040, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "COALINDIA.NS":     {"price":  490.0,   "vol": 0.00048, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "JSWSTEEL.NS":      {"price":  920.0,   "vol": 0.00055, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "TATASTEEL.NS":     {"price":  175.0,   "vol": 0.00060, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "ITC.NS":           {"price":  480.0,   "vol": 0.00030, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "ONGC.NS":          {"price":  285.0,   "vol": 0.00050, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "M&M.NS":           {"price": 2500.0,   "vol": 0.00045, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "DRREDDY.NS":       {"price": 6800.0,   "vol": 0.00032, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "CIPLA.NS":         {"price": 1450.0,   "vol": 0.00038, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "EICHERMOT.NS":     {"price": 4400.0,   "vol": 0.00040, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    "BAJAJ-AUTO.NS":    {"price": 9500.0,   "vol": 0.00035, "exchange": "NSE", "lot": 1,    "kind": "equity"},
    # ── MCX Commodities ──────────────────────────────────────────────────
    "GOLD":             {"price": 72500.0,  "vol": 0.00025, "exchange": "MCX", "lot": 1,    "kind": "commodity"},
    "SILVER":           {"price": 91000.0,  "vol": 0.00035, "exchange": "MCX", "lot": 30,   "kind": "commodity"},
    "CRUDEOIL":         {"price":  6800.0,  "vol": 0.00060, "exchange": "MCX", "lot": 100,  "kind": "commodity"},
    "NATURALGAS":       {"price":   225.0,  "vol": 0.00080, "exchange": "MCX", "lot": 1250, "kind": "commodity"},
    "COPPER":           {"price":   870.0,  "vol": 0.00045, "exchange": "MCX", "lot": 2500, "kind": "commodity"},
    # ── NFO Index Futures ────────────────────────────────────────────────
    "NIFTYFUT":         {"price": 22550.0,  "vol": 0.00015, "exchange": "NFO", "lot": 25,   "kind": "future"},
    "BANKNIFTYFUT":     {"price": 48100.0,  "vol": 0.00020, "exchange": "NFO", "lot": 15,   "kind": "future"},
    # ── NFO Stock Futures ────────────────────────────────────────────────
    "RELIANCEFUT":      {"price": 2955.0,   "vol": 0.00040, "exchange": "NFO", "lot": 250,  "kind": "future"},
    "TCSFUT":           {"price": 3855.0,   "vol": 0.00035, "exchange": "NFO", "lot": 150,  "kind": "future"},
    # ── NFO Options (NIFTY – ATM ± 4 strikes @ 50 step) ─────────────────
    "NIFTY24JULCE22000": {"price":  620.0,  "vol": 0.00120, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULPE22000": {"price":   28.0,  "vol": 0.00200, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULCE22200": {"price":  430.0,  "vol": 0.00130, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULPE22200": {"price":   42.0,  "vol": 0.00190, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULCE22400": {"price":  255.0,  "vol": 0.00140, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULPE22400": {"price":   68.0,  "vol": 0.00180, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULCE22500": {"price":  185.0,  "vol": 0.00150, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULPE22500": {"price":   98.0,  "vol": 0.00170, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULCE22600": {"price":  125.0,  "vol": 0.00160, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULPE22600": {"price":  140.0,  "vol": 0.00160, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULCE22800": {"price":   55.0,  "vol": 0.00180, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULPE22800": {"price":  260.0,  "vol": 0.00140, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULCE23000": {"price":   18.0,  "vol": 0.00200, "exchange": "NFO", "lot": 25,   "kind": "option"},
    "NIFTY24JULPE23000": {"price":  420.0,  "vol": 0.00120, "exchange": "NFO", "lot": 25,   "kind": "option"},
    # ── BankNifty ATM options ─────────────────────────────────────────────
    "BANKNIFTY24JULCE48000": {"price": 240.0, "vol": 0.00150, "exchange": "NFO", "lot": 15, "kind": "option"},
    "BANKNIFTY24JULPE48000": {"price": 260.0, "vol": 0.00150, "exchange": "NFO", "lot": 15, "kind": "option"},
    "BANKNIFTY24JULCE48500": {"price": 110.0, "vol": 0.00180, "exchange": "NFO", "lot": 15, "kind": "option"},
    "BANKNIFTY24JULPE47500": {"price": 115.0, "vol": 0.00180, "exchange": "NFO", "lot": 15, "kind": "option"},
}

# ---------------------------------------------------------------------------
# Intraday regime schedule
# ---------------------------------------------------------------------------

_REGIMES = [
    ((9, 15),  (0.0,    2.5)),  # open burst
    ((9, 45),  (0.0003, 1.8)),  # early trend
    ((10, 30), (0.0,    1.2)),  # normal
    ((12, 30), (0.0,    0.6)),  # lunch lull
    ((13, 30), (0.0,    1.0)),  # post-lunch
    ((14, 30), (0.0002, 1.4)),  # pre-close
    ((15, 0),  (0.0,    1.8)),  # closing bell
    ((15, 30), (0.0,    0.1)),  # closed
]


def _regime(t: datetime) -> tuple:
    hm = (t.hour, t.minute)
    selected = _REGIMES[0][1]
    for (rh, rm), params in _REGIMES:
        if hm >= (rh, rm):
            selected = params
    return selected


def _spread_pct(exchange: str, kind: str) -> float:
    return {
        ("NSE", "index"):     0.00008,
        ("NSE", "equity"):    0.00040,
        ("NFO", "future"):    0.00020,
        ("NFO", "option"):    0.00300,
        ("BFO", "future"):    0.00020,
        ("BFO", "option"):    0.00300,
        ("MCX", "commodity"): 0.00040,
    }.get((exchange, kind), 0.00050)


# ---------------------------------------------------------------------------
# Core seeding function
# ---------------------------------------------------------------------------

async def seed_historical_ticks(days_ago: int = 1) -> None:
    print("=" * 60)
    print("AlphaSync — Comprehensive Tick Seeder")
    print("=" * 60)
    print(f"Initializing database connection …")
    await init_db()

    # --- Choose target date (skip weekends) ---
    target_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    # Roll back further if it lands on a weekend
    while target_date.weekday() >= 5:
        target_date -= timedelta(days=1)

    start_time = target_date.replace(hour=9, minute=15, second=0, microsecond=0)
    end_time   = target_date.replace(hour=15, minute=30, second=0, microsecond=0)

    print(f"Target date  : {start_time.date()}")
    print(f"Window       : {start_time.strftime('%H:%M:%S')} → {end_time.strftime('%H:%M:%S')} UTC")
    print(f"Symbols      : {len(SYMBOLS)}")
    print()

    # Initialise per-symbol state
    states: dict = {}
    for sym, cfg in SYMBOLS.items():
        # Apply a small random open gap (± 0.5 %)
        gap = cfg["price"] * random.uniform(-0.005, 0.005)
        open_px = round(cfg["price"] + gap, 2)
        states[sym] = {
            "price":    open_px,
            "open":     open_px,
            "high":     open_px,
            "low":      open_px,
            "volume":   0,
            "oi":       50_000 if cfg["exchange"] in ("NFO", "MCX") else 0,
        }

    ticks_to_insert: list = []
    current_time = start_time
    market_drift = 0.0
    total = 0

    print("Generating ticks …", end="", flush=True)

    while current_time < end_time:
        drift_bias, vol_mult = _regime(current_time)

        # Step forward: faster at open/close, slower at lunch
        base_ms = 80 if vol_mult > 1.5 else (200 if vol_mult < 0.7 else 120)
        step_ms = random.randint(base_ms // 2, base_ms * 2)
        current_time += timedelta(milliseconds=step_ms)

        # Market-wide drift (mean-reverting)
        market_drift += random.normalvariate(drift_bias, 0.0001)
        market_drift = max(-0.015, min(0.015, market_drift))

        # Number of symbols ticking in this step (burst model)
        r = random.random()
        if r > 0.985:
            n = random.randint(8, 20)
        elif r > 0.88:
            n = random.randint(3, 8)
        else:
            n = random.randint(1, 2)

        syms = random.sample(list(SYMBOLS.keys()), min(n, len(SYMBOLS)))

        for sym in syms:
            cfg   = SYMBOLS[sym]
            state = states[sym]
            kind  = cfg["kind"]
            exch  = cfg["exchange"]
            lot   = cfg["lot"]
            base_vol = cfg["vol"]

            eff_vol = base_vol * vol_mult

            corr = 0.85 if kind == "index" else 0.55 if kind == "equity" else 0.45
            drift = market_drift * corr + random.normalvariate(0.0, eff_vol)

            old_px = state["price"]
            new_px = old_px * (1.0 + drift)

            # Price floors
            if kind == "option":
                new_px = max(0.05, round(new_px, 2))
            elif exch == "MCX":
                new_px = max(old_px * 0.90, round(new_px, 2))
            else:
                new_px = max(old_px * 0.95, round(new_px, 2))

            state["price"] = new_px
            state["high"]  = max(state["high"],  new_px)
            state["low"]   = min(state["low"],   new_px)

            # Spread
            sp_pct = _spread_pct(exch, kind)
            half_sp = max(0.05, round(new_px * sp_pct / 2.0, 2))
            bid = round(new_px - half_sp, 2)
            ask = round(new_px + half_sp, 2)

            bid_qty = random.randint(1, 25) * lot
            ask_qty = random.randint(1, 25) * lot

            # Volume
            if kind not in ("index",):
                state["volume"] += random.randint(1, 10) * lot

            # OI for derivatives
            if exch in ("NFO", "BFO", "MCX"):
                state["oi"] = max(0, state["oi"] + random.randint(-lot, lot))

            ticks_to_insert.append(HistoricalTick(
                symbol    = sym,
                timestamp = current_time,
                price     = Decimal(str(round(new_px, 2))),
                volume    = state["volume"],
                oi        = state["oi"],
                bid_price = Decimal(str(bid)),
                ask_price = Decimal(str(ask)),
                bid_qty   = bid_qty,
                ask_qty   = ask_qty,
                exchange  = exch,
            ))
            total += 1

        if total % 10_000 == 0:
            print(".", end="", flush=True)

    print()
    print(f"Generated {total:,} ticks across {len(SYMBOLS)} symbols.")
    print("Inserting into database …")

    chunk_size = 5_000
    async with async_session_factory() as db:
        try:
            # Clear existing data for this date
            await db.execute(
                text("DELETE FROM historical_ticks WHERE DATE(timestamp) = :d"),
                {"d": start_time.date()},
            )
            await db.commit()
            print(f"Cleared existing ticks for {start_time.date()}")

            inserted = 0
            for i in range(0, len(ticks_to_insert), chunk_size):
                chunk = ticks_to_insert[i: i + chunk_size]
                db.add_all(chunk)
                await db.commit()
                inserted += len(chunk)
                pct = inserted * 100 // total
                print(f"  {inserted:,}/{total:,} ({pct}%) …", end="\r", flush=True)

            print(f"\n✓ Inserted {inserted:,} ticks for {start_time.date()}")
            print()
            print("Summary by symbol:")
            for sym, state in states.items():
                exch = SYMBOLS[sym]["exchange"]
                print(f"  {sym:<30} open={state['open']:.2f}  close={state['price']:.2f}  "
                      f"hi={state['high']:.2f}  lo={state['low']:.2f}  vol={state['volume']:,}  [{exch}]")

        except Exception as e:
            await db.rollback()
            print(f"\n✗ Seeding failed: {e}")
            raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    days = 1
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print(f"Usage: python seed_ticks.py [days_ago]")
            sys.exit(1)

    asyncio.run(seed_historical_ticks(days_ago=days))
