"""
Provider Factory — Create MarketProvider instances.

DemoAlphasync is a simulation-only environment.
All market data flows through ReplayProvider — no live broker connections.
"""

import logging
from typing import Optional

from providers.base import MarketProvider

logger = logging.getLogger(__name__)


async def create_provider(broker: str, user_id: str, creds: dict) -> Optional[MarketProvider]:
    """
    Factory for MarketProvider.
    Returns DelayedFeedProvider when Zebu OAuth live feed is configured/requested,
    otherwise falls back to ReplayProvider.
    """
    from providers.replay_provider import ReplayProvider
    from providers.delayed_feed_provider import DelayedFeedProvider
    from cache.redis_client import get_redis
    from config.settings import settings

    if broker in ("zebu", "zebu_delayed", "delayed"):
        logger.info(f"Creating DelayedFeedProvider for user {str(user_id)[:8] if user_id else '?'}")
        return DelayedFeedProvider(settings=settings)

    redis_cache = await get_redis(settings.REDIS_URL)
    provider = ReplayProvider(redis_client=redis_cache)
    logger.info(
        f"Created ReplayProvider for user {str(user_id)[:8] if user_id else '?'}... "
        "(simulation fallback)"
    )
    return provider

