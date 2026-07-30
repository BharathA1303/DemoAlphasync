# replay_scheduler.py - High-resolution delay and scheduling loop
import asyncio
import logging
import time
from datetime import datetime
from typing import Callable, Optional

from market_data.replay.simulation_clock import simulation_clock
from market_data.replay.tick_queue import tick_queue

logger = logging.getLogger(__name__)

class ReplayScheduler:
    """
    Pops ticks from the TickQueue, calculates the time difference between them,
    waits for the appropriate duration scaled by simulation speed,
    and invokes the callback to publish the tick.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callback: Optional[Callable[[dict], None]] = None
        self._last_tick_sim_time: Optional[datetime] = None

    def set_callback(self, callback: Callable[[dict], None]) -> None:
        self._callback = callback

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._running = True
        self._last_tick_sim_time = None
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("ReplayScheduler started")

    async def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ReplayScheduler stopped")

    async def _scheduler_loop(self) -> None:
        """
        Pops ticks from the queue and schedules them with precise delays.
        """
        while self._running:
            try:
                tick = await tick_queue.pop()
                if not tick:
                    # Queue is empty, yield control and wait for the buffer loader to refill
                    await asyncio.sleep(0.1)
                    continue

                # Parse tick timestamp
                ts_str = tick["timestamp"]
                if isinstance(ts_str, str):
                    tick_sim_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                else:
                    tick_sim_time = ts_str

                if self._last_tick_sim_time:
                    # Calculate time difference in simulation seconds
                    sim_diff = (tick_sim_time - self._last_tick_sim_time).total_seconds()
                    if sim_diff > 0:
                        # Scale delay based on current simulation speed
                        speed = simulation_clock.speed
                        real_sleep = sim_diff / speed
                        
                        # Cap sleep to prevent large gaps (e.g. overnight or lunch)
                        if real_sleep > 5.0:
                            real_sleep = 0.1
                            simulation_clock.set_clock(tick_sim_time, speed)

                        await asyncio.sleep(real_sleep)

                # Dispatch tick via callback
                if self._callback:
                    try:
                        if asyncio.iscoroutinefunction(self._callback):
                            await self._callback(tick)
                        else:
                            self._callback(tick)
                    except Exception as e:
                        logger.error(f"ReplayScheduler: Callback error: {e}")

                self._last_tick_sim_time = tick_sim_time

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ReplayScheduler: Error in scheduler loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

replay_scheduler = ReplayScheduler()
