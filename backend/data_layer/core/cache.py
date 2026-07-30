import time
import logging
from typing import Optional, Dict, Tuple
import redis.asyncio as aioredis
from config.settings import settings

logger = logging.getLogger(__name__)

# Redis client
redis_client: Optional[aioredis.Redis] = None

# In-memory fallbacks for caching and rate limiting
_in_memory_cache: Dict[str, Tuple[str, float]] = {}  # key -> (value, expiry_timestamp)
_in_memory_rate_limit: Dict[str, Tuple[int, float]] = {}  # key -> (count, expiry_timestamp)


async def get_redis_client() -> Optional[aioredis.Redis]:
    """Retrieve the shared Redis client from the main application connection pool."""
    global redis_client
    if redis_client is None:
        try:
            from cache.redis_client import get_redis
            cache = await get_redis()
            if cache and cache.is_connected:
                redis_client = cache._redis
        except Exception as e:
            logger.warning(f"Failed to resolve shared Redis client: {e}")
    return redis_client


async def init_redis():
    """Shared hook matching the lifespan lifecycle."""
    await get_redis_client()


async def close_redis():
    """No-op: the main application's connection close is managed globally."""
    pass


# --- Cache Interfaces ---

async def get_cached_response(key: str) -> Optional[str]:
    """Retrieve response from cache (Redis or in-memory)."""
    client = await get_redis_client()
    if client:
        try:
            return await client.get(key)
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
    
    # In-memory fallback
    if key in _in_memory_cache:
        val, expiry = _in_memory_cache[key]
        if time.time() < expiry:
            return val
        else:
            del _in_memory_cache[key]
    return None


async def set_cached_response(key: str, value: str, ttl: int = 60) -> None:
    """Set response in cache (Redis or in-memory) with a TTL in seconds."""
    client = await get_redis_client()
    if client:
        try:
            await client.set(key, value, ex=ttl)
            return
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {e}")
    
    # In-memory fallback
    _in_memory_cache[key] = (value, time.time() + ttl)


# --- Rate Limit Interfaces ---

async def check_and_increment_rate_limit(key: str, limit: int, ttl: int = 60) -> bool:
    """
    Increments request count for `key` and checks if it exceeds `limit`.
    Returns True if allowed, False if rate limited.
    """
    client = await get_redis_client()
    if client:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl, nx=True)
            results = await pipe.execute()
            count = results[0]
            return count <= limit
        except Exception as e:
            logger.error(f"Redis rate limit error for key {key}: {e}")
    
    # In-memory fallback
    now = time.time()
    if key in _in_memory_rate_limit:
        count, expiry = _in_memory_rate_limit[key]
        if now < expiry:
            new_count = count + 1
            _in_memory_rate_limit[key] = (new_count, expiry)
            return new_count <= limit
        else:
            _in_memory_rate_limit[key] = (1, now + ttl)
            return True
    else:
        _in_memory_rate_limit[key] = (1, now + ttl)
        return True


async def clear_cache() -> None:
    """Helper to clear both local and Redis caches."""
    _in_memory_cache.clear()
    _in_memory_rate_limit.clear()
    client = await get_redis_client()
    if client:
        try:
            await client.flushdb()
        except Exception as e:
            logger.error(f"Redis flushdb error: {e}")
