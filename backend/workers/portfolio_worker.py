"""
Portfolio Recalculation Worker — Event-driven portfolio updates.

Unlike other workers that poll on timers, this worker is PURELY
event-driven. It subscribes to ORDER_FILLED events and recalculates
the affected user's portfolio.
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, and_

from core.event_bus import event_bus, Event, EventType
from database.connection import async_session_factory
from models.order import Order
from models.portfolio import Portfolio, Holding, Transaction
from models.user import User
from services import market_data
from services.portfolio_service import invalidate_user_portfolio_cache

logger = logging.getLogger(__name__)


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_available_capital(
    available_capital: Decimal, net_equity: Decimal, holdings_count: int
) -> Decimal:
    if holdings_count <= 0:
        return net_equity
    if available_capital > net_equity:
        return net_equity
    return available_capital


class PortfolioRecalcWorker:
    """
    Recalculates portfolio on order fills.

    Registered as an event handler (not a loop):
        event_bus.subscribe(EventType.ORDER_FILLED, worker.on_order_filled)
    """

    def __init__(self):
        self._stats = {"recalcs": 0, "errors": 0}

    async def on_order_filled(self, event: Event) -> None:
        """
        Handle ORDER_FILLED event from Order Execution Worker.

        Updates the user's portfolio, holdings, creates a transaction
        record, and emits PORTFOLIO_UPDATED for the WebSocket layer.

        NOTE: Events from 'trading_engine' source are skipped because
        MARKET orders already update the portfolio inline during place_order().
        This handler only processes fills from the order_execution_worker
        (LIMIT/STOP_LOSS fills that happen asynchronously).
        """
        # Order fills are already applied by trading_engine/order_worker.
        # This worker should remain idempotent and only sync portfolio snapshots.
        if event.source == "trading_engine":
            user_id = event.data.get("user_id")
            if user_id:
                await self._emit_portfolio_snapshot(user_id)
            return

        order_id = event.data.get("order_id")
        user_id = event.data.get("user_id")
        symbol = event.data.get("symbol")
        side = event.data.get("side")
        quantity = event.data.get("quantity")
        filled_price = event.data.get("filled_price")

        if not all([order_id, user_id, symbol, side, quantity, filled_price]):
            logger.error(f"Incomplete ORDER_FILLED event data: {event.data}")
            return

        import uuid
        user_id = uuid.UUID(str(user_id)) if isinstance(user_id, (str, uuid.UUID)) else user_id
        order_id = uuid.UUID(str(order_id)) if isinstance(order_id, (str, uuid.UUID)) else order_id

        logger.info(
            f"Portfolio recalc triggered: {side} {quantity}x {symbol} "
            f"@ ₹{filled_price:.2f} for user {str(user_id)[:8]}..."
        )

        async with async_session_factory() as db:
            try:
                # Idempotency guard: if this order already created a transaction,
                # skip mutation to prevent duplicate holding inserts/updates.
                existing_txn = await db.execute(
                    select(Transaction.id).where(
                        and_(
                            Transaction.user_id == user_id,
                            Transaction.order_id == order_id,
                        )
                    )
                )
                if existing_txn.scalar_one_or_none() is not None:
                    await self._emit_portfolio_snapshot(user_id)
                    return

                # Get or create portfolio
                result = await db.execute(
                    select(Portfolio).where(Portfolio.user_id == user_id)
                )
                portfolio = result.scalar_one_or_none()

                if not portfolio:
                    logger.error(f"No portfolio found for user {user_id}")
                    return

                await db.execute(
                    select(Portfolio.id)
                    .where(Portfolio.id == portfolio.id)
                    .with_for_update()
                )

                filled_price = _to_decimal(filled_price)
                total_value = filled_price * quantity

                if side == "BUY":
                    await self._handle_buy(
                        db,
                        portfolio,
                        symbol,
                        quantity,
                        filled_price,
                        total_value,
                        user_id,
                    )
                elif side == "SELL":
                    await self._handle_sell(
                        db,
                        portfolio,
                        symbol,
                        quantity,
                        filled_price,
                        total_value,
                        user_id,
                    )

                # Create transaction record
                db.add(
                    Transaction(
                        user_id=user_id,
                        order_id=order_id,
                        symbol=symbol,
                        transaction_type=side,
                        quantity=quantity,
                        price=filled_price,
                        total_value=total_value,
                    )
                )

                # Recalculate portfolio totals
                await self._recalculate_totals(db, portfolio)

                await db.commit()
                self._stats["recalcs"] += 1
                invalidate_user_portfolio_cache(str(user_id))

                # Emit portfolio update for WebSocket
                await self._emit_portfolio_snapshot(user_id)

            except Exception as e:
                await db.rollback()
                self._stats["errors"] += 1
                logger.error(
                    f"Portfolio recalc failed for user {user_id}: {e}", exc_info=True
                )

    async def _emit_portfolio_snapshot(self, user_id: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Portfolio).where(Portfolio.user_id == user_id)
            )
            portfolio = result.scalar_one_or_none()
            if not portfolio:
                return
            await event_bus.emit(
                Event(
                    type=EventType.PORTFOLIO_UPDATED,
                    data={
                        "user_id": user_id,
                        "available_capital": float(portfolio.available_capital or 0),
                        "total_invested": float(portfolio.total_invested or 0),
                        "total_pnl": float(portfolio.total_pnl or 0),
                    },
                    user_id=user_id,
                    source="portfolio_worker",
                )
            )

    async def _handle_buy(
        self,
        db,
        portfolio: Portfolio,
        symbol: str,
        quantity: int,
        price,
        total_value,
        user_id: str,
    ) -> None:
        """Update portfolio for a BUY fill."""
        price = _to_decimal(price)
        total_value = _to_decimal(total_value)

        # Cap deduction at available capital — prevents negative balance from
        # concurrent LIMIT orders that were placed before capital was spent elsewhere
        available = _to_decimal(portfolio.available_capital or 0)
        deduct = min(total_value, available)
        portfolio.available_capital = available - deduct
        portfolio.total_invested += deduct

        # Get or create holding
        result = await db.execute(
            select(Holding).where(
                and_(Holding.portfolio_id == portfolio.id, Holding.symbol == symbol)
            )
        )
        holding = result.scalar_one_or_none()

        if holding:
            # Average up
            old_value = holding.quantity * holding.avg_price
            new_value = old_value + total_value
            holding.quantity += quantity
            holding.avg_price = new_value / holding.quantity
            holding.invested_value = holding.avg_price * holding.quantity
            holding.current_price = price
            holding.current_value = price * holding.quantity
            holding.pnl = holding.current_value - holding.invested_value
            holding.pnl_percent = (
                (holding.pnl / holding.invested_value * 100)
                if holding.invested_value
                else 0
            )
        else:
            # Fetch symbol name
            quote = await market_data.get_quote_safe(symbol, user_id)
            name = quote.get("name", symbol) if quote else symbol

            holding = Holding(
                portfolio_id=portfolio.id,
                symbol=symbol,
                company_name=name,
                quantity=quantity,
                avg_price=price,
                current_price=price,
                invested_value=total_value,
                current_value=total_value,
            )
            db.add(holding)

    async def _handle_sell(
        self,
        db,
        portfolio: Portfolio,
        symbol: str,
        quantity: int,
        price,
        total_value,
        user_id: str,
    ) -> None:
        """Update portfolio for a SELL fill."""
        price = _to_decimal(price)
        total_value = _to_decimal(total_value)
        result = await db.execute(
            select(Holding).where(
                and_(Holding.portfolio_id == portfolio.id, Holding.symbol == symbol)
            )
        )
        holding = result.scalar_one_or_none()

        if not holding:
            logger.error(
                f"No holding found for SELL: {symbol} — skipping portfolio update"
            )
            return

        # Clamp quantity to what is actually held (safety guard)
        actual_qty = min(quantity, holding.quantity)
        if actual_qty <= 0:
            logger.error(
                f"No shares to sell for {symbol} (holding qty={holding.quantity})"
            )
            return
        if actual_qty != quantity:
            logger.warning(
                f"SELL {symbol}: requested {quantity}, only {actual_qty} held — clamping"
            )
            quantity = actual_qty
            total_value = price * _to_decimal(quantity)

        # Calculate realized P&L
        realized_pnl = (price - holding.avg_price) * quantity

        portfolio.available_capital += total_value
        portfolio.total_invested -= holding.avg_price * quantity
        portfolio.total_pnl += realized_pnl

        holding.quantity -= quantity
        if holding.quantity <= 0:
            await db.delete(holding)
        else:
            holding.invested_value = holding.avg_price * holding.quantity
            holding.current_value = price * holding.quantity
            holding.pnl = holding.current_value - holding.invested_value
            holding.pnl_percent = (
                (holding.pnl / holding.invested_value * 100)
                if holding.invested_value
                else 0
            )

    async def _recalculate_totals(self, db, portfolio: Portfolio) -> None:
        """Recalculate portfolio market value and unrealized P&L."""
        result = await db.execute(
            select(Holding).where(Holding.portfolio_id == portfolio.id)
        )
        holdings = result.scalars().all()

        total_current_value = Decimal("0")
        total_invested_value = Decimal("0")

        for holding in holdings:
            quote = await market_data.get_system_quote_safe(holding.symbol)
            if quote and "price" in quote:
                current_price = _to_decimal(quote["price"])
                holding.current_price = current_price
                holding.pnl = (current_price - holding.avg_price) * holding.quantity
                total_current_value += current_price * holding.quantity
            else:
                total_current_value += holding.avg_price * holding.quantity

            total_invested_value += holding.avg_price * holding.quantity

        portfolio.current_value = total_current_value
        portfolio.total_invested = total_invested_value
        unrealized_pnl = total_current_value - total_invested_value
        realized_pnl = _to_decimal(portfolio.total_pnl or 0)

        user_result = await db.execute(
            select(User.virtual_capital).where(User.id == portfolio.user_id)
        )
        base_capital = _to_decimal(user_result.scalar_one_or_none() or 0)
        pnl_denominator = (
            abs(base_capital)
            if base_capital
            else (abs(total_invested_value) if total_invested_value else Decimal("0"))
        )
        net_equity = base_capital + realized_pnl + unrealized_pnl
        portfolio.available_capital = _normalize_available_capital(
            _to_decimal(portfolio.available_capital or 0),
            net_equity,
            len(holdings),
        )
        portfolio.total_pnl_percent = (
            ((realized_pnl + unrealized_pnl) / pnl_denominator * 100)
            if pnl_denominator
            else 0
        )

    def get_stats(self) -> dict:
        return self._stats.copy()


# ── Singleton ──────────────────────────────────────────────────────
portfolio_recalc_worker = PortfolioRecalcWorker()
