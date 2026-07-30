"""
Data Feed Session Manager.

DemoAlphasync uses a single shared market data provider (the "master
session") for all users, sourced from the internal simulation engine
(backend/data_layer/*) when an admin has enabled it from the admin panel.
No broker integrations, and no external service of any kind, are used —
the simulation engine runs in this same process.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

MASTER_SESSION_ID = "__master__"


class DataFeedSessionManager:
    """
    Provider registry. All users share the single global market data
    provider (master session) — InternalSimProvider (in-process simulator).
    """

    def __init__(self):
        # user_id -> provider instance (always the master provider)
        self._sessions: dict[str, object] = {}
        self._health_task: Optional[asyncio.Task] = None
        self._running = False

    # -- Session CRUD ------------------------------------------------

    async def create_session(self, user_id: str) -> bool:
        """Map a user to the shared master provider."""
        master = self._sessions.get(MASTER_SESSION_ID)
        if not master:
            logger.warning(
                f"Master session not yet initialized — cannot create session for user {str(user_id)[:8]}..."
            )
            return False

        self._sessions[str(user_id)] = master
        logger.info(
            f"Data feed session CREATED for user {str(user_id)[:8]}... (total sessions: {len(self._sessions)})"
        )
        return True

    def get_session(self, user_id: str) -> Optional[object]:
        """Return the provider for a user, falling back to the master session."""
        val = self._sessions.get(user_id)
        if val is not None:
            return val
        return self._sessions.get(MASTER_SESSION_ID)

    def get_any_session(self) -> Optional[object]:
        """Return ANY active provider."""
        return self._sessions.get(MASTER_SESSION_ID)

    def get_all_sessions(self) -> dict[str, object]:
        """Return all active sessions."""
        return dict(self._sessions)

    async def destroy_session(self, user_id: str) -> bool:
        """Remove a user's session mapping."""
        if user_id == MASTER_SESSION_ID:
            return False
        removed = self._sessions.pop(user_id, None)
        if removed:
            logger.info(
                f"Data feed session REMOVED for user {str(user_id)[:8]}... (remaining: {len(self._sessions)})"
            )
            return True
        return False

    def register_session(self, user_id: str, provider) -> None:
        """Register a provider under a given user_id."""
        self._sessions[str(user_id)] = provider
        logger.info(f"DataFeedSessionManager: session registered for user_id={user_id}")

    def has_session(self, user_id: str) -> bool:
        return user_id in self._sessions or MASTER_SESSION_ID in self._sessions

    def session_count(self) -> int:
        return len(self._sessions)

    def _init_simulation_clock_open(self) -> None:
        """Seed the virtual market clock to 09:15 IST on the most recent weekday."""
        try:
            from market_data.replay.simulation_clock import simulation_clock
            from datetime import datetime, timezone, timedelta
            from zoneinfo import ZoneInfo

            IST = ZoneInfo("Asia/Kolkata")
            session_date = datetime.now(IST).date()
            while session_date.weekday() >= 5:  # roll back over Sat/Sun
                session_date -= timedelta(days=1)

            sim_start = datetime(
                session_date.year, session_date.month, session_date.day,
                9, 20, 0, tzinfo=IST,
            )
            simulation_clock.set_clock(
                sim_start_time=sim_start.astimezone(timezone.utc),
                speed=1.0,
            )
            logger.info(
                f"Simulation clock set: {sim_start.strftime('%Y-%m-%d %H:%M IST')} at 1x speed"
            )
        except Exception as e:
            logger.warning(f"Simulation clock init failed: {e}")

    # -- Startup -----------------------------------------------------

    # Bump this whenever the mock EOD generators' symbol coverage or price
    # anchors change, so already-seeded (but now-outdated) deployments
    # re-run the backfill once instead of silently keeping stale rows/cache
    # just because `market_timestamp` already looks "recent".
    _SEED_GENERATION = 3

    async def _ensure_price_data_seeded(self, min_recent_days: int = 5) -> None:
        """Auto-backfill PriceData if the DB doesn't yet have recent EOD rows,
        or if the mock data generators have changed since the last backfill.

        The simulation engine can only generate ticks for symbols/dates that
        already have an EOD row in price_data — without this, a fresh
        deployment (empty DB) would start the tick engine but produce no
        prices at all until an admin manually calls POST
        /admin/simulation/seed. Since the whole point of the internal
        simulation is to be self-contained, we check for recent data here
        and backfill automatically if it's missing, so the platform works
        out of the box.
        """
        from database.connection import async_session
        from sqlalchemy import select, func
        from data_layer.db.models import PriceData
        from models.data_feed_config import DataFeedConfig

        try:
            async with async_session() as session:
                stmt = select(func.max(PriceData.market_timestamp)).where(
                    PriceData.superseded_at.is_(None)
                )
                res = await session.execute(stmt)
                latest_date = res.scalar_one_or_none()

                stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
                res = await session.execute(stmt)
                db_config = res.scalar_one_or_none()
                seeded_generation = getattr(db_config, "seed_generation", None) if db_config else None
        except Exception as e:
            logger.warning(f"Failed to check existing PriceData coverage: {e}")
            return

        from datetime import date, timedelta
        stale_cutoff = date.today() - timedelta(days=min_recent_days)

        generation_current = seeded_generation == self._SEED_GENERATION
        if latest_date and latest_date >= stale_cutoff and generation_current:
            logger.info(f"PriceData already seeded through {latest_date}; skipping auto-backfill.")
            return

        logger.info(
            f"PriceData is missing, stale (latest={latest_date}), or from an "
            f"older seed generation ({seeded_generation} != {self._SEED_GENERATION}); "
            f"running auto-backfill of simulated EOD data..."
        )
        try:
            from data_layer.ingestion.run_ingestion import run_backfill
            await run_backfill(days_to_backfill=45, use_mock=True)

            if not generation_current:
                # The generator's symbol coverage/anchors changed - any
                # cached Redis quotes/history for symbols outside the old
                # coverage (or seeded from stale anchors) would otherwise
                # keep winning over the freshly corrected PriceData rows.
                from cache.redis_client import clear_market_cache
                cleared = await clear_market_cache()
                logger.info(f"Cleared stale market cache after re-seed: {cleared}")

            async with async_session() as session:
                stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
                res = await session.execute(stmt)
                conf = res.scalar_one_or_none()
                if conf:
                    conf.seed_generation = self._SEED_GENERATION
                    await session.commit()

            logger.info("Auto-backfill of simulated EOD data completed.")
        except Exception as e:
            logger.error(f"Auto-backfill of PriceData failed: {e}", exc_info=True)

    async def initialize_master_session(self) -> None:
        """Create and start the master session (InternalSimProvider)."""
        from database.connection import async_session
        from sqlalchemy import select
        from models.data_feed_config import DataFeedConfig
        from cache.redis_client import get_redis
        from config.settings import settings
        from providers.internal_sim_provider import InternalSimProvider

        await self._ensure_price_data_seeded()

        redis_cache = await get_redis(settings.REDIS_URL)

        # Check if the simulation engine is enabled in DB
        db_config = None
        try:
            async with async_session() as session:
                stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
                res = await session.execute(stmt)
                db_config = res.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"Failed to query DataFeedConfig at startup: {e}")

        if not db_config:
            try:
                async with async_session() as session:
                    db_config = DataFeedConfig(is_enabled=True, connection_status="disconnected")
                    session.add(db_config)
                    await session.commit()
                    stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
                    res = await session.execute(stmt)
                    db_config = res.scalar_one_or_none()
                    logger.info("Created default DataFeedConfig (internal simulation engine, enabled)")
            except Exception as e:
                logger.warning(f"Failed to bootstrap default DataFeedConfig: {e}")

        if db_config and db_config.is_enabled:
            logger.info("Initializing internal simulation engine from database configuration...")

            provider = InternalSimProvider(redis_client=redis_cache)
            self.register_session(MASTER_SESSION_ID, provider)

            try:
                await provider.start()
                await self._auto_subscribe(provider)
                async with async_session() as session:
                    stmt = select(DataFeedConfig).filter(DataFeedConfig.id == db_config.id)
                    res = await session.execute(stmt)
                    conf = res.scalar_one()
                    conf.connection_status = "connected"
                    conf.error_message = None
                    await session.commit()
                logger.info("Internal simulation engine started successfully at startup")
                self._init_simulation_clock_open()
            except Exception as e:
                logger.error(f"Failed to start internal simulation engine at startup: {e}")
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
                self._init_simulation_clock_open()
        else:
            logger.warning("Internal simulation engine is disabled by admin configuration.")

    async def reload_data_feed(self, db_session) -> tuple[bool, Optional[str]]:
        """Dynamically reload/switch the active provider based on updated settings in the database."""
        from models.data_feed_config import DataFeedConfig
        from sqlalchemy import select
        from cache.redis_client import get_redis
        from config.settings import settings
        from providers.internal_sim_provider import InternalSimProvider
        from providers.base import ProviderStatus

        stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
        res = await db_session.execute(stmt)
        db_config = res.scalar_one_or_none()

        if not db_config:
            return False, "No data feed configuration found in database"

        old_provider = self._sessions.get(MASTER_SESSION_ID)
        subscribed_symbols = list(old_provider.get_subscribed_symbols()) if old_provider else []

        redis_cache = await get_redis(settings.REDIS_URL)

        success = True
        err_msg = None

        if db_config.is_enabled:
            logger.info("Dynamically starting new internal simulation engine session...")

            await self._ensure_price_data_seeded()

            new_provider = InternalSimProvider(redis_client=redis_cache)
            try:
                db_config.connection_status = "connecting"
                db_config.error_message = None
                await db_session.commit()

                await new_provider.start()
                await asyncio.sleep(1.0)

                if new_provider._status == ProviderStatus.ERROR:
                    raise Exception("Simulation engine session failed to start.")

                if old_provider:
                    await old_provider.stop()

                self.register_session(MASTER_SESSION_ID, new_provider)

                if subscribed_symbols:
                    await new_provider.subscribe(subscribed_symbols)
                else:
                    await self._auto_subscribe(new_provider)

                db_config.connection_status = "connected"
                db_config.error_message = None
                logger.info("Dynamically switched master provider to InternalSimProvider")
            except Exception as e:
                success = False
                err_msg = str(e)
                logger.error(f"Failed to dynamically start internal simulation engine: {e}")

                db_config.connection_status = "error"
                db_config.error_message = err_msg
                await db_session.commit()

                await new_provider.stop()
                return False, err_msg
        else:
            logger.info("Simulation engine disabled.")
            if old_provider:
                await old_provider.stop()
                if MASTER_SESSION_ID in self._sessions:
                    del self._sessions[MASTER_SESSION_ID]

            db_config.connection_status = "disconnected"
            db_config.error_message = None

        await db_session.commit()
        return success, err_msg

    async def restore_sessions(self) -> int:
        await self.initialize_master_session()
        logger.info("Master data feed session started. No per-user sessions to restore.")
        return 0

    # -- Lifecycle ----------------------------------------------------

    async def start_health_check(self, interval: float = 300.0) -> None:
        self._running = True
        logger.info("DataFeedSessionManager health check: nothing to monitor.")

    async def stop(self) -> None:
        self._running = False
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()

        master = self._sessions.get(MASTER_SESSION_ID)
        if master:
            try:
                await master.stop()
            except Exception as e:
                logger.error(f"Error stopping master provider: {e}")

        self._sessions.clear()
        logger.info("DataFeedSessionManager stopped.")

    # -- Internal helpers ---------------------------------------------

    async def _auto_subscribe(self, provider) -> None:
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
            logger.info(f"Auto-subscribed {len(symbols)} symbols on master provider")
        except Exception as e:
            logger.error(f"Auto-subscribe failed: {e}")

    # -- Status --------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "mode": "data_feed",
            "active_sessions": len(self._sessions),
            "master_session_active": MASTER_SESSION_ID in self._sessions,
            "running": self._running,
        }


data_feed_session_manager = DataFeedSessionManager()
