"""
Broker Session Manager — Simulation-Only Edition.

DemoAlphasync uses a single shared ReplayProvider (master session) for all
market data. No live broker connections are made.

Architecture:
    - App startup: initialize_master_session() starts the global ReplayProvider.
    - Per-user sessions: create_session(user_id) maps a user to the master
      ReplayProvider so downstream code can call get_session(user_id) as normal.
    - No broker OAuth, no credential decryption, no token expiry.

Lifecycle:
    1. App startup → initialize_master_session()
    2. User authenticated → create_session(user_id) (optional, for per-user quota)
    3. Any code → get_session(user_id) or get_any_session()
    4. App shutdown → stop()
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

MASTER_SESSION_ID = "__master__"


class BrokerSessionManager:
    """
    Simulation-only provider registry.
    All users share the single global ReplayProvider (master session).
    """

    def __init__(self):
        # user_id → ReplayProvider instance (always the master in simulation mode)
        self._sessions: dict[str, object] = {}
        self._health_task: Optional[asyncio.Task] = None
        self._running = False

    # ── Session CRUD ────────────────────────────────────────────────

    async def create_session(self, user_id: str) -> bool:
        """
        Map a user to the shared master ReplayProvider.
        Returns True if the session was created (or already existed).
        """
        master = self._sessions.get(MASTER_SESSION_ID)
        if not master:
            logger.warning(
                f"Master session not yet initialized — cannot create session for "
                f"user {str(user_id)[:8]}..."
            )
            return False

        self._sessions[str(user_id)] = master
        logger.info(
            f"Simulation session CREATED for user {str(user_id)[:8]}... "
            f"(total sessions: {len(self._sessions)})"
        )
        return True

    def get_session(self, user_id: str) -> Optional[object]:
        """Return the ReplayProvider for a user, falling back to the master session."""
        val = self._sessions.get(user_id)
        if val is not None:
            return val
        return self._sessions.get(MASTER_SESSION_ID)

    def get_any_session(self) -> Optional[object]:
        """
        Return ANY active provider — for system-level tasks (MarketDataWorker).
        Always returns the master ReplayProvider when available.
        """
        master = self._sessions.get(MASTER_SESSION_ID)
        if master is not None:
            return master
        # Fallback: return first non-None session
        for provider in self._sessions.values():
            if provider is not None:
                return provider
        return None

    def get_all_sessions(self) -> dict[str, object]:
        """Return all active sessions (for MarketDataWorker iteration)."""
        return dict(self._sessions)

    async def destroy_session(self, user_id: str) -> bool:
        """Remove a user's session mapping. Does NOT stop the shared master provider."""
        if user_id == MASTER_SESSION_ID:
            # Master is controlled by initialize_master_session / stop()
            return False
        removed = self._sessions.pop(user_id, None)
        if removed:
            logger.info(
                f"Simulation session REMOVED for user {str(user_id)[:8]}... "
                f"(remaining: {len(self._sessions)})"
            )
            return True
        return False

    def register_session(self, user_id: str, provider) -> None:
        """
        Register a provider under a given user_id.
        Used by initialize_master_session() to inject the shared ReplayProvider.
        """
        self._sessions[str(user_id)] = provider
        logger.info(f"BrokerSessionManager: session registered for user_id={user_id}")

    def has_session(self, user_id: str) -> bool:
        """Check if user has an active session."""
        return user_id in self._sessions or MASTER_SESSION_ID in self._sessions

    def session_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)

    # ── Startup ─────────────────────────────────────────────────────

    async def initialize_master_session(self) -> None:
        """
        Create and start the master session (AMDPProvider or ReplayProvider).
        Called once at app startup.
        """
        from database.connection import async_session
        from sqlalchemy import select
        from models.data_feed_config import DataFeedConfig
        from cache.redis_client import get_redis
        from config.settings import settings
        from providers.replay_provider import ReplayProvider
        from providers.amdp_provider import AMDPProvider
        from providers.base import ProviderStatus

        redis_cache = await get_redis(settings.REDIS_URL)

        # Check if AMDP is configured and enabled in DB
        db_config = None
        try:
            async with async_session() as session:
                stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
                res = await session.execute(stmt)
                db_config = res.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"Failed to query DataFeedConfig at startup (will fallback to Replay): {e}")

        provider = None
        if db_config and db_config.is_enabled and db_config.api_key and db_config.api_secret:
            logger.info("Initializing live AMDPProvider from database configuration...")
            provider = AMDPProvider(
                api_key=db_config.api_key,
                api_secret=db_config.api_secret,
                base_url=db_config.base_url,
                redis_client=redis_cache
            )
            try:
                await provider.start()
                # Update status
                async with async_session() as session:
                    stmt = select(DataFeedConfig).filter(DataFeedConfig.id == db_config.id)
                    res = await session.execute(stmt)
                    conf = res.scalar_one()
                    conf.connection_status = "connected"
                    conf.error_message = None
                    await session.commit()
                logger.info("AMDPProvider started successfully at startup")
            except Exception as e:
                logger.error(f"Failed to start AMDPProvider at startup: {e}. Falling back to Replay.")
                # Update status to error
                try:
                    async with async_session() as session:
                        stmt = select(DataFeedConfig).filter(DataFeedConfig.id == db_config.id)
                        res = await session.execute(stmt)
                        conf = res.scalar_one()
                        conf.connection_status = "error"
                        conf.error_message = str(e)
                        await session.commit()
                except Exception as db_err:
                    logger.debug(f"Failed to write error status: {db_err}")
                provider = None

        if provider is None:
            logger.info("Initializing master session using ReplayProvider...")
            provider = ReplayProvider(redis_client=redis_cache)
            await provider.start()

            # ── Set simulation clock to 9:15 AM IST on the last trading day ──
            try:
                from market_data.replay.simulation_clock import simulation_clock
                from datetime import datetime, timezone, timedelta, date
                from zoneinfo import ZoneInfo

                IST = ZoneInfo("Asia/Kolkata")
                today = datetime.now(IST)

                # Roll back to last weekday if today is weekend
                session_date = today.date()
                while session_date.weekday() >= 5:  # 5=Sat, 6=Sun
                    session_date -= timedelta(days=1)

                # Start simulation at 09:15 AM IST on the chosen date
                sim_start = datetime(
                    session_date.year, session_date.month, session_date.day,
                    9, 15, 0,
                    tzinfo=IST,
                )

                simulation_clock.set_clock(
                    sim_start_time=sim_start.astimezone(timezone.utc),
                    speed=1.0,  # real-time (1 second = 1 second)
                )
                logger.info(
                    f"Simulation clock set: {sim_start.strftime('%Y-%m-%d %H:%M IST')} at 1x speed"
                )
            except Exception as e:
                logger.warning(f"Simulation clock init failed: {e}")

            # ── Download real NSE prices and update replay engine catalogue ──
            try:
                from market_data.downloader.nse_downloader import nse_downloader
                from market_data.replay.replay_engine import replay_engine, SYMBOL_CATALOGUE

                logger.info("Fetching real NSE Bhavcopy prices (this may take a few seconds)...")
                real_prices = await nse_downloader.fetch_and_seed(seed_db=True)

                if real_prices:
                    # Patch the SYMBOL_CATALOGUE with real price levels
                    # so the dynamic generator starts from real market prices
                    updated = 0
                    for canonical, real_px in real_prices.items():
                        if canonical in SYMBOL_CATALOGUE and real_px > 0:
                            SYMBOL_CATALOGUE[canonical]["price"] = real_px
                            # Also update symbol_states if already initialized
                            if canonical in replay_engine._symbol_states:
                                state = replay_engine._symbol_states[canonical]
                                state["price"] = real_px
                                state["open"]  = real_px
                                state["high"]  = real_px
                                state["low"]   = real_px
                            updated += 1

                    logger.info(
                        f"✓ Updated {updated}/{len(SYMBOL_CATALOGUE)} symbols with real NSE prices"
                    )
                else:
                    logger.warning("NSE data unavailable — using default simulation prices")
            except Exception as e:
                logger.warning(f"NSE price update failed (using defaults): {e}")

        # Auto-subscribe popular symbols so the session is active immediately
        await self._auto_subscribe(provider)
        logger.info(f"Master Session initialized with {provider.__class__.__name__}")

    async def reload_data_feed(self, db_session) -> tuple[bool, Optional[str]]:
        """
        Dynamically reload the master provider based on latest DataFeedConfig.
        Returns (success, error_message).
        """
        from sqlalchemy import select
        from models.data_feed_config import DataFeedConfig
        from cache.redis_client import get_redis
        from config.settings import settings
        from providers.replay_provider import ReplayProvider
        from providers.amdp_provider import AMDPProvider
        from providers.base import ProviderStatus

        stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
        res = await db_session.execute(stmt)
        db_config = res.scalar_one_or_none()

        if not db_config:
            return False, "No data feed configuration found"

        # Get existing master provider
        old_provider = self._sessions.get(MASTER_SESSION_ID)
        subscribed_symbols = list(old_provider.get_subscribed_symbols()) if old_provider else []

        redis_cache = await get_redis(settings.REDIS_URL)

        success = True
        err_msg = None

        if db_config.is_enabled:
            if not db_config.api_key or not db_config.api_secret:
                db_config.connection_status = "error"
                db_config.error_message = "API Key and Secret are required when enabled"
                await db_session.commit()
                return False, db_config.error_message

            logger.info("Dynamically starting new AMDPProvider...")
            new_provider = AMDPProvider(
                api_key=db_config.api_key,
                api_secret=db_config.api_secret,
                base_url=db_config.base_url,
                redis_client=redis_cache
            )
            try:
                db_config.connection_status = "connecting"
                db_config.error_message = None
                await db_session.commit()

                await new_provider.start()
                
                # Wait briefly for WebSocket listener to try starting
                await asyncio.sleep(1.0)
                
                if new_provider._status == ProviderStatus.ERROR:
                    raise Exception("WebSocket connection failed to establish. Please check API Key/Secret and URL.")

                # Stop the old provider
                if old_provider:
                    await old_provider.stop()

                # Register new provider
                self.register_session(MASTER_SESSION_ID, new_provider)
                
                # Re-subscribe symbols
                if subscribed_symbols:
                    await new_provider.subscribe(subscribed_symbols)

                db_config.connection_status = "connected"
                db_config.error_message = None
                logger.info("Dynamically switched master provider to AMDPProvider")
            except Exception as e:
                success = False
                err_msg = str(e)
                logger.error(f"Failed to dynamically switch to AMDPProvider: {e}")
                
                db_config.connection_status = "error"
                db_config.error_message = err_msg
                await db_session.commit()
                
                # Stop the failed provider if running
                await new_provider.stop()
                
                # Ensure we fall back to ReplayProvider if no provider is currently active
                if not old_provider or not getattr(old_provider, "_running", False):
                    fallback = ReplayProvider(redis_client=redis_cache)
                    await fallback.start()
                    self.register_session(MASTER_SESSION_ID, fallback)
                    if subscribed_symbols:
                        await fallback.subscribe(subscribed_symbols)
                return False, err_msg
        else:
            logger.info("Live feed disabled. Dynamically switching to ReplayProvider...")
            if old_provider and isinstance(old_provider, AMDPProvider):
                await old_provider.stop()
                
                fallback = ReplayProvider(redis_client=redis_cache)
                await fallback.start()
                self.register_session(MASTER_SESSION_ID, fallback)
                if subscribed_symbols:
                    await fallback.subscribe(subscribed_symbols)
            
            db_config.connection_status = "disconnected"
            db_config.error_message = None
            logger.info("Dynamically switched master provider to ReplayProvider")

        await db_session.commit()
        return success, err_msg




    async def restore_sessions(self) -> int:
        """
        Called during app startup. In simulation mode this only initializes
        the master ReplayProvider — no broker DB queries are performed.
        """
        await self.initialize_master_session()
        logger.info("Simulation mode: master ReplayProvider started. No broker sessions restored.")
        return 0

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start_health_check(self, interval: float = 300.0) -> None:
        """No-op in simulation mode — there are no broker tokens to expire."""
        self._running = True
        logger.info("BrokerSessionManager health check: simulation mode — nothing to monitor.")

    async def stop(self) -> None:
        """Stop the master session and clean up."""
        self._running = False
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()

        master = self._sessions.get(MASTER_SESSION_ID)
        if master:
            try:
                await master.stop()
            except Exception as e:
                logger.error(f"Error stopping master ReplayProvider: {e}")

        self._sessions.clear()
        logger.info("BrokerSessionManager stopped.")

    # ── Internal helpers ─────────────────────────────────────────────

    async def _auto_subscribe(self, provider) -> None:
        """Subscribe all popular symbols on the shared ReplayProvider."""
        from services.market_data import (
            POPULAR_INDIAN_STOCKS,
            INDIAN_INDICES,
            POPULAR_COMMODITIES,
        )

        symbols = (
            [s["symbol"] for s in POPULAR_INDIAN_STOCKS]
            + [i["symbol"] for i in INDIAN_INDICES]
            + [c["symbol"] for c in POPULAR_COMMODITIES]
        )
        try:
            await provider.subscribe(symbols)
            logger.info(f"Auto-subscribed {len(symbols)} symbols on master ReplayProvider")
        except Exception as e:
            logger.error(f"Auto-subscribe failed: {e}")

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return session manager status for health endpoint."""
        return {
            "mode": "simulation",
            "active_sessions": len(self._sessions),
            "master_session_active": MASTER_SESSION_ID in self._sessions,
            "running": self._running,
        }


# ── Module-level singleton ──────────────────────────────────────────
broker_session_manager = BrokerSessionManager()
