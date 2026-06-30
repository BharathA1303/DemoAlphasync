"""
Safe quote overwrite rules — newer timestamp / sequence / source priority wins.
"""

from __future__ import annotations

import time
from typing import Any, Optional


_SOURCE_RANK_OPEN = {
    "live_ws": 5,
    "live": 5,
    "market_data_worker": 4,
    "poll": 3,
    "worker": 3,
    "rest": 2,
    "history_snapshot": 1,
    "frozen": 1,
    "eod": 6,  # wins when market closed
}

_SOURCE_RANK_CLOSED = {
    "official_eod_close": 11,
    "eod": 10,
    "frozen": 9,
    "history_snapshot": 8,
    "live_ws": 0,
    "live": 0,
    "poll": 4,
    "worker": 4,
}


def _parse_ts(quote: dict) -> float:
    raw = quote.get("exchange_timestamp") or quote.get("timestamp") or quote.get(
        "last_trade_time"
    )
    if raw in (None, ""):
        return time.time()
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
        return time.time()


def _source_rank(source: str, market_open: bool) -> int:
    key = str(source or "").lower()
    table = _SOURCE_RANK_OPEN if market_open else _SOURCE_RANK_CLOSED
    return table.get(key, 2)


def should_accept_overwrite(
    existing: Optional[dict],
    incoming: dict,
    *,
    source: str,
    market_open: bool,
) -> bool:
    """Return True if incoming quote should replace existing authority."""
    if not existing:
        return True

    inc_ts = _parse_ts(incoming)
    ex_ts = _parse_ts(existing)
    if inc_ts > ex_ts + 0.001:
        return True
    if inc_ts < ex_ts - 0.001:
        return False

    inc_seq = int(incoming.get("sequence") or 0)
    ex_seq = int(existing.get("sequence") or 0)
    if inc_seq > ex_seq:
        return True
    if inc_seq < ex_seq:
        return False

    inc_rank = _source_rank(source, market_open)
    ex_rank = _source_rank(str(existing.get("source") or ""), market_open)
    if inc_rank > ex_rank:
        return True
    if inc_rank < ex_rank:
        return False

    # Same second — allow live to refresh price fields
    inc_price = incoming.get("price") or incoming.get("ltp")
    ex_price = existing.get("price") or existing.get("ltp")
    if inc_price is not None and inc_price != ex_price:
        return _source_rank(source, market_open) >= _source_rank(
            str(existing.get("source") or ""), market_open
        )

    return False


def normalize_for_storage(quote: dict) -> dict:
    """Ensure canonical price field exists for Redis + WS."""
    out = dict(quote)
    price = out.get("price") or out.get("ltp") or out.get("lp")
    if price is not None:
        try:
            out["price"] = float(price)
        except (TypeError, ValueError):
            pass
    return out
