# session_manager.py - Manage replay dates, speed, and market states
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional
from enum import Enum

from market_data.storage.tick_repository import tick_repository
from market_data.replay.simulation_clock import simulation_clock

logger = logging.getLogger(__name__)

class MarketState(Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    LUNCH = "LUNCH"
    CLOSING = "CLOSING"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"

class SessionManager:
    """
    Manages the current active simulation date and market state.
    Allows changing replay speed and rotates dates.
    """

    def __init__(self):
        self._current_date: Optional[datetime] = None
        self._speed = 1.0
        self._market_state = MarketState.CLOSED

    async def setup_session(self, target_date: Optional[datetime] = None) -> datetime:
        """
        Initialize the simulation session. 
        Selects the specified date, a random date from the database, or falls back to a recent day.
        """
        session_date = target_date
        
        if not session_date:
            # Query available dates in the DB
            available_dates = await tick_repository.get_available_dates()
            if available_dates:
                session_date = random.choice(available_dates)
                logger.info(f"SessionManager: Selected historical session date from DB: {session_date.date()}")
            else:
                # Fallback: Choose a random recent day
                random_days_ago = random.randint(1, 30)
                today = datetime.now(timezone.utc) - timedelta(days=random_days_ago)
                session_date = datetime(today.year, today.month, today.day, 9, 15, 0, tzinfo=timezone.utc)
                logger.info(f"SessionManager: Empty database. Starting in fallback mode on date: {session_date.date()}")

        if session_date.tzinfo is None:
            session_date = session_date.replace(tzinfo=timezone.utc)

        self._current_date = session_date
        
        # Reset the global simulation clock
        simulation_clock.set_clock(session_date, self._speed)
        self._market_state = MarketState.OPEN
        
        return session_date

    def set_speed(self, speed: float) -> None:
        """Change the replay speed multiplier."""
        self._speed = max(0.1, speed)
        if simulation_clock.is_simulated:
            simulation_clock.set_clock(simulation_clock.now(), self._speed)
        logger.info(f"SessionManager: Replay speed set to {self._speed}x")

    @property
    def current_date(self) -> Optional[datetime]:
        return self._current_date

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def market_state(self) -> MarketState:
        """Determine the simulated market state based on the simulation clock time."""
        if not simulation_clock.is_simulated:
            return MarketState.CLOSED

        now = simulation_clock.now()
        # Market hours: 9:15 AM to 3:30 PM
        market_open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
        pre_open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
        post_market_time = now.replace(hour=15, minute=40, second=0, microsecond=0)

        if now < pre_open_time:
            return MarketState.CLOSED
        elif now < market_open_time:
            return MarketState.PRE_OPEN
        elif now >= market_open_time and now <= market_close_time:
            # Simulated lunch hours (optional detail)
            if now.hour == 12 and now.minute >= 30 or now.hour == 13 and now.minute < 30:
                return MarketState.LUNCH
            return MarketState.OPEN
        elif now > market_close_time and now < post_market_time:
            return MarketState.POST_MARKET
        else:
            return MarketState.CLOSED

session_manager = SessionManager()
