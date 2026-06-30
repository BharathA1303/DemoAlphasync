"""
Symbol priority tiers — orchestration overlay (does not remove subscriptions).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional


class PriorityTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


# Bootstrap HOT universe (indices + ticker staples) — matches market_data lists.
def _bootstrap_hot_symbols() -> set[str]:
    symbols: set[str] = set()
    try:
        from services.market_data import INDIAN_INDICES, POPULAR_INDIAN_STOCKS

        for item in INDIAN_INDICES:
            sym = str(item.get("symbol") or "").strip().upper()
            if sym:
                symbols.add(sym)
        for item in POPULAR_INDIAN_STOCKS:
            sym = str(item.get("symbol") or "").strip().upper()
            if sym:
                symbols.add(sym)
    except Exception:
        pass
    return symbols


class SymbolPriorityEngine:
    """
    Tracks per-symbol tier. HOT = lowest latency path.
    Futures contract symbols can be registered as HOT without touching equity store.
    """

    def __init__(self) -> None:
        self._tiers: dict[str, PriorityTier] = {}
        self._last_touch: dict[str, float] = {}
        for sym in _bootstrap_hot_symbols():
            self._tiers[sym] = PriorityTier.HOT

    def register(self, symbol: str, tier: PriorityTier) -> None:
        sym = str(symbol or "").strip().upper()
        if not sym:
            return
        prev = self._tiers.get(sym)
        if prev is None or _tier_rank(tier) < _tier_rank(prev):
            self._tiers[sym] = tier
        self._last_touch[sym] = time.time()

    def touch(self, symbol: str) -> None:
        sym = str(symbol or "").strip().upper()
        if sym:
            self._last_touch[sym] = time.time()

    def get_tier(self, symbol: str) -> PriorityTier:
        sym = str(symbol or "").strip().upper()
        if not sym:
            return PriorityTier.COLD
        if sym in self._tiers:
            return self._tiers[sym]
        # Recently viewed symbols decay to WARM
        last = self._last_touch.get(sym)
        if last and (time.time() - last) < 600:
            return PriorityTier.WARM
        return PriorityTier.COLD

    def list_by_tier(self, tier: PriorityTier) -> list[str]:
        return [s for s, t in self._tiers.items() if t == tier]

    def emit_interval_sec(self, tier: PriorityTier) -> float:
        if tier == PriorityTier.HOT:
            return 0.0
        if tier == PriorityTier.WARM:
            return 0.25
        return 1.0


def _tier_rank(tier: PriorityTier) -> int:
    if tier == PriorityTier.HOT:
        return 0
    if tier == PriorityTier.WARM:
        return 1
    return 2


symbol_priority_engine = SymbolPriorityEngine()
