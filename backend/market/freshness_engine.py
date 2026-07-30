"""
Quote freshness classification (LIVE / DELAYED / STALE / FROZEN / EOD).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from market.symbol_priority_engine import PriorityTier, symbol_priority_engine


class FreshnessState(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    FROZEN = "FROZEN"
    EOD = "EOD"


def _parse_ts(quote: dict) -> Optional[float]:
    raw = quote.get("exchange_timestamp") or quote.get("timestamp") or quote.get(
        "last_trade_time"
    )
    if raw in (None, ""):
        return None
    try:
        numeric = float(raw)
        if numeric > 1e12:
            numeric /= 1000.0
        if numeric > 1e9:
            return numeric
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def classify_freshness(
    symbol: str,
    quote: dict,
    *,
    market_open: bool,
    last_tick_at: Optional[float] = None,
) -> FreshnessState:
    source = str(quote.get("source") or "").lower()
    if source in ("official_eod_close", "eod"):
        return FreshnessState.EOD
    if source in ("frozen", "history_snapshot"):
        return FreshnessState.FROZEN

    if not market_open:
        return FreshnessState.FROZEN

    now = time.time()
    tick_at = last_tick_at or _parse_ts(quote) or now
    age = max(0.0, now - tick_at)
    tier = symbol_priority_engine.get_tier(symbol)

    hot_limit = 2.0
    warm_limit = 8.0
    if tier == PriorityTier.WARM:
        hot_limit = 4.0
        warm_limit = 20.0
    elif tier == PriorityTier.COLD:
        hot_limit = 15.0
        warm_limit = 45.0

    if age <= hot_limit:
        return FreshnessState.LIVE
    if age <= warm_limit:
        return FreshnessState.DELAYED
    return FreshnessState.STALE


def enrich_quote_metadata(
    symbol: str,
    quote: dict,
    *,
    source: str,
    sequence: int,
    market_open: bool,
    last_tick_at: float,
) -> dict:
    sym = str(symbol or "").strip().upper()
    tier = symbol_priority_engine.get_tier(sym)
    state = classify_freshness(sym, quote, market_open=market_open, last_tick_at=last_tick_at)
    enriched = {
        **quote,
        "symbol": sym or quote.get("symbol"),
        "source": source,
        "sequence": sequence,
        "freshness_state": state.value,
        "priority_tier": tier.value,
        "coordinator_ts": time.time(),
    }
    if "exchange_timestamp" not in enriched:
        ts = _parse_ts(quote)
        if ts:
            enriched["exchange_timestamp"] = ts
    return enriched
