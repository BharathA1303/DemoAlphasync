# redis_cache.py - Redis price cache wrapper
import logging
import json
from typing import Dict, Optional

from cache.redis_client import get_redis
from config.settings import settings

logger = logging.getLogger(__name__)

class RedisCache:
    """
    Wraps Redis commands for storing and retrieving live/simulated quotes.
    """

    def __init__(self):
        self._redis = None

    async def _get_client(self):
        if not self._redis:
            self._redis = await get_redis(settings.REDIS_URL)
        return self._redis

    async def set_quote(self, symbol: str, quote: dict, ttl: int = 5) -> bool:
        """Cache a single quote."""
        try:
            client = await self._get_client()
            if client:
                key = f"q:{symbol.upper()}"
                await client.set(key, json.dumps(quote), ex=ttl)
                return True
        except Exception as e:
            logger.debug(f"RedisCache: Failed to set quote: {e}")
        return False

    async def get_quote(self, symbol: str) -> Optional[dict]:
        """Get a cached quote."""
        try:
            client = await self._get_client()
            if client:
                key = f"q:{symbol.upper()}"
                data = await client.get(key)
                if data:
                    return json.loads(data)
        except Exception as e:
            logger.debug(f"RedisCache: Failed to get quote: {e}")
        return None

redis_cache = RedisCache()
