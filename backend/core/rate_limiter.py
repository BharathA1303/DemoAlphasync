"""
AlphaSync Rate Limiter — Redis-backed request throttling middleware.

Provides per-IP rate limiting for auth endpoints (login, register)
to prevent brute-force attacks. Uses a sliding window counter stored in Redis.
Falls back to in-memory if Redis is unavailable.

Usage:
    Applied as FastAPI middleware in main.py.
"""

import time
import logging
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Rate limit configurations per path prefix
RATE_LIMITS = {
    "/api/auth/sync": {"max_requests": 10, "window_seconds": 60},
    "/api/auth/me": {"max_requests": 30, "window_seconds": 60},
    "/api/auth/logout": {"max_requests": 10, "window_seconds": 60},
    # Admin endpoints — strict rate limiting
    "/api/admin/auth": {"max_requests": 5, "window_seconds": 60},
    "/api/admin/": {"max_requests": 180, "window_seconds": 60},
    # Market data endpoints are read-only cached data — allow higher throughput
    "/api/market/": {"max_requests": 600, "window_seconds": 60},
    # Futures endpoints get their own bucket — WS-first arch reduces REST usage
    "/api/futures/": {"max_requests": 300, "window_seconds": 60},
}

# Default rate limit for all other API endpoints
DEFAULT_RATE_LIMIT = {"max_requests": 120, "window_seconds": 60}

# Redis key prefix for rate limiting
_RL_PREFIX = "alphasync:ratelimit"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter keyed by client IP + path prefix.

    Uses Redis sorted sets for persistence across restarts.
    Falls back to in-memory dict if Redis is unavailable.
    Skips non-API paths (static files, WebSocket, health).
    """

    def __init__(self, app):
        super().__init__(app)
        # In-memory fallback
        self._requests: dict[tuple, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 minutes

    async def _get_redis(self):
        """Try to get the Redis connection, return None if unavailable."""
        try:
            from cache.redis_client import _price_cache

            if _price_cache and _price_cache._redis:
                return _price_cache._redis
        except Exception:
            pass
        return None

    async def __call__(self, scope, receive, send):
        # CRITICAL: BaseHTTPMiddleware breaks WebSocket protocol.
        # Bypass completely for WebSocket connections.
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip non-API paths, WebSocket, and health checks
        if not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)

        client_ip = self._extract_client_ip(request)

        # Find matching rate limit config
        config = DEFAULT_RATE_LIMIT
        matched_prefix = "default"
        for prefix, limit_config in RATE_LIMITS.items():
            if path.startswith(prefix):
                config = limit_config
                matched_prefix = prefix
                break

        max_requests = config["max_requests"]
        window = config["window_seconds"]
        now = time.time()

        # Keep buckets scoped to the matched prefix, so strict limits on
        # /api/admin/auth don't get consumed by /api/admin/users requests.
        path_group = matched_prefix.replace("/", ":")

        # Try Redis first, fall back to in-memory
        redis = await self._get_redis()
        if redis:
            is_limited, retry_after, count = await self._check_redis(
                redis, client_ip, path_group, max_requests, window, now
            )
        else:
            is_limited, retry_after, count = self._check_memory(
                client_ip, path_group, max_requests, window, now
            )

        if is_limited:
            logger.warning(
                f"Rate limit exceeded: {client_ip} on {path} "
                f"({count}/{max_requests} in {window}s)"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

    def _extract_client_ip(self, request: Request) -> str:
        """Resolve the best-effort client IP behind reverse proxies."""
        # Preferred order for common proxy stacks: Cloudflare -> Nginx -> direct.
        for header in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
            raw = (request.headers.get(header) or "").strip()
            if not raw:
                continue
            if header == "x-forwarded-for":
                # RFC 7239 style: client, proxy1, proxy2
                raw = raw.split(",", 1)[0].strip()
            if raw:
                return raw

        return request.client.host if request.client else "unknown"

    async def _check_redis(
        self,
        redis,
        client_ip: str,
        path_group: str,
        max_requests: int,
        window: int,
        now: float,
    ) -> tuple[bool, int, int]:
        """Sliding window check using Redis sorted set."""
        key = f"{_RL_PREFIX}:{client_ip}:{path_group}"
        cutoff = now - window

        try:
            pipe = redis.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, cutoff)
            # Count current entries
            pipe.zcard(key)
            results = await pipe.execute()
            count = results[1]

            if count >= max_requests:
                # Get the oldest entry to calculate retry_after
                oldest = await redis.zrange(key, 0, 0, withscores=True)
                if oldest:
                    retry_after = int(window - (now - oldest[0][1])) + 1
                else:
                    retry_after = window
                return True, retry_after, count

            # Add the current request
            pipe2 = redis.pipeline()
            pipe2.zadd(key, {f"{now}": now})
            pipe2.expire(key, window + 10)  # TTL slightly longer than window
            await pipe2.execute()
            return False, 0, count + 1

        except Exception as e:
            logger.warning(f"Redis rate limit check failed, using in-memory: {e}")
            return self._check_memory(client_ip, path_group, max_requests, window, now)

    def _check_memory(
        self,
        client_ip: str,
        path_group: str,
        max_requests: int,
        window: int,
        now: float,
    ) -> tuple[bool, int, int]:
        """In-memory fallback sliding window check."""
        key = (client_ip, path_group)

        # Clean old timestamps
        self._requests[key] = [ts for ts in self._requests[key] if now - ts < window]

        if len(self._requests[key]) >= max_requests:
            retry_after = int(window - (now - self._requests[key][0])) + 1
            return True, retry_after, len(self._requests[key])

        self._requests[key].append(now)

        # Periodic cleanup of expired entries
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup(now)
            self._last_cleanup = now

        return False, 0, len(self._requests[key])

    def _cleanup(self, now: float):
        """Remove expired entries to prevent memory growth."""
        max_window = max(c["window_seconds"] for c in RATE_LIMITS.values())
        expired_keys = [
            key
            for key, timestamps in self._requests.items()
            if not timestamps or (now - timestamps[-1]) > max_window
        ]
        for key in expired_keys:
            del self._requests[key]
