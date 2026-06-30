"""
Redis Price Cache — Low-latency price storage for real-time data.

Redis Key Schema:
──────────────────────────────────────────────────────────────────
    alphasync:price:{symbol}            → JSON hash of latest quote
    alphasync:price:{symbol}:ts         → Unix timestamp of last update
    alphasync:subscriptions             → SET of currently subscribed symbols
    alphasync:provider:status           → JSON hash with provider health
    alphasync:price:all                 → HASH of symbol -> JSON quote (batch reads)

Key TTLs:
    Price data:    120 seconds (auto-expire stale data)
    Subscriptions: No TTL (managed explicitly)
    Provider info: 60 seconds

Design decisions:
    - Uses redis.asyncio for non-blocking I/O within the FastAPI event loop.
    - Every write sets a TTL so stale data is auto-evicted.
    - PriceCache wraps all Redis ops with error handling — callers never
      need to catch Redis exceptions.
    - Falls back gracefully if Redis is unavailable (logged warning, returns None).
"""

import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── Key prefix ──────────────────────────────────────────────────────
PREFIX = "alphasync"

# ── TTLs ────────────────────────────────────────────────────────────
PRICE_TTL = 120  # seconds — price keys auto-expire
PRICE_TTL_CLOSED = 86400  # keep last tradable price for closed/holiday periods
SNAPSHOT_TTL = 7 * 24 * 60 * 60  # 7 days retention for frozen market snapshots
PROVIDER_STATUS_TTL = 60  # seconds


def _get_price_ttl() -> int:
    """Use short TTL during trading, long TTL when market is closed/holiday/weekend."""
    try:
        from engines.market_session import market_session, MarketState

        state = market_session.get_current_state()
        if state != MarketState.OPEN:
            return PRICE_TTL_CLOSED
    except Exception:
        pass
    return PRICE_TTL


def _is_closed_market() -> bool:
    try:
        from engines.market_session import market_session, MarketState

        state = market_session.get_current_state()
        return state != MarketState.OPEN
    except Exception:
        return False


def _safe_float(value) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _enrich_frozen_day_change_payload(quote: dict) -> dict:
    """Ensure frozen Redis quotes always carry prev_close, change, and change_percent.

  Intraday/history snapshots often persist LTP only; this derives day change from
  fields already on the payload without overwriting valid values.
    """
    if not quote or not isinstance(quote, dict):
        return quote

    out = dict(quote)
    price = _safe_float(
        out.get("price")
        or out.get("ltp")
        or out.get("lp")
        or out.get("last_price")
        or out.get("lastPrice")
    )
    if price is None or price <= 0:
        return out

    price = round(price, 2)
    out["price"] = price
    out["ltp"] = price
    out["lp"] = price
    out["last_price"] = price

    change = _safe_float(out.get("change") or out.get("net_change") or out.get("netChange"))
    change_pct = _safe_float(
        out.get("change_percent")
        or out.get("change_pct")
        or out.get("changePercent")
        or out.get("pct_change")
        or out.get("pc")
        or out.get("pChange")
    )
    prev_close = _safe_float(out.get("prev_close") or out.get("previous_close") or out.get("prevClose"))

    # "close"/"c" is previous session close on live ticks — not today's LTP.
    if prev_close is None:
        close_field = _safe_float(out.get("close") or out.get("c"))
        if close_field and close_field > 0 and abs(close_field - price) > 0.004:
            prev_close = close_field

    if (
        change is not None
        and change_pct is not None
        and prev_close is not None
        and prev_close > 0
    ):
        out["change"] = round(change, 2)
        out["change_percent"] = round(change_pct, 2)
        out["prev_close"] = round(prev_close, 2)
        return out

    if prev_close is not None and prev_close > 0:
        derived_change = round(price - prev_close, 2)
        derived_pct = round((derived_change / prev_close) * 100.0, 2)
        out["prev_close"] = round(prev_close, 2)
        if change is None:
            out["change"] = derived_change
        else:
            out["change"] = round(change, 2)
        if change_pct is None:
            out["change_percent"] = derived_pct
        else:
            out["change_percent"] = round(change_pct, 2)
        return out

    if change is not None and change_pct is not None:
        denominator = 1.0 + (float(change_pct) / 100.0)
        if denominator > 0:
            derived_prev = price / denominator
            if derived_prev > 0:
                out["prev_close"] = round(derived_prev, 2)
                out["change"] = round(change, 2)
                out["change_percent"] = round(change_pct, 2)
        return out

    # BSE/index ticks often carry only pc (percent change) without absolute change.
    # Derive prev_close and change so closed-market quotes always display correctly.
    if change is None and change_pct is not None:
        denominator = 1.0 + (float(change_pct) / 100.0)
        if denominator > 0:
            derived_prev = price / denominator
            if derived_prev > 0:
                out["prev_close"] = round(derived_prev, 2)
                out["change"] = round(price - derived_prev, 2)
                out["change_percent"] = round(change_pct, 2)
        return out

    if change is not None and change_pct is None:
        out["change"] = round(change, 2)

    return out


def _key(kind: str, *parts: str) -> str:
    """Build a namespaced Redis key."""
    segments = [PREFIX, kind] + list(parts)
    return ":".join(segments)


def _symbol_aliases(symbol: str) -> list[str]:
    """Return canonical lookup aliases for a symbol.

    Example: TCS -> ["TCS", "TCS.NS"]; TCS.NS -> ["TCS.NS", "TCS"]
    Legacy NSE renames (TATAMOTORS.NS) prefer the live master key (TMPV.NS) first.
    """
    if not symbol:
        return []

    raw = str(symbol).strip().upper()
    if not raw:
        return []

    try:
        from providers.symbol_mapper import redis_price_lookup_symbols

        ordered = redis_price_lookup_symbols(raw)
        if ordered:
            return ordered
    except Exception:
        pass

    aliases: list[str] = []

    def _add(value: str):
        if value and value not in aliases:
            aliases.append(value)

    _add(raw)

    if raw.startswith("^"):
        return aliases

    if raw.endswith(".NS"):
        _add(raw[:-3])
    elif raw.endswith(".BO"):
        _add(raw[:-3])
    elif "=" not in raw and not raw.endswith((".NS", ".BO")):
        _add(f"{raw}.NS")

    return aliases


def _history_keys(symbol: str, period: str, interval: str) -> list[str]:
    """Return canonical history key variants for a symbol/period/interval."""
    keys = []
    for alias in _symbol_aliases(symbol):
        key = _key("history", alias, period, interval)
        if key not in keys:
            keys.append(key)
    return keys


def _snapshot_price_keys(symbol: str) -> list[str]:
    keys = []
    for alias in _symbol_aliases(symbol):
        key = _key("snapshot", "price", alias)
        if key not in keys:
            keys.append(key)
    return keys


def _snapshot_history_keys(symbol: str, interval: str) -> list[str]:
    keys = []
    for alias in _symbol_aliases(symbol):
        key = _key("snapshot", "history", alias, interval)
        if key not in keys:
            keys.append(key)
    return keys


class PriceCache:
    """
    Async Redis wrapper for the price cache layer.

    Usage:
        cache = PriceCache(redis_url="redis://localhost:6379/0")
        await cache.connect()
        await cache.set_price("RELIANCE.NS", {"price": 2513.45, ...})
        quote = await cache.get_price("RELIANCE.NS")
        await cache.close()
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._url = redis_url
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Establish Redis connection pool."""
        try:
            self._redis = aioredis.from_url(
                self._url,
                decode_responses=True,
                max_connections=64,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            # Verify connectivity
            await self._redis.ping()
            logger.info(f"Redis connected: {self._url}")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            self._redis = None

    async def close(self) -> None:
        """Close Redis connection pool."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Redis connection closed")

    @property
    def is_connected(self) -> bool:
        return self._redis is not None

    # ── Price operations ────────────────────────────────────────────

    async def set_price(self, symbol: str, quote: dict) -> bool:
        """
        Store a quote in Redis.

        Returns True on success, False on failure.
        """
        if not self._redis:
            return False

        try:
            key = _key("price", symbol)
            ts_key = _key("price", symbol, "ts")
            pipe = self._redis.pipeline()
            stored_quote = (
                _enrich_frozen_day_change_payload(quote)
                if _is_closed_market()
                else quote
            )
            payload = json.dumps(stored_quote, separators=(",", ":"))
            ttl = _get_price_ttl()
            pipe.set(key, payload, ex=ttl)
            pipe.set(ts_key, str(time.time()), ex=ttl)
            # Persistent last-tradable snapshot (no TTL) for closed/holiday reads.
            last_payload = _enrich_frozen_day_change_payload(stored_quote)
            pipe.set(_key("last_price", symbol), json.dumps(last_payload, separators=(",", ":")))
            pipe.set(_key("last_price", symbol, "ts"), str(time.time()))
            for snapshot_key in _snapshot_price_keys(symbol):
                pipe.set(snapshot_key, payload, ex=SNAPSHOT_TTL)
            # Also update the batch hash for bulk reads
            pipe.hset(_key("price", "all"), symbol, payload)
            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(f"Redis set_price failed for {symbol}: {e}")
            return False

    async def set_prices_mirrored(self, canonical: str, quote: dict, mirror_symbols: list[str]) -> bool:
        """
        Store one tick for canonical + alias symbols in a single pipeline round-trip.
        """
        if not self._redis:
            return False

        symbols = [canonical, *(s for s in mirror_symbols if s and s != canonical)]
        if not symbols:
            return False

        try:
            now = str(time.time())
            ttl = _get_price_ttl()
            batch_key = _key("price", "all")
            pipe = self._redis.pipeline()

            for sym in symbols:
                payload_obj = quote
                if sym != canonical:
                    payload_obj = {
                        **quote,
                        "symbol": sym,
                        "name": sym.replace(".NS", "").replace(".BO", ""),
                    }
                if _is_closed_market():
                    payload_obj = _enrich_frozen_day_change_payload(payload_obj)
                payload = json.dumps(payload_obj, separators=(",", ":"))
                last_payload = json.dumps(
                    _enrich_frozen_day_change_payload(payload_obj),
                    separators=(",", ":"),
                )
                pipe.set(_key("price", sym), payload, ex=ttl)
                pipe.set(_key("price", sym, "ts"), now, ex=ttl)
                pipe.set(_key("last_price", sym), last_payload)
                pipe.set(_key("last_price", sym, "ts"), now)
                for snapshot_key in _snapshot_price_keys(sym):
                    pipe.set(snapshot_key, payload, ex=SNAPSHOT_TTL)
                pipe.hset(batch_key, sym, payload)

            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(f"Redis set_prices_mirrored failed for {canonical}: {e}")
            return False

    async def set_prices_batch(self, quotes: dict[str, dict]) -> bool:
        """Store multiple quotes in Redis using a single pipeline round-trip."""
        if not self._redis or not quotes:
            return False

        try:
            batch_key = _key("price", "all")
            now = str(time.time())
            ttl = _get_price_ttl()
            pipe = self._redis.pipeline()
            for symbol, quote in quotes.items():
                stored_quote = (
                    _enrich_frozen_day_change_payload(quote)
                    if _is_closed_market()
                    else quote
                )
                payload = json.dumps(stored_quote, separators=(",", ":"))
                last_payload = json.dumps(
                    _enrich_frozen_day_change_payload(stored_quote),
                    separators=(",", ":"),
                )
                pipe.set(_key("price", symbol), payload, ex=ttl)
                pipe.set(_key("price", symbol, "ts"), now, ex=ttl)
                pipe.set(_key("last_price", symbol), last_payload)
                pipe.set(_key("last_price", symbol, "ts"), now)
                for snapshot_key in _snapshot_price_keys(symbol):
                    pipe.set(snapshot_key, payload, ex=SNAPSHOT_TTL)
                pipe.hset(batch_key, symbol, payload)
            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(
                f"Redis set_prices_batch failed ({len(quotes)} symbols): {e}"
            )
            return False

    async def set_authoritative_close(self, symbol: str, quote: dict) -> bool:
        """
        Write official EOD close to price, last_price, and snapshot keys.

        Schema includes source=official_eod_close, official_close, frozen_at, etc.
        Used after market close — must not be overwritten by stale live_ws ticks.
        """
        if not self._redis:
            return False

        try:
            now = time.time()
            enriched = _enrich_frozen_day_change_payload(
                {
                    **quote,
                    "source": "official_eod_close",
                    "source_detail": quote.get("source") or "official_eod_close",
                    "market_session": quote.get("market_session") or "closed",
                    "official": True,
                    "frozen": True,
                    "frozen_at": quote.get("frozen_at") or now,
                    "official_close": quote.get("official_close") or quote.get("price"),
                    "official_close_timestamp": quote.get("official_close_timestamp")
                    or quote.get("timestamp"),
                }
            )
            if enriched.get("official_close") is not None:
                try:
                    enriched["official_close"] = round(
                        float(enriched["official_close"]), 2
                    )
                except (TypeError, ValueError):
                    pass
            if enriched.get("price") is not None:
                try:
                    ltp = round(float(enriched["price"]), 2)
                    enriched["price"] = ltp
                    enriched["ltp"] = ltp
                    enriched["lp"] = ltp
                    enriched["last_price"] = ltp
                except (TypeError, ValueError):
                    pass

            key = _key("price", symbol)
            ts_key = _key("price", symbol, "ts")
            pipe = self._redis.pipeline()
            payload = json.dumps(enriched, separators=(",", ":"))
            ttl = PRICE_TTL_CLOSED
            ts_str = str(now)
            pipe.set(key, payload, ex=ttl)
            pipe.set(ts_key, ts_str, ex=ttl)
            pipe.set(_key("last_price", symbol), payload)
            pipe.set(_key("last_price", symbol, "ts"), ts_str)
            for snapshot_key in _snapshot_price_keys(symbol):
                pipe.set(snapshot_key, payload, ex=SNAPSHOT_TTL)
            pipe.hset(_key("price", "all"), symbol, payload)
            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(f"Redis set_authoritative_close failed for {symbol}: {e}")
            return False

    async def get_price(self, symbol: str) -> Optional[dict]:
        """
        Fetch latest quote for a symbol from Redis.

        Returns None if key doesn't exist or Redis is unavailable.
        """
        if not self._redis:
            return None

        try:
            aliases = _symbol_aliases(symbol)
            if not aliases:
                return None

            pipe = self._redis.pipeline()
            for sym in aliases:
                pipe.get(_key("price", sym))
            results = await pipe.execute()

            for raw in results:
                if raw:
                    return json.loads(raw)

            return None
        except Exception as e:
            logger.warning(f"Redis get_price failed for {symbol}: {e}")
            return None

    async def get_last_price(self, symbol: str) -> Optional[dict]:
        """Fetch the last persisted tradable quote for a symbol from Redis."""
        if not self._redis:
            return None

        try:
            aliases = _symbol_aliases(symbol)
            if not aliases:
                return None

            pipe = self._redis.pipeline()
            for sym in aliases:
                pipe.get(_key("last_price", sym))
            results = await pipe.execute()

            for raw in results:
                if raw:
                    return json.loads(raw)

            return None
        except Exception as e:
            logger.warning(f"Redis get_last_price failed for {symbol}: {e}")
            return None

    async def get_batch_prices(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch quotes for multiple symbols in a single round-trip."""
        if not self._redis or not symbols:
            return {}

        try:
            normalized_symbols = [
                str(s).strip().upper() for s in symbols if str(s).strip()
            ]
            if not normalized_symbols:
                return {}

            alias_map: dict[str, list[str]] = {
                sym: _symbol_aliases(sym) for sym in normalized_symbols
            }

            # Primary fast path: read current live keys for all aliases in one pipeline.
            primary_pipe = self._redis.pipeline()
            primary_index: list[tuple[str, str]] = []
            for requested_sym, aliases in alias_map.items():
                for alias in aliases:
                    primary_pipe.get(_key("price", alias))
                    primary_index.append((requested_sym, alias))
            primary_results = await primary_pipe.execute()

            quotes: dict[str, dict] = {}
            for (requested_sym, alias), raw in zip(primary_index, primary_results):
                if requested_sym in quotes or not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                    quotes[requested_sym] = parsed
                    if alias != requested_sym:
                        quotes[alias] = parsed
                except Exception:
                    continue

            return quotes
        except Exception as e:
            logger.warning(f"Redis get_batch_prices failed: {e}")
            return {}

    async def get_all_prices(self) -> dict[str, dict]:
        """Fetch all cached prices from the batch hash."""
        if not self._redis:
            return {}

        try:
            raw_map = await self._redis.hgetall(_key("price", "all"))
            return {sym: json.loads(data) for sym, data in raw_map.items()}
        except Exception as e:
            logger.warning(f"Redis get_all_prices failed: {e}")
            return {}

    async def delete_price(self, symbol: str) -> None:
        """Remove a symbol's price data from Redis."""
        if not self._redis:
            return

        try:
            pipe = self._redis.pipeline()
            pipe.delete(_key("price", symbol))
            pipe.delete(_key("price", symbol, "ts"))
            pipe.hdel(_key("price", "all"), symbol)
            pipe.delete(_key("last_price", symbol))
            pipe.delete(_key("last_price", symbol, "ts"))
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Redis delete_price failed for {symbol}: {e}")

    async def clear_market_cache(self) -> dict[str, int]:
        """Remove market-data cache keys so live Zebu data can repopulate them."""
        if not self._redis:
            return {"deleted": 0}

        prefixes = [
            f"{PREFIX}:price",
            f"{PREFIX}:history",
            f"{PREFIX}:snapshot",
            f"{PREFIX}:ticker",
            f"{PREFIX}:indices",
            f"{PREFIX}:commodities",
            f"{PREFIX}:provider:status",
        ]

        deleted = 0
        try:
            pipe = self._redis.pipeline()
            keys: list[str] = []
            for prefix in prefixes:
                async for key in self._redis.scan_iter(match=f"{prefix}*"):
                    keys.append(key)

            if keys:
                pipe.delete(*keys)
                await pipe.execute()
                deleted = len(keys)
        except Exception as e:
            logger.warning(f"Redis clear_market_cache failed: {e}")

        return {"deleted": deleted}

    # ── Subscription tracking ───────────────────────────────────────

    async def set_subscriptions(self, symbols: set[str]) -> None:
        """Store the current subscription set in Redis."""
        if not self._redis:
            return

        try:
            key = _key("subscriptions")
            pipe = self._redis.pipeline()
            pipe.delete(key)
            if symbols:
                pipe.sadd(key, *symbols)
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Redis set_subscriptions failed: {e}")

    async def get_subscriptions(self) -> set[str]:
        """Retrieve the active subscription set."""
        if not self._redis:
            return set()

        try:
            members = await self._redis.smembers(_key("subscriptions"))
            return set(members)
        except Exception as e:
            logger.warning(f"Redis get_subscriptions failed: {e}")
            return set()

    # ── Provider status ─────────────────────────────────────────────

    async def set_provider_status(self, status: dict) -> None:
        """Store provider health info for monitoring dashboards."""
        if not self._redis:
            return

        try:
            await self._redis.set(
                _key("provider", "status"),
                json.dumps(status),
                ex=PROVIDER_STATUS_TTL,
            )
        except Exception as e:
            logger.warning(f"Redis set_provider_status failed: {e}")

    async def get_provider_status(self) -> Optional[dict]:
        """Retrieve provider health info."""
        if not self._redis:
            return None

        try:
            raw = await self._redis.get(_key("provider", "status"))
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"Redis get_provider_status failed: {e}")
            return None

    # ── Quote metadata (Phase 2 — freshness / sequence / emit tracking) ──

    async def set_quote_meta(self, symbol: str, meta: dict) -> bool:
        """Store compact coordination metadata — does not replace price JSON."""
        if not self._redis or not symbol:
            return False
        try:
            key = _key("quote", "meta", symbol)
            await self._redis.hset(key, mapping={k: str(v) for k, v in meta.items()})
            await self._redis.expire(key, PRICE_TTL)
            return True
        except Exception as e:
            logger.debug(f"Redis set_quote_meta failed for {symbol}: {e}")
            return False

    async def get_quote_meta(self, symbol: str) -> Optional[dict]:
        if not self._redis or not symbol:
            return None
        try:
            raw = await self._redis.hgetall(_key("quote", "meta", symbol))
            return raw if raw else None
        except Exception as e:
            logger.debug(f"Redis get_quote_meta failed for {symbol}: {e}")
            return None

    # ── Ticker bar cache (indices + popular stocks) ──────────────────

    async def set_ticker(self, items: list) -> None:
        """Cache the full ticker bar payload (indices + stocks)."""
        if not self._redis:
            return
        try:
            payload = json.dumps(items)
            await self._redis.setex(_key("ticker", "all"), 10, payload)
            await self._redis.set(_key("ticker", "last"), payload)
            await self._redis.set(_key("snapshot", "ticker"), payload, ex=SNAPSHOT_TTL)
        except Exception as e:
            logger.debug(f"Redis set_ticker failed: {e}")

    async def get_ticker(self) -> Optional[list]:
        """Get cached ticker bar payload."""
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(_key("ticker", "all"))
            if raw:
                return json.loads(raw)

            return None
        except Exception as e:
            logger.debug(f"Redis get_ticker failed: {e}")
            return None

    # ── Indices cache ───────────────────────────────────────────────

    async def set_indices(self, items: list) -> None:
        """Cache the indices (NIFTY, SENSEX, etc.)."""
        if not self._redis:
            return
        try:
            payload = json.dumps(items)
            await self._redis.setex(_key("indices", "all"), 10, payload)
            await self._redis.set(_key("indices", "last"), payload)
            await self._redis.set(_key("snapshot", "indices"), payload, ex=SNAPSHOT_TTL)
        except Exception as e:
            logger.debug(f"Redis set_indices failed: {e}")

    async def get_indices(self) -> Optional[list]:
        """Get cached indices."""
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(_key("indices", "all"))
            if raw:
                return json.loads(raw)

            raw = await self._redis.get(_key("snapshot", "indices"))
            if raw:
                return json.loads(raw)

            raw = await self._redis.get(_key("indices", "last"))
            if raw:
                return json.loads(raw)

            return None
        except Exception as e:
            logger.debug(f"Redis get_indices failed: {e}")
            return None

    # ── Commodities cache ───────────────────────────────────────────

    async def set_commodities(self, items: list) -> None:
        """Cache commodities payload (hot + frozen snapshot)."""
        if not self._redis:
            return
        try:
            payload = json.dumps(items)
            await self._redis.setex(_key("commodities", "all"), 10, payload)
            await self._redis.set(_key("commodities", "last"), payload)
            await self._redis.set(
                _key("snapshot", "commodities"), payload, ex=SNAPSHOT_TTL
            )
        except Exception as e:
            logger.debug(f"Redis set_commodities failed: {e}")

    async def get_commodities(self) -> Optional[list]:
        """Get cached commodities payload (hot -> frozen -> last)."""
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(_key("commodities", "all"))
            if raw:
                return json.loads(raw)

            raw = await self._redis.get(_key("snapshot", "commodities"))
            if raw:
                return json.loads(raw)

            raw = await self._redis.get(_key("commodities", "last"))
            if raw:
                return json.loads(raw)

            return None
        except Exception as e:
            logger.debug(f"Redis get_commodities failed: {e}")
            return None

    async def get_commodities_with_source(self) -> Optional[dict]:
        """Get cached commodities payload with cache state.

        Returns:
            {"items": [...], "source": "hot"}
            or None when nothing is cached.
        """
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(_key("commodities", "all"))
            if raw:
                return {"items": json.loads(raw), "source": "hot"}

            raw = await self._redis.get(_key("snapshot", "commodities"))
            if raw:
                return {"items": json.loads(raw), "source": "frozen"}

            raw = await self._redis.get(_key("commodities", "last"))
            if raw:
                return {"items": json.loads(raw), "source": "cache"}

            return None
        except Exception as e:
            logger.debug(f"Redis get_commodities_with_source failed: {e}")
            return None

    # ── Historical OHLCV cache ──────────────────────────────────────

    async def set_history(
        self, symbol: str, period: str, interval: str, candles: list
    ) -> None:
        """Cache OHLCV candles for a symbol."""
        if not self._redis:
            return
        try:
            payload = json.dumps(candles)
            pipe = self._redis.pipeline()
            for key in _history_keys(symbol, period, interval):
                pipe.setex(key, 300, payload)
            # Keep last successful historical snapshot for closed/holiday view.
            for alias in _symbol_aliases(symbol):
                pipe.set(_key("history", "last", alias, period, interval), payload)
            for snapshot_key in _snapshot_history_keys(symbol, interval):
                pipe.set(snapshot_key, payload, ex=SNAPSHOT_TTL)
            await pipe.execute()
        except Exception as e:
            logger.debug(f"Redis set_history({symbol}) failed: {e}")

    async def get_history(
        self, symbol: str, period: str, interval: str
    ) -> Optional[list]:
        """Get cached candles for a symbol."""
        if not self._redis:
            return None
        try:
            pipe = self._redis.pipeline()
            for key in _history_keys(symbol, period, interval):
                pipe.get(key)
            results = await pipe.execute()

            for raw in results:
                if raw:
                    return json.loads(raw)

            return None
        except Exception as e:
            logger.debug(f"Redis get_history({symbol}) failed: {e}")
            return None

    async def get_last_history(
        self, symbol: str, period: str, interval: str
    ) -> Optional[list]:
        """Get last persisted candles for a symbol (no TTL snapshot key)."""
        if not self._redis:
            return None
        try:
            aliases = _symbol_aliases(symbol)
            if not aliases:
                return None

            pipe = self._redis.pipeline()
            for alias in aliases:
                pipe.get(_key("history", "last", alias, period, interval))
            results = await pipe.execute()

            for raw in results:
                if raw:
                    return json.loads(raw)

            return None
        except Exception as e:
            logger.debug(f"Redis get_last_history({symbol}) failed: {e}")
            return None

    # ── Health check ────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        if not self._redis:
            return False
        try:
            return await self._redis.ping()
        except Exception:
            return False


# ── Module-level singleton ──────────────────────────────────────────
_price_cache: Optional[PriceCache] = None
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_last_reconnect_attempt: float = 0.0
_RECONNECT_INTERVAL = 30.0  # seconds between reconnect attempts


def _get_redis_url(redis_url: Optional[str] = None) -> str:
    """Resolve Redis URL: explicit arg → settings → hardcoded default."""
    if redis_url:
        return redis_url
    try:
        from config.settings import settings

        url = getattr(settings, "REDIS_URL", None)
        if url:
            return url
    except Exception:
        pass
    return _DEFAULT_REDIS_URL


async def get_redis(redis_url: Optional[str] = None) -> PriceCache:
    """Get or create the global PriceCache singleton, with reconnect on disconnect."""
    global _price_cache, _last_reconnect_attempt
    now = time.time()

    if _price_cache is None:
        _price_cache = PriceCache(_get_redis_url(redis_url))
        await _price_cache.connect()
    elif (
        not _price_cache.is_connected
        and (now - _last_reconnect_attempt) > _RECONNECT_INTERVAL
    ):
        # Redis was down at startup or dropped — try to reconnect periodically.
        _last_reconnect_attempt = now
        await _price_cache.connect()

    return _price_cache


async def close_redis() -> None:
    """Close the global PriceCache."""
    global _price_cache
    if _price_cache:
        await _price_cache.close()
        _price_cache = None


# ── Convenience module-level functions ──────────────────────────────────────


async def set_price(symbol: str, quote: dict) -> None:
    """Write a price/quote to Redis."""
    cache = await get_redis()
    await cache.set_price(symbol, quote)


async def set_prices_batch(quotes: dict[str, dict]) -> bool:
    """Write multiple prices to Redis in one pipeline."""
    cache = await get_redis()
    return await cache.set_prices_batch(quotes)


async def get_price(symbol: str) -> Optional[dict]:
    """Read a cached price/quote."""
    cache = await get_redis()
    return await cache.get_price(symbol)


async def get_last_price(symbol: str) -> Optional[dict]:
    """Read the last persisted tradable price/quote."""
    cache = await get_redis()
    return await cache.get_last_price(symbol)


async def set_authoritative_close(symbol: str, quote: dict) -> bool:
    """Write official EOD close quote to Redis (price + last_price + snapshot)."""
    cache = await get_redis()
    return await cache.set_authoritative_close(symbol, quote)


async def get_batch_prices(symbols: list[str]) -> dict[str, dict]:
    """Read multiple cached prices in one Redis pipeline round-trip."""
    cache = await get_redis()
    return await cache.get_batch_prices(symbols)


async def set_ticker(items: list) -> None:
    """Cache the ticker bar."""
    cache = await get_redis()
    await cache.set_ticker(items)


async def get_ticker() -> Optional[list]:
    """Get cached ticker."""
    cache = await get_redis()
    return await cache.get_ticker()


async def set_indices(items: list) -> None:
    """Cache indices."""
    cache = await get_redis()
    await cache.set_indices(items)


async def get_indices() -> Optional[list]:
    """Get cached indices."""
    cache = await get_redis()
    return await cache.get_indices()


async def set_commodities(items: list) -> None:
    """Cache commodities payload."""
    cache = await get_redis()
    await cache.set_commodities(items)


async def get_commodities() -> Optional[list]:
    """Get cached commodities payload."""
    cache = await get_redis()
    return await cache.get_commodities()


async def get_commodities_with_source() -> Optional[dict]:
    """Get cached commodities payload with cache state."""
    cache = await get_redis()
    return await cache.get_commodities_with_source()


async def set_history(symbol: str, period: str, interval: str, candles: list) -> None:
    """Cache historical candles."""
    cache = await get_redis()
    await cache.set_history(symbol, period, interval, candles)


async def get_history(symbol: str, period: str, interval: str) -> Optional[list]:
    """Get cached candles."""
    cache = await get_redis()
    return await cache.get_history(symbol, period, interval)


async def get_last_history(symbol: str, period: str, interval: str) -> Optional[list]:
    """Get last persisted historical candles."""
    cache = await get_redis()
    return await cache.get_last_history(symbol, period, interval)


async def clear_market_cache() -> dict[str, int]:
    """Clear all market-data cache entries that can poison live reads."""
    cache = await get_redis()
    return await cache.clear_market_cache()


async def is_available() -> bool:
    """Check if Redis is available."""
    cache = await get_redis()
    return await cache.ping()
