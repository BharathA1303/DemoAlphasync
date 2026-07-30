"""
Internal Simulation Engine — direct symbol/EOD lookups needed outside the
live tick path (providers/internal_sim_provider.py owns that): symbol
listing and per-contract EOD lookups for populating the NSE/BSE/MCX/NCDEX
+ F&O contract registry at startup.

Replaces the old TickAlphaClient, which made real HTTP+JWT calls to
"TickAlpha" even though it is this same process's own simulator. All calls
here are direct in-process function calls (see
services/internal_sim_engine.py) — nothing external is contacted.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def get_configured_client() -> Optional["InternalSimClient"]:
    """Build an InternalSimClient if the internal simulation engine is
    enabled in DataFeedConfig, or None otherwise."""
    from database.connection import async_session
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select

    try:
        async with async_session() as session:
            stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
            res = await session.execute(stmt)
            config = res.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"Internal sim client: failed to load DataFeedConfig: {e}")
        return None

    if not config or not config.is_enabled:
        return None

    return InternalSimClient()


class InternalSimClient:
    """Direct in-process accessor for symbol lists and EOD lookups."""

    async def get_symbols(self, exchange: str, segment: str = "EQ") -> list[str]:
        from database.connection import async_session
        from services.internal_sim_engine import get_eligible_symbols_list

        async with async_session() as db:
            return await get_eligible_symbols_list(db, exchange, segment)

    async def get_latest_price(
        self,
        exchange: str,
        symbol: str,
        segment: str = "EQ",
        expiry: Optional[str] = None,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
    ) -> Optional[dict]:
        from datetime import date as date_cls
        from database.connection import async_session
        from services.internal_sim_engine import get_latest_eligible_price

        parsed_expiry = date_cls.fromisoformat(expiry) if expiry else None
        async with async_session() as db:
            return await get_latest_eligible_price(
                db,
                exchange=exchange,
                symbol=symbol,
                segment=segment,
                expiry=parsed_expiry,
                strike=strike,
                option_type=option_type,
            )
