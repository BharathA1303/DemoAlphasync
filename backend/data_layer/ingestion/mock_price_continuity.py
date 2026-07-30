"""Deterministic day-to-day price continuity for mock EOD generators.

Each mock generator used to draw a brand new `rng.uniform(lo, hi)` base
price independently for every calendar day, with no link to the previous
day's close. Since the internal simulator's tick engine computes
change/change_percent by comparing today's simulated price against
whatever the previous session's last close happened to be, that produced
huge, unrealistic day-over-day jumps (a stock "moving" +3000% overnight)
purely because the mock data had no notion of continuity.

`anchor_price_for_date` fixes this the same way real markets work: each
symbol gets one fixed anchor price at a reference date, compounded by a
small deterministic daily drift. Any date can still be computed
independently (safe to backfill/re-run/seed in any order), but consecutive
trading days now sit close to each other in price.
"""
from datetime import date

_REFERENCE_DATE = date(2024, 1, 1)


def anchor_price_for_date(base_price: float, daily_drift: float, target_date: date) -> float:
    days_elapsed = (target_date - _REFERENCE_DATE).days
    return base_price * ((1 + daily_drift) ** days_elapsed)
