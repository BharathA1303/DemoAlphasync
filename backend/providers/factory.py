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
    Always return a ReplayProvider — this is the simulation environment.
    The `broker` and `creds` arguments are accepted for API compatibility
    but are intentionally ignored.
    """
    from providers.replay_provider import ReplayProvider
    from cache.redis_client import get_redis
    from config.settings import settings

    redis_cache = await get_redis(settings.REDIS_URL)
    provider = ReplayProvider(redis_client=redis_cache)
    logger.info(
        f"Created ReplayProvider for user {str(user_id)[:8] if user_id else '?'}... "
        "(simulation mode — no live broker connection)"
    )
    return provider
