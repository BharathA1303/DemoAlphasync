"""
AlphaSync Smart Cache — In-memory TTL cache with LRU eviction.

Provides a fast, process-local cache layer that sits ABOVE Redis.
Eliminates network round-trips for hot data that gets hammered
by multiple concurrent requests within the same second.

Architecture:
    Request → SmartCache (in-memory, <1μs) → Redis (network, ~1ms) → DB/API (~50ms+)

Key design decisions:
    - asyncio-safe (no threads/locks needed — single event loop)
    - Automatic TTL-based expiry with lazy cleanup
    - LRU eviction when max_size is reached
    - Per-key TTL support (different data has different freshness needs)
    - Periodic background cleanup of expired entries
    - Stats tracking for hit/miss ratio monitoring

Usage:
    from cache.smart_cache import portfolio_cache, quote_cache

    # Set with TTL
    portfolio_cache.set("user:abc", data, ttl=5)

    # Get (returns None if expired/missing)
    result = portfolio_cache.get("user:abc")

    # Decorator for async functions
    @quote_cache.cached(ttl=10, key_fn=lambda sym, uid: f"{sym}:{uid}")
    async def get_quote(symbol, user_id):
        ...
"""

import time
import logging
import functools
from collections import OrderedDict
from typing import Optional, Any, Callable

logger = logging.getLogger(__name__)


class SmartCache:
    """
    In-memory TTL cache with LRU eviction.

    Thread-safe within a single asyncio event loop (no GIL contention).
    Uses OrderedDict for O(1) LRU operations.
    """

    def __init__(self, name: str, max_size: int = 1000, default_ttl: float = 30.0):
        self.name = name
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()  # key → (value, expire_at)
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "sets": 0}
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 60.0  # seconds between full cleanups

    def get(self, key: str) -> Optional[Any]:
        """Get a value. Returns None if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        value, expire_at = entry
        if time.monotonic() > expire_at:
            # Expired — lazy delete
            del self._store[key]
            self._stats["misses"] += 1
            return None

        # Move to end (most recently used)
        self._store.move_to_end(key)
        self._stats["hits"] += 1
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set a value with optional TTL override."""
        ttl = ttl if ttl is not None else self.default_ttl
        expire_at = time.monotonic() + ttl

        # If key exists, update in place
        if key in self._store:
            self._store[key] = (value, expire_at)
            self._store.move_to_end(key)
        else:
            # Evict LRU if at capacity
            if len(self._store) >= self.max_size:
                self._store.popitem(last=False)
                self._stats["evictions"] += 1
            self._store[key] = (value, expire_at)

        self._stats["sets"] += 1

        # Periodic cleanup of expired entries
        now = time.monotonic()
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup()
            self._last_cleanup = now

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if it existed."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    def invalidate_prefix(self, prefix: str) -> int:
        """Delete all keys starting with prefix. Returns count deleted."""
        to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in to_delete:
            del self._store[k]
        return len(to_delete)

    def clear(self) -> None:
        """Clear all entries."""
        self._store.clear()

    def _cleanup(self) -> None:
        """Remove all expired entries."""
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        if expired:
            logger.debug(f"[SmartCache:{self.name}] Cleaned {len(expired)} expired entries")

    def get_stats(self) -> dict:
        """Return cache statistics for monitoring."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        return {
            "name": self.name,
            "size": len(self._store),
            "max_size": self.max_size,
            "hit_rate": round(hit_rate, 1),
            **self._stats,
        }

    def cached(self, ttl: Optional[float] = None, key_fn: Optional[Callable] = None):
        """
        Decorator for caching async function results.

        Args:
            ttl: Cache TTL in seconds (defaults to cache's default_ttl)
            key_fn: Function that takes the same args as the decorated function
                    and returns a cache key string. If None, uses f"{func_name}:{args}"
        """
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # Build cache key
                if key_fn:
                    cache_key = key_fn(*args, **kwargs)
                else:
                    parts = [func.__name__] + [str(a) for a in args]
                    cache_key = ":".join(parts)

                # Check cache
                cached_value = self.get(cache_key)
                if cached_value is not None:
                    return cached_value

                # Call function and cache result
                result = await func(*args, **kwargs)
                if result is not None:
                    self.set(cache_key, result, ttl=ttl)
                return result

            # Expose cache control on the wrapper
            wrapper.cache = self
            wrapper.invalidate = lambda *a, **kw: self.delete(
                key_fn(*a, **kw) if key_fn else ":".join([func.__name__] + [str(x) for x in a])
            )
            return wrapper
        return decorator


# ── Pre-configured cache instances ───────────────────────────────────────────

# Quote cache — very short TTL, high throughput
# Prices update every 3s from the market worker; 5s TTL means at most 1 stale cycle
quote_cache = SmartCache(name="quotes", max_size=2000, default_ttl=5.0)

# Portfolio cache — short TTL, moderate throughput
# Portfolio summaries are expensive (N DB queries + quote lookups per holding)
portfolio_cache = SmartCache(name="portfolio", max_size=200, default_ttl=3.0)

# Holdings cache — short TTL
holdings_cache = SmartCache(name="holdings", max_size=200, default_ttl=3.0)

# Order list cache — very short TTL (changes on every trade)
order_cache = SmartCache(name="orders", max_size=200, default_ttl=2.0)

# Search cache — longer TTL (stock list doesn't change often)
search_cache = SmartCache(name="search", max_size=500, default_ttl=300.0)

# History cache — medium TTL (candle data is immutable for past candles)
history_cache = SmartCache(name="history", max_size=300, default_ttl=60.0)

# Indices cache — short TTL
indices_cache = SmartCache(name="indices", max_size=10, default_ttl=8.0)

# Ticker cache — short TTL
ticker_cache = SmartCache(name="ticker", max_size=5, default_ttl=8.0)


def get_all_cache_stats() -> dict:
    """Return stats for all cache instances — used in /api/health."""
    return {
        c.name: c.get_stats()
        for c in [
            quote_cache, portfolio_cache, holdings_cache,
            order_cache, search_cache, history_cache,
            indices_cache, ticker_cache,
        ]
    }
