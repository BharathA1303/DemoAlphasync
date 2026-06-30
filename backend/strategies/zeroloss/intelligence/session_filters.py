"""
Session-level trade permission filters (additive).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

from engines.market_session import market_session

IST = ZoneInfo("Asia/Kolkata")

# Align with controller constants — additive lunch band
LUNCH_START = time(12, 0)
LUNCH_END = time(13, 0)
OPENING_CHAOS_END = time(9, 20)
LATE_ENTRY_CUTOFF = time(15, 0)


@dataclass
class SessionFilterResult:
    allowed: bool = True
    reasons: list[str] = field(default_factory=list)


class SessionTradeFilter:
    """Time-of-day and session-state gates without changing controller time constants."""

    @staticmethod
    def evaluate(
        *,
        simulation_mode: bool | None = None,
        extra_block_reasons: list[str] | None = None,
    ) -> SessionFilterResult:
        if not market_session.is_live_trading_session():
            return SessionFilterResult(allowed=False, reasons=["market_closed"])

        now_ist = datetime.now(IST).time()
        reasons: list[str] = []

        if now_ist < OPENING_CHAOS_END:
            reasons.append("opening_chaos_window")
        if LUNCH_START <= now_ist < LUNCH_END:
            reasons.append("lunch_dead_zone")
        if now_ist >= LATE_ENTRY_CUTOFF:
            reasons.append("late_session_cutoff")

        if extra_block_reasons:
            reasons.extend(extra_block_reasons)

        return SessionFilterResult(allowed=len(reasons) == 0, reasons=reasons)
