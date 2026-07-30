"""
Order Execution Worker — Background LIMIT/STOP_LOSS order evaluator.

Periodically scans ALL open orders across all users and evaluates them
against current market prices. Fills orders that meet their conditions
and emits ORDER_FILLED events.

This worker solves the critical gap: check_pending_orders() in
trading_engine.py exists but is never called.
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
from models.order import Order
from models.portfolio import Portfolio, Holding
from services import market_data
from services.trading_engine import (
    _create_bracket_child_orders,
    _update_portfolio_on_fill,
)

logger = logging.getLogger(__name__)

# Orders older than this are expired automatically
ORDER_EXPIRY_DAYS = 7


def _utcnow():
    from market_data.replay.simulation_clock import simulation_clock
    return simulation_clock.now()


def _coerce_utc_datetime(value):
    if value is None:
        return None

    dt = value
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None

    if not isinstance(dt, datetime):
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _to_decimal(value) -> Decimal | None:
    try:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except Exception:
        return None


def _reserved_amount_for_open_buy_order(order: Order) -> Decimal:
    if not (
        order.side == "BUY"
        and order.order_type in ("LIMIT", "BRACKET")
        and order.price is not None
    ):
        return Decimal("0")

    order_price = _to_decimal(order.price)
    if order_price is None or order_price <= 0:
        return Decimal("0")

    qty = max((order.quantity or 0) - (order.filled_quantity or 0), 0)
    if qty <= 0:
        return Decimal("0")

    product_type = (order.product_type or "CNC").upper()
    if product_type == "MIS":
        return (order_price * Decimal(qty)) / Decimal("5")
    return order_price * Decimal(qty)


class OrderExecutionWorker:
    """
    Continuously evaluates OPEN orders against live prices.

    Design:
    - Sweeps ALL users' open orders in a single pass (not per-user).
    - Each order is evaluated independently with its own error handling.
    - Uses its own DB session (not FastAPI's dependency injection).
    """

    def __init__(self):
        self._running = False
        self._stats = {"sweeps": 0, "fills": 0, "expired": 0, "errors": 0}

    async def run(self) -> None:
        """Main loop — sweeps periodically for order expiry and clean up."""
        self._running = True
        logger.info("Order Execution Worker started")

        while self._running:
            try:
                await self._sweep_expiry()
                self._stats["sweeps"] += 1
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"Order Execution Worker error: {e}", exc_info=True)
                await asyncio.sleep(10)

        logger.info("Order Execution Worker stopped")

    async def on_price_event(self, event: Event) -> None:
        """Handle EventType.PRICE_UPDATED tick event for real-time immediate order execution."""
        if not event or not event.data:
            return

        symbol = event.data.get("symbol")
        quote = event.data.get("quote")
        if not symbol or not quote or "price" not in quote:
            return

        current_price = _to_decimal(quote["price"])
        if current_price is None or current_price <= 0:
            return

        await self.evaluate_orders_for_symbol(symbol, current_price, quote)

    async def evaluate_orders_for_symbol(self, symbol: str, current_price: Decimal, quote: dict) -> None:
        """Evaluate and execute open orders for a specific symbol against the new price."""
        async with async_session_factory() as db:
            try:
                result = await db.execute(
                    select(Order).where(
                        and_(
                            Order.symbol == symbol,
                            Order.status == "OPEN"
                        )
                    )
                )
                open_orders = result.scalars().all()
                if not open_orders:
                    return

                filled_events = []
                for order in open_orders:
                    try:
                        filled = await self._evaluate_order_with_price(db, order, current_price, quote)
                        if filled:
                            filled_events.append(
                                {
                                    "order_id": str(order.id),
                                    "user_id": str(order.user_id),
                                    "symbol": order.symbol,
                                    "side": order.side,
                                    "quantity": order.quantity,
                                    "filled_price": float(order.filled_price) if order.filled_price else None,
                                }
                            )
                    except Exception as e:
                        logger.error(f"Error evaluating order {order.id} for symbol {symbol}: {e}", exc_info=True)

                if filled_events:
                    await db.commit()
                    logger.info(f"[Tick Execution] Filled {len(filled_events)} orders for {symbol} at {current_price}")

                    # Emit events
                    for evt_data in filled_events:
                        await event_bus.emit(
                            Event(
                                type=EventType.ORDER_FILLED,
                                data=evt_data,
                                user_id=evt_data["user_id"],
                                source="order_execution_worker",
                            )
                        )
            except Exception as e:
                await db.rollback()
                logger.error(f"Order tick evaluation failed for {symbol}: {e}", exc_info=True)

    async def _sweep_expiry(self) -> None:
        """Periodically check and expire stale orders."""
        async with async_session_factory() as db:
            try:
                result = await db.execute(select(Order).where(Order.status == "OPEN"))
                open_orders = result.scalars().all()
                if not open_orders:
                    return

                expiry_cutoff = _utcnow() - timedelta(
                    days=ORDER_EXPIRY_DAYS
                )
                expired_events = []

                for order in open_orders:
                    created_at = _coerce_utc_datetime(order.created_at)
                    if created_at and created_at < expiry_cutoff:
                        reserved = _reserved_amount_for_open_buy_order(order)
                        if reserved > 0:
                            pf_result = await db.execute(
                                select(Portfolio).where(Portfolio.user_id == order.user_id)
                            )
                            pf = pf_result.scalar_one_or_none()
                            if pf:
                                current_avail = _to_decimal(pf.available_capital) or Decimal("0")
                                pf.available_capital = current_avail + reserved

                        order.status = "EXPIRED"
                        order.updated_at = _utcnow()
                        self._stats["expired"] += 1
                        expired_events.append(
                            {
                                "order_id": str(order.id),
                                "user_id": str(order.user_id),
                                "symbol": order.symbol,
                                "side": order.side,
                                "quantity": order.quantity,
                            }
                        )

                if expired_events:
                    await db.commit()
                    for evt_data in expired_events:
                        await event_bus.emit(
                            Event(
                                type=EventType.ORDER_EXPIRED,
                                data=evt_data,
                                user_id=evt_data["user_id"],
                                source="order_execution_worker",
                            )
                        )
            except Exception as e:
                await db.rollback()
                logger.error(f"Expiry sweep failed: {e}", exc_info=True)

    async def _evaluate_order(self, db: AsyncSession, order: Order) -> bool:
        """
        Evaluate a single order against current price.
        Returns True if the order was filled.
        """
        quote = await market_data.get_quote_safe(order.symbol, str(order.user_id))
        if not quote or "price" not in quote:
            return False

        current_price = _to_decimal(quote["price"])
        if current_price is None or current_price <= 0:
            return False

        return await self._evaluate_order_with_price(db, order, current_price, quote)

    async def _evaluate_order_with_price(
        self, db: AsyncSession, order: Order, current_price: Decimal, quote: dict
    ) -> bool:
        """
        Evaluate a single order against the provided live price and quote.
        Returns True if the order was filled.
        """
        order_price = _to_decimal(order.price)
        trigger_price = _to_decimal(order.trigger_price)
        should_fill = False
        fill_price = current_price  # default fill price

        if order.order_type in ("LIMIT", "BRACKET"):
            if order_price is None:
                return False
            # BUY limit fills when market falls to/below limit price.
            # SELL limit fills when market rises to/above limit price.
            if order.side == "BUY" and current_price <= order_price:
                should_fill = True
                fill_price = order_price  # fill at limit price, not current
            elif order.side == "SELL" and current_price >= order_price:
                should_fill = True
                fill_price = order_price

        elif order.order_type == "TAKE_PROFIT":
            if order_price is None:
                return False
            # BUY TP (close short): fills when market drops to/below target.
            # SELL TP (close long): fills when market rises to/above target.
            if order.side == "BUY" and current_price <= order_price:
                should_fill = True
                fill_price = order_price
            elif order.side == "SELL" and current_price >= order_price:
                should_fill = True
                fill_price = order_price

        elif order.order_type == "STOP_LOSS":
            trigger = trigger_price or order_price
            if trigger is None:
                return False
            if order.side == "BUY" and current_price >= trigger:
                should_fill = True
            elif order.side == "SELL" and current_price <= trigger:
                should_fill = True

        elif order.order_type == "STOP_LOSS_LIMIT":
            # Trigger fires first; after trigger, fill at limit price (order.price) if set
            trigger = trigger_price or order_price
            if trigger is None:
                return False
            trigger_hit = (order.side == "BUY" and current_price >= trigger) or (
                order.side == "SELL" and current_price <= trigger
            )
            if trigger_hit:
                if order_price is not None:
                    # For SL-M: after trigger, fill only if current price is at or
                    # better than the limit price
                    if order.side == "BUY" and current_price <= order_price:
                        should_fill = True
                        fill_price = current_price
                    elif order.side == "SELL" and current_price >= order_price:
                        should_fill = True
                        fill_price = current_price
                    elif order.side == "BUY" and current_price > order_price:
                        # Trigger hit but price above limit — fill at limit price
                        should_fill = True
                        fill_price = order_price
                    elif order.side == "SELL" and current_price < order_price:
                        # Trigger hit but price below limit — fill at limit price
                        should_fill = True
                        fill_price = order_price
                else:
                    # No limit price set — treat as regular STOP_LOSS (fill at market)
                    should_fill = True

        if should_fill:
            product_type = order.product_type or "CNC"

            # ── Fetch portfolio (needed for holdings check and portfolio update) ──
            # Lock Portfolio row
            portfolio_result = await db.execute(
                select(Portfolio).where(Portfolio.user_id == order.user_id).with_for_update()
            )
            portfolio = portfolio_result.scalar_one_or_none()

            # SL/TP orders are exit-only; never allow them to create new positions.
            if order.order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT", "TAKE_PROFIT"):
                if not portfolio:
                    order.status = "CANCELLED"
                    order.updated_at = _utcnow()
                    return False

                exit_holding_result = await db.execute(
                    select(Holding).where(
                        and_(
                            Holding.portfolio_id == portfolio.id,
                            Holding.symbol == order.symbol,
                            Holding.product_type == product_type,
                        )
                    ).with_for_update()
                )
                exit_holding = exit_holding_result.scalar_one_or_none()
                if not exit_holding:
                    order.status = "CANCELLED"
                    order.updated_at = _utcnow()
                    return False

                if order.side == "SELL":
                    if (
                        exit_holding.quantity <= 0
                        or exit_holding.quantity < order.quantity
                    ):
                        order.status = "CANCELLED"
                        order.updated_at = _utcnow()
                        return False
                else:
                    short_qty = (
                        abs(exit_holding.quantity) if exit_holding.quantity < 0 else 0
                    )
                    if short_qty < order.quantity:
                        order.status = "CANCELLED"
                        order.updated_at = _utcnow()
                        return False

            # ── For CNC SELL orders: verify the holding still exists ───
            # MIS/NRML short sells are allowed without holdings.
            if order.side == "SELL" and product_type == "CNC":
                if portfolio:
                    holding_result = await db.execute(
                        select(Holding).where(
                            and_(
                                Holding.portfolio_id == portfolio.id,
                                Holding.symbol == order.symbol,
                                Holding.product_type == product_type,
                            )
                        ).with_for_update()
                    )
                    holding = holding_result.scalar_one_or_none()
                    if not holding or holding.quantity < order.quantity:
                        available = holding.quantity if holding else 0
                        logger.warning(
                            f"Order {order.id} SELL {order.quantity}x {order.symbol} — "
                            f"holding only has {available}. Cancelling."
                        )
                        order.status = "CANCELLED"
                        order.updated_at = _utcnow()
                        return False

            order.status = "FILLED"
            order.filled_quantity = order.quantity
            order.filled_price = fill_price
            order.executed_at = _utcnow()
            order.updated_at = _utcnow()

            # This order's BUY LIMIT/BRACKET cash was reserved at placement.
            # Release it first; portfolio update will apply the actual fill debit.
            reserved = _reserved_amount_for_open_buy_order(order)
            if reserved > 0 and portfolio:
                current_avail = _to_decimal(portfolio.available_capital) or Decimal("0")
                portfolio.available_capital = current_avail + reserved

            # ── OCO: cancel sibling bracket leg when one fires ────────────────
            if order.tag and (
                order.tag.startswith("BRK_SL_") or order.tag.startswith("BRK_TP_")
            ):
                bracket_ref = order.tag[
                    7:
                ]  # strip "BRK_SL_" or "BRK_TP_" prefix (both 7 chars)
                sibling_prefix = (
                    "BRK_TP_" if order.tag.startswith("BRK_SL_") else "BRK_SL_"
                )
                sibling_tag = f"{sibling_prefix}{bracket_ref}"
                try:
                    sib_result = await db.execute(
                        select(Order).where(
                            and_(
                                Order.user_id == order.user_id,
                                Order.tag == sibling_tag,
                                Order.status == "OPEN",
                            )
                        )
                    )
                    sibling = sib_result.scalar_one_or_none()
                    if sibling:
                        sibling.status = "CANCELLED"
                        sibling.updated_at = _utcnow()
                        logger.info(
                            f"OCO: cancelled sibling order {sibling.id} (tag={sibling_tag}) "
                            f"because {order.tag} filled."
                        )
                except Exception as e:
                    logger.error(
                        f"OCO sibling cancellation failed for tag={sibling_tag}: {e}"
                    )

            if order.order_type == "BRACKET":
                await _create_bracket_child_orders(db, order, str(order.user_id))

            # ── Update portfolio holdings ──────────────────────────────────────
            # This is the critical step: mark holdings and capital changes so that
            # positions appear in the terminal after a limit/stop order fills.
            if portfolio:
                try:
                    company_name = quote.get("name", order.symbol) if quote else order.symbol
                    await _update_portfolio_on_fill(
                        db=db,
                        portfolio=portfolio,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=order.quantity,
                        price=fill_price,
                        order_id=order.id,
                        user_id=str(order.user_id),
                        company_name=company_name,
                        product_type=product_type,
                    )
                except Exception as e:
                    logger.error(
                        f"Portfolio update failed after filling order {order.id}: {e}",
                        exc_info=True,
                    )
            else:
                logger.warning(
                    f"No portfolio found for user {order.user_id}; "
                    f"order {order.id} filled but holdings NOT updated"
                )

            logger.info(
                f"Order FILLED: {order.id} | {order.side} {order.quantity}x "
                f"{order.symbol} @ ₹{float(fill_price):.2f} "
                f"(type={order.order_type} limit=₹{float(order_price) if order_price is not None else 0:.2f})"
            )
            return True

        return False

    async def stop(self) -> None:
        self._running = False

    def get_stats(self) -> dict:
        return self._stats.copy()


# ── Singleton ──────────────────────────────────────────────────────
order_execution_worker = OrderExecutionWorker()
