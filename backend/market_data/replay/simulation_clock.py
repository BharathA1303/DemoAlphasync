# simulation_clock.py - Global simulation clock
import time
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class SimulationClock:
    """
    Global clock that manages simulated trading time.
    Supports running time at accelerated speeds (e.g. 1x, 2x, 5x).
    """

    def __init__(self):
        self._is_simulated = False
        self._start_real_time = 0.0
        self._start_sim_time = datetime.now(timezone.utc)
        self._speed = 1.0

    def set_clock(self, sim_start_time: datetime, speed: float = 1.0) -> None:
        """Enable simulation mode and set the starting simulation time and speed."""
        if sim_start_time.tzinfo is None:
            sim_start_time = sim_start_time.replace(tzinfo=timezone.utc)

        self._is_simulated = True
        self._start_real_time = time.time()
        self._start_sim_time = sim_start_time
        self._speed = max(0.1, speed)
        logger.info(
            f"Simulation clock initialized: Start={self._start_sim_time.isoformat()} | Speed={self._speed}x"
        )

    def disable(self) -> None:
        """Disable simulation mode, reverting to the real system clock."""
        self._is_simulated = False
        logger.info("Simulation clock disabled — reverted to system time")

    @property
    def is_simulated(self) -> bool:
        """Check if simulation mode is active."""
        return self._is_simulated

    @property
    def speed(self) -> float:
        """Get the current simulation speed multiplier."""
        return self._speed

    def now(self) -> datetime:
        """Get the current time (simulated if active, else real UTC)."""
        if not self._is_simulated:
            return datetime.now(timezone.utc)

        elapsed_real = time.time() - self._start_real_time
        elapsed_sim = elapsed_real * self._speed
        return self._start_sim_time + timedelta(seconds=elapsed_sim)

    def now_iso(self) -> str:
        """Get the current time as an ISO-8601 string."""
        return self.now().isoformat()

    def elapsed_seconds(self) -> float:
        """Get the number of simulated seconds elapsed since the clock started."""
        if not self._is_simulated:
            return 0.0
        return (time.time() - self._start_real_time) * self._speed


# Global singleton instance
simulation_clock = SimulationClock()
