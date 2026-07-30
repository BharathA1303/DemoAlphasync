# replay_engine.py - Ultra Tick Replay Engine with 3-tier loading
"""
Three-tier simulation pipeline
────────────────────────────────────────────────────────────────────────────
Tier 1 – Historical Database (PostgreSQL historical_ticks)
Tier 2 – Replay Buffer Loader  (loads next 60 s of ticks into RAM queue)
Tier 3 – In-Memory Priority Queue  (chronological min-heap)
Tier 4 – Ultra-Precise Scheduler   (real-sleep scaled by speed)
Tier 5 – Market Publisher  (routes to QuoteCoordinator / EventBus)

If the DB is empty the engine falls back to the High-Fidelity Dynamic
Generator which produces realistic intraday microstructure for every
subscribed symbol across EQ, F&O and MCX.

Multi-user note
───────────────
All users share a single replay engine. The engine maintains the union of
all active subscriptions; individual filtering happens at the WebSocket layer.
"""

import asyncio
import logging
import math
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

from market_data.replay.simulation_clock import simulation_clock
from market_data.replay.session_manager import session_manager, MarketState
from market_data.replay.tick_queue import tick_queue
from market_data.replay.replay_scheduler import replay_scheduler
from market_data.replay.market_publisher import market_publisher
from market_data.storage.tick_repository import tick_repository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Full symbol catalogue with realistic reference data
# ---------------------------------------------------------------------------

# fmt: off
SYMBOL_CATALOGUE: Dict[str, dict] = {
    # ── NSE Indices ──────────────────────────────────────────────────────
    "^NSEI":         {"price": 22500.0, "vol": 0.00012, "exchange": "NSE", "lot": 1,  "kind": "index"},
    "^NSEBANK":      {"price": 48000.0, "vol": 0.00018, "exchange": "NSE", "lot": 1,  "kind": "index"},
    "^BSESN":        {"price": 74000.0, "vol": 0.00012, "exchange": "NSE", "lot": 1,  "kind": "index"},
    "^NSMIDCP":      {"price": 10500.0, "vol": 0.00020, "exchange": "NSE", "lot": 1,  "kind": "index"},
    "^CNXIT":        {"price": 34000.0, "vol": 0.00015, "exchange": "NSE", "lot": 1,  "kind": "index"},
    # ── Nifty 50 constituents ───────────────────────────────────────────
    "RELIANCE.NS":   {"price": 2950.0,  "vol": 0.00035, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "TCS.NS":        {"price": 3850.0,  "vol": 0.00030, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "HDFCBANK.NS":   {"price": 1620.0,  "vol": 0.00038, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "INFY.NS":       {"price": 1490.0,  "vol": 0.00032, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "ICICIBANK.NS":  {"price": 1260.0,  "vol": 0.00040, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "SBIN.NS":       {"price":  830.0,  "vol": 0.00045, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "WIPRO.NS":      {"price":  480.0,  "vol": 0.00038, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "AXISBANK.NS":   {"price": 1180.0,  "vol": 0.00042, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "KOTAKBANK.NS":  {"price": 1780.0,  "vol": 0.00035, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "LT.NS":         {"price": 3600.0,  "vol": 0.00033, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "HCLTECH.NS":    {"price": 1620.0,  "vol": 0.00030, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "ASIANPAINT.NS": {"price": 3100.0,  "vol": 0.00028, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "MARUTI.NS":     {"price":10800.0,  "vol": 0.00030, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "SUNPHARMA.NS":  {"price": 1480.0,  "vol": 0.00035, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "ONGC.NS":       {"price":  285.0,  "vol": 0.00050, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "NTPC.NS":       {"price":  370.0,  "vol": 0.00045, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "POWERGRID.NS":  {"price":  330.0,  "vol": 0.00040, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "BAJFINANCE.NS": {"price": 7200.0,  "vol": 0.00050, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "BAJAJFINSV.NS": {"price": 1620.0,  "vol": 0.00048, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "ADANIENT.NS":   {"price": 3200.0,  "vol": 0.00060, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "ADANIPORTS.NS": {"price": 1380.0,  "vol": 0.00055, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "HINDUNILVR.NS": {"price": 2650.0,  "vol": 0.00025, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "NESTLEIND.NS":  {"price":24500.0,  "vol": 0.00022, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "TITAN.NS":      {"price": 3500.0,  "vol": 0.00040, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "ULTRACEMCO.NS": {"price": 9800.0,  "vol": 0.00035, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "GRASIM.NS":     {"price": 2350.0,  "vol": 0.00038, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "TECHM.NS":      {"price": 1380.0,  "vol": 0.00042, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "DRREDDY.NS":    {"price": 6800.0,  "vol": 0.00032, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "CIPLA.NS":      {"price": 1450.0,  "vol": 0.00038, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "DIVISLAB.NS":   {"price": 4800.0,  "vol": 0.00030, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "BHARTIARTL.NS": {"price": 1560.0,  "vol": 0.00040, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "COALINDIA.NS":  {"price":  490.0,  "vol": 0.00048, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "JSWSTEEL.NS":   {"price":  920.0,  "vol": 0.00055, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "TATASTEEL.NS":  {"price":  175.0,  "vol": 0.00060, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "HINDALCO.NS":   {"price":  680.0,  "vol": 0.00055, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "EICHERMOT.NS":  {"price": 4400.0,  "vol": 0.00040, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "BAJAJ-AUTO.NS": {"price": 9500.0,  "vol": 0.00035, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "HEROMOTOCO.NS": {"price": 5200.0,  "vol": 0.00035, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "M&M.NS":        {"price": 2500.0,  "vol": 0.00045, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "TATACONSUM.NS": {"price": 1100.0,  "vol": 0.00040, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "ITC.NS":        {"price":  480.0,  "vol": 0.00030, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "BPCL.NS":       {"price":  640.0,  "vol": 0.00055, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "INDUSINDBK.NS": {"price": 1480.0,  "vol": 0.00055, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "APOLLOHOSP.NS": {"price": 6900.0,  "vol": 0.00038, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "SBILIFE.NS":    {"price": 1680.0,  "vol": 0.00038, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    "HDFCLIFE.NS":   {"price":  680.0,  "vol": 0.00038, "exchange": "NSE", "lot": 1,  "kind": "equity"},
    # ── NSE Futures (NFO) ───────────────────────────────────────────────
    "NIFTYFUT":      {"price": 22550.0, "vol": 0.00015, "exchange": "NFO", "lot": 25, "kind": "future"},
    "BANKNIFTYFUT":  {"price": 48100.0, "vol": 0.00020, "exchange": "NFO", "lot": 15, "kind": "future"},
    "FINNIFTYFUT":   {"price": 23800.0, "vol": 0.00018, "exchange": "NFO", "lot": 40, "kind": "future"},
    "RELIANCEFUT":   {"price": 2955.0,  "vol": 0.00040, "exchange": "NFO", "lot": 250,"kind": "future"},
    "TCSFUT":        {"price": 3855.0,  "vol": 0.00035, "exchange": "NFO", "lot": 150,"kind": "future"},
    "HDFCBANKFUT":   {"price": 1625.0,  "vol": 0.00042, "exchange": "NFO", "lot": 550,"kind": "future"},
    "SBINFUT":       {"price":  832.0,  "vol": 0.00048, "exchange": "NFO", "lot": 1500,"kind": "future"},
    # ── NSE Options (NFO) – selected strikes ────────────────────────────
    "NIFTY24JULCE22500": {"price":  185.0, "vol": 0.0012, "exchange": "NFO", "lot": 25, "kind": "option"},
    "NIFTY24JULPE22500": {"price":  210.0, "vol": 0.0012, "exchange": "NFO", "lot": 25, "kind": "option"},
    "NIFTY24JULCE23000": {"price":   55.0, "vol": 0.0018, "exchange": "NFO", "lot": 25, "kind": "option"},
    "NIFTY24JULPE22000": {"price":   48.0, "vol": 0.0018, "exchange": "NFO", "lot": 25, "kind": "option"},
    "BANKNIFTY24JULCE48000": {"price": 240.0,"vol": 0.0015,"exchange": "NFO","lot": 15,"kind": "option"},
    "BANKNIFTY24JULPE48000": {"price": 260.0,"vol": 0.0015,"exchange": "NFO","lot": 15,"kind": "option"},
    # ── BSE F&O (BFO) ───────────────────────────────────────────────────
    "SENSEXFUT":     {"price": 74150.0, "vol": 0.00013, "exchange": "BFO", "lot": 10, "kind": "future"},
    "SENSEX24JULCE74000": {"price": 310.0,"vol": 0.0013,"exchange": "BFO","lot": 10,"kind": "option"},
    # ── MCX Commodities ─────────────────────────────────────────────────
    "GOLD":          {"price": 72500.0, "vol": 0.00025, "exchange": "MCX", "lot": 1,    "kind": "commodity"},
    "GOLDM":         {"price": 72520.0, "vol": 0.00025, "exchange": "MCX", "lot": 10,   "kind": "commodity"},
    "SILVER":        {"price": 91000.0, "vol": 0.00035, "exchange": "MCX", "lot": 30,   "kind": "commodity"},
    "SILVERM":       {"price": 91050.0, "vol": 0.00035, "exchange": "MCX", "lot": 5000, "kind": "commodity"},
    "CRUDEOIL":      {"price":  6800.0, "vol": 0.00060, "exchange": "MCX", "lot": 100,  "kind": "commodity"},
    "NATURALGAS":    {"price":   225.0, "vol": 0.00080, "exchange": "MCX", "lot": 1250, "kind": "commodity"},
    "COPPER":        {"price":   870.0, "vol": 0.00045, "exchange": "MCX", "lot": 2500, "kind": "commodity"},
    "ZINC":          {"price":   265.0, "vol": 0.00050, "exchange": "MCX", "lot": 5000, "kind": "commodity"},
    "LEAD":          {"price":   195.0, "vol": 0.00050, "exchange": "MCX", "lot": 5000, "kind": "commodity"},
    "ALUMINIUM":     {"price":   245.0, "vol": 0.00045, "exchange": "MCX", "lot": 5000, "kind": "commodity"},
    "NICKEL":        {"price":  1960.0, "vol": 0.00060, "exchange": "MCX", "lot": 1500, "kind": "commodity"},
}
# fmt: on

# Intraday regime schedule (hour, minute) → (drift_bias, volatility_multiplier)
# Models: open volatility burst, mid-morning trend, lunch lull, closing rally
_INTRADAY_REGIMES = [
    ((9, 15),  (0.0,   2.5)),   # open burst – very high vol, no bias
    ((9, 45),  (0.0003, 1.8)),  # early trend
    ((10, 30), (0.0,   1.2)),   # normal
    ((12, 30), (0.0,   0.6)),   # lunch dip – low vol
    ((13, 30), (0.0,   1.0)),   # post-lunch
    ((14, 30), (0.0002,1.4)),   # pre-close buildup
    ((15, 00), (0.0,   1.8)),   # closing volatility
    ((15, 30), (0.0,   0.3)),   # market closed – almost no movement
]


def _regime(sim_now: datetime) -> tuple:
    """Return (drift_bias, vol_multiplier) for the current simulated time."""
    t = (sim_now.hour, sim_now.minute)
    selected = _INTRADAY_REGIMES[0][1]
    for (rh, rm), params in _INTRADAY_REGIMES:
        if t >= (rh, rm):
            selected = params
    return selected


def _spread_pct(exchange: str, kind: str) -> float:
    spreads = {
        ("NSE", "index"):     0.00008,
        ("NSE", "equity"):    0.00040,
        ("NFO", "future"):    0.00020,
        ("NFO", "option"):    0.00200,
        ("BFO", "future"):    0.00020,
        ("BFO", "option"):    0.00200,
        ("MCX", "commodity"): 0.00040,
    }
    return spreads.get((exchange, kind), 0.00050)


class UltraTickReplayEngine:
    """
    Coordinates the entire simulation runtime.

    Key improvements over previous version
    ────────────────────────────────────────
    • Full 50+ symbol catalogue (EQ, F&O, MCX)
    • Realistic intraday regimes (open burst, lunch lull, close rally)
    • Multi-user: union of all subscriptions, no per-user engine instances
    • Graceful day-end: wraps to next session without crashing
    • Dynamic generator never stalls when queue is empty
    • Price floors by asset class prevent nonsensical ticks
    """

    def __init__(self):
        self._running = False
        self._loader_task: Optional[asyncio.Task] = None
        self._dynamic_task: Optional[asyncio.Task] = None

        # Per-symbol state for dynamic generator
        self._symbol_states: Dict[str, dict] = {}
        self._market_drift = 0.0  # shared market-wide factor

        # Union of all active subscriptions across all connected users
        self._subscribed_symbols: Set[str] = set()

    # ── Public API ───────────────────────────────────────────────────────

    def subscribe(self, symbols: List[str]) -> None:
        for sym in symbols:
            clean = sym.strip().upper()
            if clean:
                self._subscribed_symbols.add(clean)
                self._init_symbol_state(clean)
        logger.info(f"ReplayEngine: +{len(symbols)} subscriptions → {len(self._subscribed_symbols)} total")

    def unsubscribe(self, symbols: List[str]) -> None:
        for sym in symbols:
            self._subscribed_symbols.discard(sym.strip().upper())
        logger.info(f"ReplayEngine: -{len(symbols)} subscriptions → {len(self._subscribed_symbols)} total")

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Pre-seed states for every known symbol so the dynamic generator
        # can produce ticks even before any user subscribes
        for sym in SYMBOL_CATALOGUE:
            self._init_symbol_state(sym)

        session_date = await session_manager.setup_session()
        available_dates = await tick_repository.get_available_dates()
        has_db_ticks = any(d.date() == session_date.date() for d in available_dates)

        replay_scheduler.set_callback(market_publisher.publish_tick)

        if has_db_ticks:
            logger.info("ReplayEngine: DB ticks found → 3-tier replay pipeline starting")
            await tick_queue.clear()
            self._loader_task = asyncio.create_task(self._buffer_loader_loop(session_date))
            await replay_scheduler.start()
        else:
            logger.info("ReplayEngine: No DB ticks → High-Fidelity Dynamic Generator starting")
            self._dynamic_task = asyncio.create_task(self._dynamic_generator_loop())

    async def stop(self) -> None:
        self._running = False
        for task in (self._loader_task, self._dynamic_task):
            if task and not task.done():
                task.cancel()
        await replay_scheduler.stop()
        await tick_queue.clear()
        simulation_clock.disable()
        logger.info("ReplayEngine: stopped")

    # ── Tier 2: Background Buffer Loader ─────────────────────────────────

    async def _buffer_loader_loop(self, session_date: datetime) -> None:
        current_sim_time = session_date
        chunk_seconds = 60

        try:
            while self._running:
                q_size = await tick_queue.size()
                if q_size < 1000:
                    end_range = current_sim_time + timedelta(seconds=chunk_seconds)

                    syms = list(self._subscribed_symbols) if self._subscribed_symbols else None
                    ticks = await tick_repository.get_ticks_for_range(
                        current_sim_time, end_range, syms
                    )

                    if ticks:
                        await tick_queue.push_batch(ticks)
                        logger.debug(f"ReplayEngine: buffered {len(ticks)} ticks ({current_sim_time.time()} → {end_range.time()})")

                    current_sim_time = end_range

                    # End of trading day → rotate to next session
                    if current_sim_time.hour >= 16:
                        logger.info("ReplayEngine: End of trading day → rotating session")
                        # Drain remaining queue before rotating
                        await asyncio.sleep(3.0)
                        await self.stop()
                        await asyncio.sleep(1.0)
                        self._running = True
                        await self.start()
                        return

                await asyncio.sleep(2.0)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"ReplayEngine: buffer loader error: {e}", exc_info=True)
            # Fall back to dynamic generator rather than dying
            if self._running:
                self._dynamic_task = asyncio.create_task(self._dynamic_generator_loop())

    # ── Tier 3: Fallback Dynamic Generator ───────────────────────────────

    async def _dynamic_generator_loop(self) -> None:
        """
        Generates realistic tick-by-tick data on-the-fly using an intraday
        regime model. Runs as the primary source when DB is empty.
        """
        while self._running:
            sim_now = simulation_clock.now()
            drift_bias, vol_mult = _regime(sim_now)

            # Tick frequency: higher near open/close, quiet at lunch
            base_sleep = random.uniform(0.03, 0.12)
            await asyncio.sleep(base_sleep / max(vol_mult, 0.1))

            # Market-wide drift random walk (mean-reverting)
            self._market_drift += random.normalvariate(drift_bias, 0.0001)
            self._market_drift = max(-0.015, min(0.015, self._market_drift))

            # Resolve active symbols: use subscriptions if any, else full catalogue
            active = list(self._subscribed_symbols) if self._subscribed_symbols else list(SYMBOL_CATALOGUE.keys())
            if not active:
                continue

            # Volatility bursts
            r = random.random()
            if r > 0.985:
                n = random.randint(6, 18)
            elif r > 0.88:
                n = random.randint(2, 6)
            else:
                n = 1

            symbols_to_tick = random.sample(active, min(n, len(active)))

            for sym in symbols_to_tick:
                tick = self._generate_dynamic_tick(sym, sim_now, vol_mult)
                await market_publisher.publish_tick(tick)

    # ── Symbol State Management ───────────────────────────────────────────

    def _init_symbol_state(self, symbol: str) -> None:
        if symbol in self._symbol_states:
            return

        meta = SYMBOL_CATALOGUE.get(symbol)
        if meta:
            base = meta["price"]
            vol = meta["vol"]
            exchange = meta["exchange"]
            kind = meta["kind"]
            lot = meta["lot"]
        else:
            # Unknown symbol: derive a deterministic price from the name hash
            h = hash(symbol) & 0xFFFF
            base = round(100.0 + (h % 4900), 2)
            exchange = "NSE"
            kind = "equity"
            vol = 0.00040
            lot = 1
            if any(x in symbol for x in ("FUT", "CE", "PE")):
                exchange = "NFO"
                kind = "option" if ("CE" in symbol or "PE" in symbol) else "future"
                vol = 0.00120
                lot = 25
            elif symbol in ("GOLD", "SILVER", "CRUDEOIL", "COPPER", "NATURALGAS"):
                exchange = "MCX"
                kind = "commodity"
                vol = 0.00045

        self._symbol_states[symbol] = {
            "price": base,
            "open":  base,
            "high":  base,
            "low":   base,
            "volume": 0,
            "oi": 50000 if exchange in ("NFO", "BFO", "MCX") else 0,
            "vol": vol,
            "exchange": exchange,
            "kind": kind,
            "lot": lot,
        }

    def _generate_dynamic_tick(self, symbol: str, sim_now: datetime, vol_mult: float = 1.0) -> dict:
        if symbol not in self._symbol_states:
            self._init_symbol_state(symbol)

        state = self._symbol_states[symbol]
        exchange = state["exchange"]
        kind = state["kind"]
        lot = state["lot"]
        base_vol = state["vol"]

        # Effective volatility with regime multiplier
        eff_vol = base_vol * vol_mult

        # Market correlation: indices highly correlated, stocks moderately
        corr = 0.85 if kind == "index" else 0.45 if kind in ("future", "option") else 0.55
        drift = self._market_drift * corr + random.normalvariate(0.0, eff_vol)

        old_price = state["price"]
        new_price = old_price * (1.0 + drift)

        # Price floor: options can go near-zero, others have a reasonable floor
        if kind == "option":
            new_price = max(0.05, round(new_price, 2))
        elif exchange == "MCX":
            new_price = max(old_price * 0.90, round(new_price, 2))
        else:
            new_price = max(old_price * 0.95, round(new_price, 2))

        # Update OHLC
        state["price"] = new_price
        state["high"] = max(state["high"], new_price)
        state["low"]  = min(state["low"],  new_price)

        # Bid/Ask spread
        sp_pct = _spread_pct(exchange, kind)
        half_sp = max(0.05, round(new_price * sp_pct / 2.0, 2))
        bid = round(new_price - half_sp, 2)
        ask = round(new_price + half_sp, 2)

        # Bid/ask quantities (in lots)
        bid_qty = random.randint(1, 25) * lot
        ask_qty = random.randint(1, 25) * lot

        # Volume increment
        if kind not in ("index",):
            state["volume"] += random.randint(1, 10) * lot

        # OI for derivatives and commodities
        if exchange in ("NFO", "BFO", "MCX"):
            state["oi"] = max(0, state["oi"] + random.randint(-lot, lot))

        return {
            "symbol":    symbol,
            "timestamp": sim_now.isoformat(),
            "price":     new_price,
            "volume":    state["volume"],
            "oi":        state["oi"],
            "bid_price": bid,
            "ask_price": ask,
            "bid_qty":   bid_qty,
            "ask_qty":   ask_qty,
            "exchange":  exchange,
        }


# Global singleton — shared across all users
replay_engine = UltraTickReplayEngine()
