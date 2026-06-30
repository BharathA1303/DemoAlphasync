"""
AlphaSync Risk Engine — Pre-trade validation layer.

Every order (manual or algo-generated) must pass through the Risk Engine
before execution. This provides institutional-grade guardrails.

Usage:
    from engines.risk_engine import risk_engine

    result = await risk_engine.validate_order(db, user_id, order_params)
    if not result.passed:
        return {"success": False, "error": result.reason}
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from models.order import Order
from models.portfolio import Portfolio, Holding
from engines.market_session import market_session

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Configurable risk parameters. Defaults are conservative for demo."""

    max_position_size: int = 10000  # Max qty per symbol per order
    max_capital_per_trade: float = 50000000  # ₹5Cr per trade (simulation)
    max_portfolio_exposure: float = 0.95  # 95% of total capital
    max_open_orders: int = 50  # Max concurrent open orders
    algo_kill_switch: bool = False  # Emergency stop for all algos


@dataclass
class RiskResult:
    """Result of a risk validation check."""

    passed: bool
    reason: Optional[str] = None
    check_name: Optional[str] = None
    details: dict = field(default_factory=dict)


class RiskEngine:
    """
    Pre-trade validation engine. Runs a chain of risk checks before
    any order can be executed.

    Design decisions:
    - Checks run sequentially (not parallel) to fail-fast on first violation.
    - Per-user risk limits will come from a RiskConfig model in Phase 5.
      For now, uses global defaults.
    - Algo kill-switch deactivates ALL algo strategies system-wide.
    """

    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()

    async def validate_order(
        self,
        db: AsyncSession,
        user_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        price: float,
        is_algo: bool = False,
        bypass_market_session: bool = False,
        is_reducing: bool = False,
    ) -> RiskResult:
        """
        Run all risk checks against a proposed order.
        Returns RiskResult with passed=True if all checks pass.
        """
        checks = [
            ("algo_kill_switch", self._check_algo_kill_switch(is_algo)),
            ("position_size", self._check_position_size(quantity)),
            ("capital_per_trade", self._check_capital_per_trade(price, quantity, side)),
            (
                "capital_exposure",
                await self._check_capital_exposure(
                    db, user_id, price, quantity, side, is_reducing=is_reducing
                ),
            ),
            ("open_order_limit", await self._check_open_order_limit(db, user_id)),
        ]
        if not bypass_market_session:
            checks.insert(1, ("market_session", self._check_market_session()))

        for check_name, result in checks:
            if not result.passed:
                result.check_name = check_name
                logger.warning(
                    f"Risk check FAILED [{check_name}] for user={str(user_id)[:8]}...: {result.reason}"
                )
                return result

        return RiskResult(passed=True, check_name="all_passed")

    # ── Individual checks ───────────────────────────────────────────

    def _check_algo_kill_switch(self, is_algo: bool) -> RiskResult:
        """Reject all algo-generated orders if kill switch is active."""
        if is_algo and self.limits.algo_kill_switch:
            return RiskResult(
                passed=False,
                reason="Algo kill-switch is active. All automated trading is suspended.",
            )
        return RiskResult(passed=True)

    def _check_market_session(self) -> RiskResult:
        """Reject orders outside trading hours (unless simulation mode)."""
        if not market_session.can_place_orders():
            state = market_session.get_current_state()
            return RiskResult(
                passed=False,
                reason=f"Market is currently {state.value}. Orders can only be placed during pre-market or market hours.",
            )
        return RiskResult(passed=True)

    def _check_position_size(self, quantity: int) -> RiskResult:
        """Reject orders exceeding max position size."""
        if quantity > self.limits.max_position_size:
            return RiskResult(
                passed=False,
                reason=f"Order quantity ({quantity}) exceeds maximum position size ({self.limits.max_position_size}).",
                details={"max": self.limits.max_position_size, "requested": quantity},
            )
        return RiskResult(passed=True)

    def _check_capital_per_trade(
        self, price: float, quantity: int, side: str
    ) -> RiskResult:
        """Reject BUY orders exceeding per-trade capital limit."""
        if side != "BUY":
            return RiskResult(passed=True)

        trade_value = price * quantity
        if trade_value > self.limits.max_capital_per_trade:
            return RiskResult(
                passed=False,
                reason=f"Trade value (₹{trade_value:,.2f}) exceeds per-trade limit (₹{self.limits.max_capital_per_trade:,.2f}).",
                details={
                    "trade_value": trade_value,
                    "limit": self.limits.max_capital_per_trade,
                },
            )
        return RiskResult(passed=True)

    async def _check_capital_exposure(
        self,
        db: AsyncSession,
        user_id: str,
        price: float,
        quantity: int,
        side: str,
        is_reducing: bool = False,
    ) -> RiskResult:
        """Reject if total portfolio exposure would exceed limit."""
        if side != "BUY" or is_reducing:
            return RiskResult(passed=True)

        result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
        portfolio = result.scalar_one_or_none()
        if not portfolio:
            return RiskResult(passed=True)  # No portfolio = new user

        available_capital = float(portfolio.available_capital or 0)
        total_invested = float(portfolio.total_invested or 0)
        total_capital = available_capital + total_invested
        new_invested = total_invested + (price * quantity)
        exposure_ratio = new_invested / total_capital if total_capital > 0 else 0

        if exposure_ratio > self.limits.max_portfolio_exposure:
            return RiskResult(
                passed=False,
                reason=(
                    f"This trade would bring portfolio exposure to {exposure_ratio:.0%}, "
                    f"exceeding the {self.limits.max_portfolio_exposure:.0%} limit."
                ),
                details={
                    "exposure": exposure_ratio,
                    "limit": self.limits.max_portfolio_exposure,
                },
            )
        return RiskResult(passed=True)

    async def _check_open_order_limit(
        self, db: AsyncSession, user_id: str
    ) -> RiskResult:
        """Reject if too many open orders."""
        result = await db.execute(
            select(func.count(Order.id)).where(
                and_(Order.user_id == user_id, Order.status == "OPEN")
            )
        )
        open_count = result.scalar() or 0

        if open_count >= self.limits.max_open_orders:
            return RiskResult(
                passed=False,
                reason=f"You have {open_count} open orders (limit: {self.limits.max_open_orders}). Cancel some before placing new orders.",
                details={
                    "open_orders": open_count,
                    "limit": self.limits.max_open_orders,
                },
            )
        return RiskResult(passed=True)

    # ── Admin controls ──────────────────────────────────────────────

    def activate_kill_switch(self) -> None:
        """Emergency: halt all algo trading."""
        self.limits.algo_kill_switch = True
        logger.critical("RISK: Algo kill-switch ACTIVATED")

    def deactivate_kill_switch(self) -> None:
        """Resume algo trading."""
        self.limits.algo_kill_switch = False
        logger.info("RISK: Algo kill-switch deactivated")

    def update_limits(self, **kwargs) -> None:
        """Update risk limits dynamically."""
        for key, value in kwargs.items():
            if hasattr(self.limits, key):
                setattr(self.limits, key, value)
                logger.info(f"Risk limit updated: {key} = {value}")

    def get_status(self) -> dict:
        """Return current risk engine status for API/health checks."""
        return {
            "kill_switch_active": self.limits.algo_kill_switch,
            "limits": {
                "max_position_size": self.limits.max_position_size,
                "max_capital_per_trade": self.limits.max_capital_per_trade,
                "max_portfolio_exposure": self.limits.max_portfolio_exposure,
                "max_open_orders": self.limits.max_open_orders,
            },
        }


# ── Singleton instance ─────────────────────────────────────────────
risk_engine = RiskEngine()
