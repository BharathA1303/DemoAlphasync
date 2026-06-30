"""
AlphaSync Alpha AutoTrade — Smart Trade Manager with Trailing Stop v3.

Improved multi-phase trailing stop system:

    Phase 1 (Initial):    SL at 2.0% from entry — room for intraday noise
    Phase 2 (Breakeven):  Once +0.9% profit, SL moves to entry (true zero-loss)
    Phase 3 (Lock Profit): Once +1.5% profit, SL locks in +0.7% profit
    Phase 4 (Trail):      Once +1.9% profit, SL trails at current - 0.6%

Target is set at 3.2% from entry (1:1.6 RR with 2% SL).
This lets winners run while using staged trailing and profit locks to control downside.

Usage:
    mgr = BreakevenManager()
    levels = mgr.compute_levels(entry_price=1400, direction="LONG")
    new_sl = mgr.compute_trailing_sl("LONG", 1400, 1414, 1372)
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeLevels:
    """Complete set of prices for a trade."""

    entry: float
    stop_loss: float
    target: float
    risk_reward_ratio: float
    total_cost: float
    cost_percent: float


class BreakevenManager:
    """
    Smart trade manager with trailing stop-loss system v3.

    Key improvements:
    - Wider initial SL (2.0% vs 1.5%) — fewer noise stopouts
    - Higher target (3.2%) for better upside capture
    - Breakeven trigger at +0.9% to quickly remove downside after confirmation
    - Profit lock at +1.5% to preserve gains before deeper trail mode
    - Tighter trailing distance (0.6%) to protect accumulated P&L
    """

    # ── Stop-loss configuration ─────────────────────────────────────
    INITIAL_SL_PERCENT = 0.018  # 1.8% initial SL (was 2.0%) — tighter, quicker cut
    TARGET_PERCENT = 0.032      # 3.2% target — 1:1.78 RR

    # ── Trailing stop phases ────────────────────────────────────────
    BREAKEVEN_TRIGGER = 0.007   # 0.7% profit → SL moves to entry (was 0.9%)
    LOCK_PROFIT_TRIGGER = 0.013 # 1.3% profit → SL locks +0.6% (was 1.5%/0.7%)
    LOCK_PROFIT_SL = 0.006      # Lock 0.6% profit in SL
    TRAIL_TRIGGER = 0.017       # 1.7% profit → active trailing (was 1.9%)
    TRAIL_DISTANCE = 0.005      # Trail SL 0.5% behind price (was 0.6%) — tighter

    # ── Partial profit-taking ───────────────────────────────────────
    PARTIAL_EXIT_TRIGGER = 0.013  # At +1.3%, exit 50% of position (was 1.5%)
    PARTIAL_EXIT_PCT = 0.50       # Close 50% at partial trigger

    # ── Cost Components (for P&L tracking only) ─────────────────────
    BROKERAGE_PERCENT = 0.0003
    BROKERAGE_FLAT = 20.0
    STT_BUY = 0.001
    STT_SELL = 0.001
    EXCHANGE_CHARGE = 0.0000345
    SEBI_FEE = 0.000001
    GST_RATE = 0.18
    STAMP_DUTY = 0.00015

    def compute_levels(
        self,
        entry_price: float,
        direction: str,
        quantity: int = 1,
        risk_reward_ratio: float = 1.25,
    ) -> TradeLevels:
        """
        Compute initial stop-loss and target prices.

        SL: 2.0% from entry
        Target: 3.2% from entry (1:1.6 RR)
        """
        trade_value = entry_price * quantity

        # Calculate costs
        buy_brokerage = min(trade_value * self.BROKERAGE_PERCENT, self.BROKERAGE_FLAT)
        buy_stt = trade_value * self.STT_BUY
        buy_exchange = trade_value * self.EXCHANGE_CHARGE
        buy_sebi = trade_value * self.SEBI_FEE
        buy_gst = (buy_brokerage + buy_exchange) * self.GST_RATE
        buy_stamp = trade_value * self.STAMP_DUTY
        buy_total = (
            buy_brokerage + buy_stt + buy_exchange + buy_sebi + buy_gst + buy_stamp
        )

        sell_brokerage = min(trade_value * self.BROKERAGE_PERCENT, self.BROKERAGE_FLAT)
        sell_stt = trade_value * self.STT_SELL
        sell_exchange = trade_value * self.EXCHANGE_CHARGE
        sell_sebi = trade_value * self.SEBI_FEE
        sell_gst = (sell_brokerage + sell_exchange) * self.GST_RATE
        sell_total = sell_brokerage + sell_stt + sell_exchange + sell_sebi + sell_gst

        total_cost = buy_total + sell_total
        cost_percent = (total_cost / trade_value * 100) if trade_value > 0 else 0

        sl_distance = entry_price * self.INITIAL_SL_PERCENT
        target_distance = entry_price * self.TARGET_PERCENT

        if direction == "LONG":
            stop_loss = round(entry_price - sl_distance, 2)
            target = round(entry_price + target_distance, 2)
        else:  # SHORT
            stop_loss = round(entry_price + sl_distance, 2)
            target = round(entry_price - target_distance, 2)

        actual_rr = self.TARGET_PERCENT / self.INITIAL_SL_PERCENT

        logger.debug(
            f"Trade levels | {direction} | Entry: {entry_price:.2f} | "
            f"SL: {stop_loss:.2f} ({self.INITIAL_SL_PERCENT*100:.1f}%) | "
            f"Target: {target:.2f} ({self.TARGET_PERCENT*100:.1f}%) | "
            f"RR: 1:{actual_rr:.1f}"
        )

        return TradeLevels(
            entry=entry_price,
            stop_loss=stop_loss,
            target=target,
            risk_reward_ratio=actual_rr,
            total_cost=round(total_cost, 2),
            cost_percent=round(cost_percent, 4),
        )

    def compute_trailing_sl(
        self,
        direction: str,
        entry_price: float,
        current_price: float,
        current_sl: float,
    ) -> float:
        """
        Compute the new trailing stop-loss based on current price.

        The SL only moves in the favorable direction (never widens).

        Phases:
            1. Price < +0.9% → keep initial SL (2.0%)
            2. Price >= +0.9% → move SL to entry (breakeven)
            3. Price >= +1.5% → lock SL at entry + 0.7%
            4. Price >= +1.9% → trail SL at price - 0.6%
        """
        if direction == "LONG":
            profit_pct = (current_price - entry_price) / entry_price
            new_sl = current_sl

            if profit_pct >= self.TRAIL_TRIGGER:
                trail_sl = round(current_price * (1 - self.TRAIL_DISTANCE), 2)
                new_sl = max(new_sl, trail_sl)
            elif profit_pct >= self.LOCK_PROFIT_TRIGGER:
                lock_sl = round(entry_price * (1 + self.LOCK_PROFIT_SL), 2)
                new_sl = max(new_sl, lock_sl)
            elif profit_pct >= self.BREAKEVEN_TRIGGER:
                new_sl = max(new_sl, round(entry_price, 2))

            return new_sl

        else:  # SHORT
            profit_pct = (entry_price - current_price) / entry_price
            new_sl = current_sl

            if profit_pct >= self.TRAIL_TRIGGER:
                trail_sl = round(current_price * (1 + self.TRAIL_DISTANCE), 2)
                new_sl = min(new_sl, trail_sl)
            elif profit_pct >= self.LOCK_PROFIT_TRIGGER:
                lock_sl = round(entry_price * (1 - self.LOCK_PROFIT_SL), 2)
                new_sl = min(new_sl, lock_sl)
            elif profit_pct >= self.BREAKEVEN_TRIGGER:
                new_sl = min(new_sl, round(entry_price, 2))

            return new_sl

    def check_exit(
        self,
        direction: str,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        target: float,
    ) -> Optional[str]:
        """
        Check if current price triggers a stop-loss or target exit.

        Returns:
            "PROFIT" if target hit, "STOPLOSS" if SL hit, None otherwise.
        """
        if direction == "LONG":
            if current_price <= stop_loss:
                return "STOPLOSS"
            if current_price >= target:
                return "PROFIT"
        elif direction == "SHORT":
            if current_price >= stop_loss:
                return "STOPLOSS"
            if current_price <= target:
                return "PROFIT"

        return None

    def should_partial_exit(
        self,
        direction: str,
        entry_price: float,
        current_price: float,
        already_partial: bool = False,
    ) -> bool:
        """
        Check if trade should take partial profits.
        Returns True if profit has reached partial trigger and hasn't been taken yet.
        """
        if already_partial:
            return False

        if direction == "LONG":
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price

        return profit_pct >= self.PARTIAL_EXIT_TRIGGER
