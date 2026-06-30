# replay_engine.py - Ultra Tick Replay Engine for AlphaSync
import asyncio
import logging
import random
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Set, Callable, Optional, Any

from sqlalchemy import select, and_, func
from database.connection import async_session_factory
from models.historical_ticks import HistoricalTick
from core.simulation_clock import simulation_clock

logger = logging.getLogger(__name__)


class UltraTickReplayEngine:
    """
    The core simulation engine. It maintains the simulation session,
    schedules and replays ticks with high timing fidelity, and provides
    a high-fidelity fallback tick generator when no historical data is seeded.
    """

    def __init__(self):
        self._callbacks: List[Callable[[dict], Any]] = []
        self._subscribed_symbols: Set[str] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._speed = 1.0
        self._current_session_date: Optional[datetime] = None
        
        # State for dynamic tick generation (fallback mode)
        self._symbol_states: Dict[str, dict] = {}
        self._market_drift = 0.0  # Shared market factor to correlate stocks and indices

    def register_callback(self, callback: Callable[[dict], Any]) -> None:
        """Register a callback to receive ticks."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to ticks for a list of symbols."""
        for sym in symbols:
            clean_sym = str(sym).strip().upper()
            if clean_sym:
                self._subscribed_symbols.add(clean_sym)
                self._init_symbol_state(clean_sym)
        logger.info(f"ReplayEngine: Subscribed to {len(symbols)} symbols. Total: {len(self._subscribed_symbols)}")

    def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from ticks for a list of symbols."""
        for sym in symbols:
            clean_sym = str(sym).strip().upper()
            self._subscribed_symbols.discard(clean_sym)
        logger.info(f"ReplayEngine: Unsubscribed from {len(symbols)} symbols. Remaining: {len(self._subscribed_symbols)}")

    def set_speed(self, speed: float) -> None:
        """Change the replay speed multiplier (e.g. 1x, 2x, 5x)."""
        self._speed = max(0.1, speed)
        if simulation_clock.is_simulated:
            # Re-base the clock with the new speed
            simulation_clock.set_clock(simulation_clock.now(), self._speed)
        logger.info(f"ReplayEngine: Replay speed set to {self._speed}x")

    async def start(self) -> None:
        """Start the replay engine loop."""
        if self._running:
            return
        self._running = True
        
        # Select or randomize session date
        await self._setup_session()
        
        self._task = asyncio.create_task(self._replay_loop())
        logger.info("Ultra Tick Replay Engine started")

    async def stop(self) -> None:
        """Stop the replay engine loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        simulation_clock.disable()
        logger.info("Ultra Tick Replay Engine stopped")

    async def _setup_session(self) -> None:
        """Query available dates in the DB or default to a random date."""
        session_date = None
        async with async_session_factory() as db:
            try:
                # Find unique dates in historical_ticks
                stmt = select(func.date(HistoricalTick.timestamp)).distinct()
                res = await db.execute(stmt)
                dates = res.scalars().all()
                if dates:
                    # Select a random date from the database
                    selected = random.choice(dates)
                    session_date = datetime.combine(selected, datetime.min.time(), tzinfo=timezone.utc)
                    logger.info(f"ReplayEngine: Selected historical session date from DB: {selected}")
            except Exception as e:
                logger.debug(f"ReplayEngine: Could not fetch dates from DB: {e}")

        if not session_date:
            # Fallback/dynamic mode: Choose a random recent day
            random_days_ago = random.randint(1, 30)
            target_date = datetime.now(timezone.utc) - timedelta(days=random_days_ago)
            session_date = datetime(target_date.year, target_date.month, target_date.day, 9, 15, 0, tzinfo=timezone.utc)
            logger.info(f"ReplayEngine: Empty database. Starting in Dynamic Fallback Mode on date: {session_date.date()}")

        self._current_session_date = session_date
        # Initialize simulation clock starting at 9:15 AM on the session date
        simulation_clock.set_clock(session_date, self._speed)

    async def _replay_loop(self) -> None:
        """Main replay loop that dispatches ticks from DB or generates them dynamically."""
        try:
            # Check if we have ticks for the current session in the database
            has_db_ticks = False
            if self._current_session_date:
                async with async_session_factory() as db:
                    stmt = select(HistoricalTick.id).where(
                        and_(
                            func.date(HistoricalTick.timestamp) == self._current_session_date.date()
                        )
                    ).limit(1)
                    res = await db.execute(stmt)
                    has_db_ticks = res.scalar_one_or_none() is not None

            if has_db_ticks:
                await self._replay_db_ticks()
            else:
                await self._run_dynamic_generator()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"ReplayEngine: Error in replay loop: {e}", exc_info=True)
            # Re-try after a short delay
            await asyncio.sleep(5)
            if self._running:
                self._task = asyncio.create_task(self._replay_loop())

    async def _replay_db_ticks(self) -> None:
        """Replay ticks from the database, preserving timing and order."""
        logger.info(f"ReplayEngine: Replaying ticks from DB for date {self._current_session_date.date()}")
        
        # Load all ticks for the day
        async with async_session_factory() as db:
            stmt = select(HistoricalTick).where(
                and_(
                    func.date(HistoricalTick.timestamp) == self._current_session_date.date()
                )
            ).order_by(HistoricalTick.timestamp.asc())
            res = await db.execute(stmt)
            ticks: List[HistoricalTick] = res.scalars().all()

        if not ticks:
            logger.warning("ReplayEngine: No ticks found in DB for the selected date. Falling back to dynamic generator.")
            await self._run_dynamic_generator()
            return

        # Start replay
        start_sim_time = ticks[0].timestamp
        simulation_clock.set_clock(start_sim_time, self._speed)
        
        last_tick_sim_time = start_sim_time
        
        for tick in ticks:
            if not self._running:
                break

            # Calculate simulation time difference
            time_diff = (tick.timestamp - last_tick_sim_time).total_seconds()
            if time_diff > 0:
                # Sleep in real-time (scaled by speed)
                real_sleep = time_diff / self._speed
                # Cap sleep to prevent huge gaps if there was a long halt (e.g. overnight or lunch)
                if real_sleep > 5.0:
                    real_sleep = 0.1
                    # Re-align clock
                    simulation_clock.set_clock(tick.timestamp, self._speed)
                
                await asyncio.sleep(real_sleep)

            # Dispatch tick
            tick_dict = {
                "symbol": tick.symbol,
                "timestamp": tick.timestamp.isoformat(),
                "price": float(tick.price),
                "volume": tick.volume,
                "oi": tick.oi or 0,
                "bid_price": float(tick.bid_price) if tick.bid_price else None,
                "ask_price": float(tick.ask_price) if tick.ask_price else None,
                "bid_qty": tick.bid_qty or 0,
                "ask_qty": tick.ask_qty or 0,
                "exchange": tick.exchange,
            }
            
            self._dispatch_tick(tick_dict)
            last_tick_sim_time = tick.timestamp

        # Session complete. Rotate/restart
        logger.info("ReplayEngine: Session complete. Rotating to a new session.")
        await self._setup_session()
        if self._running:
            await self._replay_loop()

    async def _run_dynamic_generator(self) -> None:
        """Fallback: Generates high-fidelity simulated ticks on-the-fly."""
        logger.info("ReplayEngine: Running in High-Fidelity Dynamic Generator Mode")
        
        while self._running:
            # Replay engine sleeps a small interval (e.g., 50ms to 150ms in real time)
            # and generates ticks for a subset of subscribed symbols.
            real_sleep = random.uniform(0.02, 0.1)
            await asyncio.sleep(real_sleep)
            
            if not self._subscribed_symbols:
                continue

            # Simulation time updates
            sim_now = simulation_clock.now()

            # Determine number of ticks to generate in this burst
            # Volatility bursts: occasionally generate more ticks
            burst_chance = random.random()
            if burst_chance > 0.98:
                num_ticks = random.randint(5, 15)  # Volatility burst!
            elif burst_chance > 0.85:
                num_ticks = random.randint(2, 5)
            else:
                num_ticks = 1

            # Update market-wide drift factor
            self._market_drift += random.normalvariate(0, 0.0002)
            self._market_drift = max(-0.02, min(0.02, self._market_drift)) # Cap market drift

            # Select random subscribed symbols
            active_symbols = list(self._subscribed_symbols)
            symbols_to_update = random.sample(active_symbols, min(num_ticks, len(active_symbols)))

            for symbol in symbols_to_update:
                tick = self._generate_dynamic_tick(symbol, sim_now)
                self._dispatch_tick(tick)

    def _init_symbol_state(self, symbol: str) -> None:
        """Initialize reference prices and parameters for a symbol."""
        if symbol in self._symbol_states:
            return

        # Base prices based on popular stocks or indices
        base_price = 100.0
        exchange = "NSE"
        
        if symbol == "^NSEI":
            base_price = 22000.0
        elif symbol == "^NSEBANK":
            base_price = 47000.0
        elif symbol == "^BSESN":
            base_price = 72000.0
        elif "RELIANCE" in symbol:
            base_price = 2500.0
        elif "TCS" in symbol:
            base_price = 3800.0
        elif "HDFCBANK" in symbol:
            base_price = 1450.0
        elif "INFY" in symbol:
            base_price = 1500.0
        elif "SBIN" in symbol:
            base_price = 750.0
        elif symbol in ("GOLD", "SILVER", "CRUDEOIL"):
            exchange = "MCX"
            if symbol == "GOLD":
                base_price = 65000.0
            elif symbol == "SILVER":
                base_price = 72000.0
            else:
                base_price = 6500.0
        elif "FUT" in symbol or "CE" in symbol or "PE" in symbol:
            exchange = "NFO"
            # Derivative: try to inherit base price from underlying
            underlying = symbol.split("2")[0].split("3")[0].split("4")[0].split("5")[0].split("6")[0]
            if underlying == "NIFTY":
                base_price = 22000.0
            elif underlying == "BANKNIFTY":
                base_price = 47000.0
            else:
                base_price = 500.0
        else:
            # General random price between 100 and 2000
            random.seed(symbol)
            base_price = random.uniform(100.0, 2000.0)
            random.seed() # reset seed

        # Volatility parameter (standard deviation of percent return per tick)
        volatility = 0.0005
        if symbol.startswith("^"):
            volatility = 0.00015  # Indices are less volatile
        elif exchange == "NFO":
            volatility = 0.0015   # Options/Futures are highly volatile

        self._symbol_states[symbol] = {
            "price": base_price,
            "open": base_price,
            "high": base_price,
            "low": base_price,
            "close": base_price,
            "volume": 0,
            "oi": 10000 if exchange == "NFO" else 0,
            "volatility": volatility,
            "exchange": exchange,
            "last_update": time.time()
        }

    def _generate_dynamic_tick(self, symbol: str, sim_now: datetime) -> dict:
        """Generate a single realistic tick for a symbol using a random walk."""
        state = self._symbol_states[symbol]
        
        # Determine drift and volatility
        vol = state["volatility"]
        
        # Correlate with market drift: index stocks move with the market
        market_correlation = 0.5 if not symbol.startswith("^") else 0.8
        stock_drift = (self._market_drift * market_correlation) + random.normalvariate(0, vol)
        
        # Calculate new price
        old_price = state["price"]
        new_price = old_price * (1.0 + stock_drift)
        new_price = round(new_price, 2)
        if new_price <= 0.05:
            new_price = 0.05

        # Update OHLC
        if new_price > state["high"]:
            state["high"] = new_price
        if new_price < state["low"]:
            state["low"] = new_price
        state["price"] = new_price

        # Bid/Ask order book simulation
        spread_pct = 0.0005 if not symbol.startswith("^") else 0.0001
        spread = max(0.05, round(new_price * spread_pct, 2))
        
        # Bid is slightly below price, Ask is slightly above
        half_spread = round(spread / 2.0, 2)
        if half_spread <= 0:
            half_spread = 0.05
        bid_price = round(new_price - half_spread, 2)
        ask_price = round(new_price + half_spread, 2)

        # Bid/Ask quantities
        bid_qty = random.randint(100, 5000)
        ask_qty = random.randint(100, 5000)

        # Traded volume increment
        volume_inc = random.randint(10, 500)
        if symbol.startswith("^"):
            volume_inc = 0 # Spot indices have no volume
        state["volume"] += volume_inc

        # Open Interest increment (for derivatives)
        if state["exchange"] == "NFO":
            state["oi"] += random.randint(-50, 50)
            state["oi"] = max(1000, state["oi"])

        return {
            "symbol": symbol,
            "timestamp": sim_now.isoformat(),
            "price": new_price,
            "volume": state["volume"],
            "oi": state["oi"],
            "bid_price": bid_price,
            "ask_price": ask_price,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "exchange": state["exchange"],
        }

    def _dispatch_tick(self, tick: dict) -> None:
        """Send the tick to all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(f"ReplayEngine: Callback error: {e}")


# Global singleton instance
replay_engine = UltraTickReplayEngine()
