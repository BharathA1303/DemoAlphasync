"""
Futures Order Execution Worker — Background LIMIT/STOP_LOSS order evaluator for futures.

Periodically scans ALL open futures orders across all users and evaluates them
against current market prices. Fills orders that meet their conditions.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from core.event_bus import event_bus, Event, EventType
from engines.market_session import market_session
from database.connection import async_session_factory
from models.futures_order import FuturesOrder, FuturesPosition
from models.portfolio import Portfolio
from services import futures_service

logger = logging.getLogger(__name__)

# Orders older than this are expired automatically
ORDER_EXPIRY_DAYS = 7


def _to_decimal(value) -> Decimal | None:
    try:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except Exception:
        return None


class FuturesOrderExecutionWorker:
    """
    Evaluates OPEN futures orders against live prices.

    Two evaluation paths:
    1. Tick-driven: on_futures_tick() called from EventBus FUTURES_QUOTE events
       for near-instant fills when WS ticks arrive.
    2. Periodic sweep: fallback every 15s to catch orders missed by tick path.
    """

    EVAL_INTERVAL = 15  # seconds between fallback sweeps (reduced from 5 since ticks handle most fills)

    def __init__(self):
        self._running = False
        self._stats = {"sweeps": 0, "tick_evals": 0, "fills": 0, "expired": 0, "errors": 0}
        self._open_orders_cache: dict[str, list] = {}  # contract_symbol -> [order_ids]

    async def on_futures_tick(self, event) -> None:
        """EventBus handler: evaluate open orders on every FUTURES_QUOTE tick."""
        try:
            contract_symbol = event.data.get("contract_symbol")
            quote = event.data.get("quote")
            if not contract_symbol or not quote:
                return

            ltp = quote.get("ltp")
            if not ltp or ltp <= 0:
                return

            self._stats["tick_evals"] += 1

            async with async_session_factory() as db:
                try:
                    result = await db.execute(
                        select(FuturesOrder).where(
                            and_(
                                FuturesOrder.status == "OPEN",
                                FuturesOrder.contract_symbol == contract_symbol,
                            )
                        )
                    )
                    orders = result.scalars().all()
                    if not orders:
                        return

                    for order in orders:
                        await self._evaluate_order_with_price(db, order, _to_decimal(ltp))

                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.debug(f"Tick-driven order eval error for {contract_symbol}: {e}")
        except Exception as e:
            logger.debug(f"on_futures_tick handler error: {e}")

    async def run(self) -> None:
        """Main loop — started via asyncio.create_task in lifespan."""
        self._running = True
        logger.info("Futures Order Execution Worker started (tick-driven + periodic sweep)")

        while self._running:
            try:
                await self._sweep()
                self._stats["sweeps"] += 1
                await asyncio.sleep(self.EVAL_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Worker sweep error: {e}")
                self._stats["errors"] += 1
                await asyncio.sleep(self.EVAL_INTERVAL)

        logger.info(f"Futures Order Execution Worker stopped. Stats: {self._stats}")

    async def stop(self) -> None:
        """Stop the worker gracefully."""
        self._running = False

    async def _sweep(self) -> None:
        """Scan all open orders and evaluate them."""
        async with async_session_factory() as db:
            try:
                # Get all OPEN orders
                result = await db.execute(
                    select(FuturesOrder).where(FuturesOrder.status == "OPEN")
                )
                orders = result.scalars().all()

                for order in orders:
                    await self._evaluate_order(db, order)

                await db.commit()

            except Exception as e:
                logger.exception(f"Sweep error: {e}")
                await db.rollback()

    async def _evaluate_order(self, db: AsyncSession, order: FuturesOrder) -> None:
        """Evaluate a single order against current market price (periodic sweep path)."""
        if order.created_at:
            age = (datetime.now(timezone.utc) - order.created_at).days
            if age > ORDER_EXPIRY_DAYS:
                order.status = "EXPIRED"
                order.updated_at = datetime.now(timezone.utc)
                self._stats["expired"] += 1
                await event_bus.emit(
                    Event(
                        type=EventType.FUTURES_ORDER_EXPIRED,
                        user_id=order.user_id,
                        data={"order_id": str(order.id)},
                    )
                )
                return

        try:
            quote = await futures_service.get_quote(order.contract_symbol)
            if not quote:
                return
            raw_price = quote.get("ltp") or quote.get("price") or quote.get("lp")
            if not raw_price:
                return
            current_price = _to_decimal(raw_price)
            if not current_price or current_price <= 0:
                return
            await self._evaluate_order_with_price(db, order, current_price)
        except Exception as e:
            logger.exception(f"Error evaluating order {order.id}: {e}")

    async def _evaluate_order_with_price(
        self, db: AsyncSession, order: FuturesOrder, current_price: Decimal
    ) -> None:
        """Core order evaluation logic — used by both tick-driven and sweep paths."""
        if order.status != "OPEN":
            return

        should_fill = False

        if order.order_type == "LIMIT":
            limit_price = _to_decimal(order.price)
            if order.side == "BUY" and current_price <= limit_price:
                should_fill = True
            elif order.side == "SELL" and current_price >= limit_price:
                should_fill = True

        elif order.order_type == "STOP_LOSS":
            trigger = _to_decimal(order.trigger_price)
            if order.side == "BUY" and current_price >= trigger:
                should_fill = True
            elif order.side == "SELL" and current_price <= trigger:
                should_fill = True

        elif order.order_type == "STOP_LOSS_LIMIT":
            trigger = _to_decimal(order.trigger_price)
            limit_price = _to_decimal(order.price)
            if order.side == "BUY":
                if current_price >= trigger and current_price <= limit_price:
                    should_fill = True
            else:
                if current_price <= trigger and current_price >= limit_price:
                    should_fill = True

        if should_fill:
            order.status = "FILLED"
            order.filled_quantity = order.quantity
            order.filled_price = current_price
            order.executed_at = datetime.now(timezone.utc)

            await self._update_position_on_fill(
                db, order.user_id, order.contract_symbol,
                order.side, order.quantity, current_price,
            )

            self._stats["fills"] += 1

            await event_bus.emit(
                Event(
                    type=EventType.FUTURES_ORDER_FILLED,
                    user_id=order.user_id,
                    data={
                        "order_id": str(order.id),
                        "contract_symbol": order.contract_symbol,
                        "side": order.side,
                        "quantity": order.quantity,
                        "filled_price": float(current_price),
                    },
                )
            )

    async def _update_position_on_fill(
        self,
        db: AsyncSession,
        user_id: str,
        contract_symbol: str,
        side: str,
        quantity: int,
        filled_price: Decimal,
    ) -> None:
        """Update position after order fill (simplified version)."""
        try:
            # Get portfolio
            result = await db.execute(
                select(Portfolio).where(Portfolio.user_id == user_id)
            )
            portfolio = result.scalar_one_or_none()
            if not portfolio:
                return

            # Get position
            result = await db.execute(
                select(FuturesPosition).where(
                    and_(
                        FuturesPosition.user_id == user_id,
                        FuturesPosition.contract_symbol == contract_symbol,
                    )
                )
            )
            position = result.scalar_one_or_none()

            from workers.futures_margin_engine import get_margin_fraction

            margin_rate = get_margin_fraction(contract_symbol)
            margin_requirement = (filled_price * quantity) * margin_rate

            if not position:
                position = FuturesPosition(
                    user_id=user_id,
                    contract_symbol=contract_symbol,
                    quantity=quantity if side == "BUY" else -quantity,
                    avg_entry_price=filled_price,
                    current_price=filled_price,
                )
                db.add(position)
                portfolio.available_capital = (portfolio.available_capital or Decimal("0")) - margin_requirement
            else:
                old_qty = position.quantity
                new_qty = old_qty + (quantity if side == "BUY" else -quantity)

                if new_qty == 0:
                    # Full close — correct PnL for LONG vs SHORT
                    if old_qty > 0:
                        pnl = (filled_price - position.avg_entry_price) * abs(old_qty)
                    else:
                        pnl = (position.avg_entry_price - filled_price) * abs(old_qty)
                    position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl
                    position.quantity = 0
                    portfolio.available_capital = (portfolio.available_capital or Decimal("0")) + margin_requirement
                else:
                    if (old_qty > 0 and side == "BUY") or (old_qty < 0 and side == "SELL"):
                        new_avg = (abs(old_qty) * position.avg_entry_price + quantity * filled_price) / abs(new_qty)
                        position.avg_entry_price = new_avg
                        portfolio.available_capital = (portfolio.available_capital or Decimal("0")) - margin_requirement
                    else:
                        # Partial close — correct PnL direction
                        if old_qty > 0:
                            pnl = (filled_price - position.avg_entry_price) * quantity
                        else:
                            pnl = (position.avg_entry_price - filled_price) * quantity
                        position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl
                        portfolio.available_capital = (portfolio.available_capital or Decimal("0")) + margin_requirement

                    position.quantity = new_qty

                position.updated_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.exception(f"Error updating position: {e}")


# Global worker instance
futures_order_worker = FuturesOrderExecutionWorker()
