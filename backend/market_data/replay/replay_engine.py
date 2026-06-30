# replay_engine.py - Ultra Tick Replay Engine with 3-tier loading
import asyncio
import logging
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Set, Callable, Optional, Any

from market_data.replay.simulation_clock import simulation_clock
from market_data.replay.session_manager import session_manager, MarketState
from market_data.replay.tick_queue import tick_queue
from market_data.replay.replay_scheduler import replay_scheduler
from market_data.replay.market_publisher import market_publisher
from market_data.storage.tick_repository import tick_repository

logger = logging.getLogger(__name__)

class UltraTickReplayEngine:
    """
    Coordinates the entire simulation runtime.
    Implements a three-tier pipeline:
      1. Historical Database (PostgreSQL)
      2. Replay Buffer Loader (loads next 60s of ticks into RAM in background)
      3. In-Memory Tick Queue (priority queue sorted by timestamp)
      4. Ultra Tick Scheduler (precise delays, scaled by speed)
      5. Market Publisher (delivers to QuoteCoordinator & EventBus)
    
    If no historical data is available, falls back to a high-fidelity dynamic generator.
    """

    def __init__(self):
        self._running = False
        self._loader_task: Optional[asyncio.Task] = None
        self._subscribed_symbols: Set[str] = set()
        
        # State for dynamic tick generation (fallback mode)
        self._symbol_states: Dict[str, dict] = {}
        self._market_drift = 0.0
        self._dynamic_task: Optional[asyncio.Task] = None

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

    async def start(self) -> None:
        """Start the replay engine, loader, and scheduler."""
        if self._running:
            return
        self._running = True

        # Initialize the session and simulation clock
        session_date = await session_manager.setup_session()
        
        # Check if we have ticks in the database for the selected date
        available_dates = await tick_repository.get_available_dates()
        has_db_ticks = any(d.date() == session_date.date() for d in available_dates)

        # Configure scheduler callback
        replay_scheduler.set_callback(market_publisher.publish_tick)

        if has_db_ticks:
            logger.info("ReplayEngine: Database ticks found. Starting 3-tier replay pipeline.")
            await tick_queue.clear()
            
            # Start the background buffer loader and the tick scheduler
            self._loader_task = asyncio.create_task(self._buffer_loader_loop(session_date))
            await replay_scheduler.start()
        else:
            logger.info("ReplayEngine: No ticks found. Starting High-Fidelity Dynamic Generator.")
            self._dynamic_task = asyncio.create_task(self._dynamic_generator_loop())

    async def stop(self) -> None:
        """Stop all replay tasks and the scheduler."""
        self._running = False
        
        if self._loader_task and not self._loader_task.done():
            self._loader_task.cancel()
            
        if self._dynamic_task and not self._dynamic_task.done():
            self._dynamic_task.cancel()
            
        await replay_scheduler.stop()
        await tick_queue.clear()
        simulation_clock.disable()
        logger.info("Ultra Tick Replay Engine stopped")

    # ── Tier 2: Background Buffer Loader ─────────────────────────────

    async def _buffer_loader_loop(self, session_date: datetime) -> None:
        """
        Periodically loads the next 60 seconds of ticks from PostgreSQL
        into the in-memory priority queue.
        """
        current_sim_time = session_date
        chunk_size_seconds = 60
        
        try:
            while self._running:
                # Check queue size
                q_size = await tick_queue.size()
                if q_size < 1000:  # Refill when queue is running low
                    start_range = current_sim_time
                    end_range = start_range + timedelta(seconds=chunk_size_seconds)
                    
                    logger.debug(f"ReplayEngine: Refilling tick buffer from DB for range: {start_range.time()} -> {end_range.time()}")
                    
                    # Fetch next chunk of ticks from database
                    ticks = await tick_repository.get_ticks_for_range(
                        start_time=start_range,
                        end_time=end_range,
                        symbols=list(self._subscribed_symbols) if self._subscribed_symbols else None
                    )
                    
                    if ticks:
                        await tick_queue.push_batch(ticks)
                        logger.debug(f"ReplayEngine: Buffered {len(ticks)} ticks into RAM queue.")
                    
                    # Advance the buffer window
                    current_sim_time = end_range
                    
                    # If we've reached the end of the trading day, rotate the session
                    if current_sim_time.hour >= 16:
                        logger.info("ReplayEngine: End of trading day reached. Rotating session.")
                        await self.stop()
                        await self.start()
                        break

                # Sleep in real-time before checking if we need to refill the buffer
                await asyncio.sleep(2.0)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"ReplayEngine: Error in buffer loader loop: {e}", exc_info=True)

    # ── Tier 3: Fallback Dynamic Generator ───────────────────────────

    async def _dynamic_generator_loop(self) -> None:
        """
        Fallback: Generates high-fidelity simulated ticks on-the-fly.
        """
        while self._running:
            real_sleep = random.uniform(0.02, 0.1)
            await asyncio.sleep(real_sleep)
            
            if not self._subscribed_symbols:
                continue

            sim_now = simulation_clock.now()
            
            # Volatility bursts
            burst_chance = random.random()
            if burst_chance > 0.98:
                num_ticks = random.randint(5, 15)
            elif burst_chance > 0.85:
                num_ticks = random.randint(2, 5)
            else:
                num_ticks = 1

            self._market_drift += random.normalvariate(0, 0.0002)
            self._market_drift = max(-0.02, min(0.02, self._market_drift))

            active_symbols = list(self._subscribed_symbols)
            symbols_to_update = random.sample(active_symbols, min(num_ticks, len(active_symbols)))

            for symbol in symbols_to_update:
                tick = self._generate_dynamic_tick(symbol, sim_now)
                await market_publisher.publish_tick(tick)

    def _init_symbol_state(self, symbol: str) -> None:
        if symbol in self._symbol_states:
            return

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
            underlying = symbol.split("2")[0].split("3")[0].split("4")[0].split("5")[0].split("6")[0]
            if underlying == "NIFTY":
                base_price = 22000.0
            elif underlying == "BANKNIFTY":
                base_price = 47000.0
            else:
                base_price = 500.0
        else:
            random.seed(symbol)
            base_price = random.uniform(100.0, 2000.0)
            random.seed()

        volatility = 0.0005
        if symbol.startswith("^"):
            volatility = 0.00015
        elif exchange == "NFO":
            volatility = 0.0015

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
        }

    def _generate_dynamic_tick(self, symbol: str, sim_now: datetime) -> dict:
        state = self._symbol_states[symbol]
        vol = state["volatility"]
        
        market_correlation = 0.5 if not symbol.startswith("^") else 0.8
        stock_drift = (self._market_drift * market_correlation) + random.normalvariate(0, vol)
        
        old_price = state["price"]
        new_price = round(old_price * (1.0 + stock_drift), 2)
        if new_price <= 0.05:
            new_price = 0.05

        if new_price > state["high"]:
            state["high"] = new_price
        if new_price < state["low"]:
            state["low"] = new_price
        state["price"] = new_price

        spread_pct = 0.0005 if not symbol.startswith("^") else 0.0001
        spread = max(0.05, round(new_price * spread_pct, 2))
        
        half_spread = round(spread / 2.0, 2)
        if half_spread <= 0:
            half_spread = 0.05
        bid_price = round(new_price - half_spread, 2)
        ask_price = round(new_price + half_spread, 2)

        bid_qty = random.randint(100, 5000)
        ask_qty = random.randint(100, 5000)

        volume_inc = random.randint(10, 500) if not symbol.startswith("^") else 0
        state["volume"] += volume_inc

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

# Global singleton instance
replay_engine = UltraTickReplayEngine()
