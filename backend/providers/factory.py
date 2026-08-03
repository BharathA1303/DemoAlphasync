"""
Provider Factory — Create MarketProvider instances.

Selects between DelayedFeedProvider (Zebu OAuth live data + delay engine)
and ReplayProvider (in-process simulation engine fallback).
"""

import logging
from typing import Optional

from providers.base import MarketProvider
from database.connection import async_session_factory
from models.data_feed_config import DataFeedConfig
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def create_provider(broker: str, user_id: str, creds: dict) -> Optional[MarketProvider]:
    """
    Factory for MarketProvider.
    Returns DelayedFeedProvider when Zebu OAuth live feed is enabled & connected,
    otherwise falls back seamlessly to ReplayProvider.
    """
    from providers.replay_provider import ReplayProvider
    from providers.delayed_feed_provider import DelayedFeedProvider
    from cache.redis_client import get_redis
    from config.settings import settings

    use_live_delayed = broker in ("zebu", "zebu_delayed", "delayed")

    if not use_live_delayed:
        try:
            async with async_session_factory() as session:
                stmt = select(DataFeedConfig).limit(1)
                res = await session.execute(stmt)
                config = res.scalar_one_or_none()
                if config and config.broker_live_feed_enabled and config.oauth_connection_status == "connected":
                    use_live_delayed = True
        except Exception as e:
            logger.warning(f"Provider factory config query failed: {e}")

    if use_live_delayed:
        logger.info(f"Creating DelayedFeedProvider for user {str(user_id)[:8] if user_id else '?'}")
        return DelayedFeedProvider(settings=settings)

    redis_cache = await get_redis(settings.REDIS_URL)
    provider = ReplayProvider(redis_client=redis_cache)
    logger.info(
        f"Created ReplayProvider for user {str(user_id)[:8] if user_id else '?'}... "
        "(simulation fallback)"
    )
    return provider
