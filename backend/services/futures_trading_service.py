"""
Futures Trading Service — Simulated futures order placement and execution.
All orders stored in local DB only. NEVER sends orders to broker.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from models.futures_order import FuturesOrder, FuturesPosition
from models.portfolio import Portfolio
from models.user import User
from engines.market_session import market_session
from services import futures_service
from core.event_bus import event_bus, Event, EventType
from cache.smart_cache import portfolio_cache
import logging

logger = logging.getLogger(__name__)


def _to_decimal(value) -> Decimal:
    """Convert any value to Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _invalidate_futures_cache(user_id: str) -> None:
    """Clear cached portfolio data after a futures trade."""
    portfolio_cache.invalidate_prefix(f"summary:{user_id}")


async def place_futures_order(
    db: AsyncSession,
    user_id: str,
    contract_symbol: str,
    side: str,
    order_type: str,
    quantity: int,
    price: Optional[float] = None,
    trigger_price: Optional[float] = None,
    client_price: Optional[float] = None,
    tag: Optional[str] = None,
    bypass_market_session: bool = False,
) -> dict:
    """
    Place a simulated futures order (local DB only, never to broker).

    Returns:
        {
            "success": bool,
            "error": str (if not success),
            "order_id": UUID (if success),
            "status": str
        }
    """

    side = str(side or "").upper().strip()
    order_type = str(order_type or "MARKET").upper().strip()

    if not bypass_market_session and not market_session.can_place_orders():
        session_info = market_session.get_session_info()
        state = session_info["state"]
        state_label = {
            "weekend": "Weekend",
            "holiday": "Holiday",
            "closed": "Market Closed",
            "after_market": "After Market Hours",
        }.get(state, "Market Closed")
        return {
            "success": False,
            "error": (
                f"Cannot place futures orders - {state_label}. "
                "Trading is available Mon-Fri 9:15 AM - 3:30 PM IST."
            ),
        }

    if side not in ("BUY", "SELL"):
        return {"success": False, "error": "Side must be BUY or SELL"}

    if quantity <= 0:
        return {"success": False, "error": "Quantity must be positive"}

    async def _zebu_futures_ltp(symbol: str) -> Optional[Decimal]:
        """Live LTP from Zebu futures pipeline only (never equity quote cache)."""
        quote = await futures_service.get_quote(symbol)
        if not quote:
            return None
        raw = quote.get("ltp") or quote.get("price") or quote.get("lp")
        if raw is None:
            return None
        try:
            val = float(raw)
            return _to_decimal(val) if val > 0 else None
        except (TypeError, ValueError):
            return None

    # LIMIT / STOP: always use fresh Zebu futures quote (ignore stale UI client_price).
    if order_type == "LIMIT" or order_type == "STOP_LOSS_LIMIT":
        current_price = await _zebu_futures_ltp(contract_symbol)
        if current_price is None:
            return {
                "success": False,
                "error": "Unable to fetch Zebu market price for this contract",
            }
        client_price = None
    else:
        current_price = await _zebu_futures_ltp(contract_symbol)
        if current_price is None:
            if client_price and client_price > 0:
                logger.info(
                    f"Using client-provided Zebu tick {client_price} for {contract_symbol}"
                )
                current_price = _to_decimal(client_price)
            else:
                return {
                    "success": False,
                    "error": "Unable to fetch Zebu market price for this contract",
                }

    # Get portfolio
    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return {"success": False, "error": "Portfolio not found"}

    if portfolio.available_capital is None:
        portfolio.available_capital = Decimal("0")

    # Determine execution price
    if order_type == "MARKET":
        execution_price = current_price
    elif order_type == "LIMIT":
        if price is None:
            return {"success": False, "error": "Limit price required for LIMIT orders"}
        execution_price = _to_decimal(price)
    elif order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
        if trigger_price is None:
            return {
                "success": False,
                "error": "Trigger price required for stop-loss orders",
            }
        execution_price = _to_decimal(price) if price else current_price
    else:
        return {"success": False, "error": f"Invalid order type: {order_type}"}

    # Calculate margin using SPAN-like engine (index ~12%, stock ~20-30%)
    from workers.futures_margin_engine import calculate_margin_required

    margin_calc = calculate_margin_required(contract_symbol, execution_price, quantity)
    margin_required = margin_calc["total_margin"]

    # Capital check
    available_capital = _to_decimal(portfolio.available_capital or 0)
    if margin_required > available_capital:
        return {
            "success": False,
            "error": f"Insufficient margin. Required: ₹{margin_required:,.2f}, Available: ₹{available_capital:,.2f}",
        }

    # Create order
    order = FuturesOrder(
        user_id=user_id,
        contract_symbol=contract_symbol,
        order_type=order_type,
        side=side,
        quantity=quantity,
        price=price,
        trigger_price=trigger_price,
        tag=tag,
    )
    db.add(order)

    # Execute MARKET orders immediately
    if order_type == "MARKET":
        order.status = "FILLED"
        order.filled_quantity = quantity
        order.filled_price = execution_price
        order.executed_at = datetime.now(timezone.utc)

        # Update position
        await _update_futures_position_on_fill(
            db,
            user_id,
            contract_symbol,
            side,
            quantity,
            execution_price,
            portfolio,
        )

        await db.commit()

        # Emit event (emit_nowait — emit() expects a single Event argument)
        event_bus.emit_nowait(
            Event(
                type=EventType.FUTURES_ORDER_FILLED,
                user_id=str(user_id),
                data={
                    "order_id": str(order.id),
                    "contract_symbol": contract_symbol,
                    "side": side,
                    "quantity": quantity,
                    "filled_price": float(execution_price),
                    "status": "FILLED",
                },
            ),
        )

        _invalidate_futures_cache(user_id)

        return {
            "success": True,
            "order_id": str(order.id),
            "status": "FILLED",
            "filled_price": float(execution_price),
        }

    else:
        # LIMIT / STOP_LOSS orders stay OPEN for evaluation
        order.status = "OPEN"
        await db.commit()

        event_bus.emit_nowait(
            Event(
                type=EventType.FUTURES_ORDER_PLACED,
                user_id=str(user_id),
                data={
                    "order_id": str(order.id),
                    "contract_symbol": contract_symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": float(execution_price) if price else None,
                    "trigger_price": float(trigger_price) if trigger_price else None,
                    "status": "OPEN",
                },
            ),
        )

        return {
            "success": True,
            "order_id": str(order.id),
            "status": "OPEN",
        }


async def _update_futures_position_on_fill(
    db: AsyncSession,
    user_id: str,
    contract_symbol: str,
    side: str,
    quantity: int,
    filled_price: Decimal,
    portfolio: Portfolio,
) -> None:
    """Update position and margin after order fill."""

    # Get or create position
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
        # New position
        position = FuturesPosition(
            user_id=user_id,
            contract_symbol=contract_symbol,
            quantity=quantity if side == "BUY" else -quantity,
            avg_entry_price=filled_price,
            current_price=filled_price,
            unrealized_pnl=Decimal("0"),
        )
        db.add(position)
        portfolio.available_capital -= margin_requirement
    else:
        old_qty = position.quantity
        new_qty = old_qty + (quantity if side == "BUY" else -quantity)

        if new_qty == 0:
            # Position fully closed — realize PnL correctly for both LONG and SHORT
            # LONG close (was positive qty, selling): PnL = (exit - entry) * qty
            # SHORT close (was negative qty, buying): PnL = (entry - exit) * |qty|
            if old_qty > 0:
                pnl = (filled_price - position.avg_entry_price) * abs(old_qty)
            else:
                pnl = (position.avg_entry_price - filled_price) * abs(old_qty)
            position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl
            position.quantity = 0
            portfolio.available_capital += margin_requirement
        else:
            if (old_qty > 0 and side == "BUY") or (old_qty < 0 and side == "SELL"):
                # Adding to existing direction — weighted average entry
                new_avg_price = (
                    abs(old_qty) * position.avg_entry_price + quantity * filled_price
                ) / abs(new_qty)
                position.avg_entry_price = new_avg_price
                portfolio.available_capital -= margin_requirement
            else:
                # Partial close — realize PnL on the closed portion
                if old_qty > 0:
                    # Was LONG, partially selling
                    pnl = (filled_price - position.avg_entry_price) * quantity
                else:
                    # Was SHORT, partially buying
                    pnl = (position.avg_entry_price - filled_price) * quantity
                position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl
                portfolio.available_capital += margin_requirement

            position.quantity = new_qty

        position.current_price = filled_price
        position.updated_at = datetime.now(timezone.utc)

    await db.commit()


async def cancel_futures_order(db: AsyncSession, user_id: str, order_id: str) -> dict:
    """Cancel an open futures order."""

    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        return {"success": False, "error": "Invalid order ID"}

    result = await db.execute(
        select(FuturesOrder).where(
            and_(
                FuturesOrder.id == order_uuid,
                FuturesOrder.user_id == user_id,
            )
        )
    )
    order = result.scalar_one_or_none()

    if not order:
        return {"success": False, "error": "Order not found"}

    if order.status not in ("PENDING", "OPEN"):
        return {
            "success": False,
            "error": f"Cannot cancel order with status {order.status}",
        }

    order.status = "CANCELLED"
    order.updated_at = datetime.now(timezone.utc)
    await db.commit()

    event_bus.emit_nowait(
        Event(
            type=EventType.FUTURES_ORDER_CANCELLED,
            user_id=str(user_id),
            data={"order_id": str(order.id), "contract_symbol": order.contract_symbol},
        ),
    )

    _invalidate_futures_cache(user_id)

    return {"success": True, "order_id": str(order.id)}


async def get_futures_positions(db: AsyncSession, user_id: str) -> list:
    """Get all open positions for a user."""
    result = await db.execute(
        select(FuturesPosition).where(
            and_(
                FuturesPosition.user_id == user_id,
                FuturesPosition.quantity != 0,  # Only open positions
            )
        )
    )
    positions = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "contract_symbol": p.contract_symbol,
            "quantity": p.quantity,
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "unrealized_pnl": float(p.unrealized_pnl),
            "realized_pnl": float(p.realized_pnl),
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in positions
    ]


async def close_all_futures_positions(db: AsyncSession, user_id: str) -> dict:
    """Kill switch — cancel open futures orders and close every open position."""
    user_id_str = str(user_id)

    # Cancel open/pending futures orders
    open_orders_result = await db.execute(
        select(FuturesOrder).where(
            and_(
                FuturesOrder.user_id == user_id,
                FuturesOrder.status.in_(("OPEN", "PENDING")),
            )
        )
    )
    open_orders = open_orders_result.scalars().all()
    cancelled = 0
    for ord_ in open_orders:
        ord_.status = "CANCELLED"
        ord_.updated_at = datetime.now(timezone.utc)
        cancelled += 1

    positions_result = await db.execute(
        select(FuturesPosition).where(
            and_(
                FuturesPosition.user_id == user_id,
                FuturesPosition.quantity != 0,
            )
        )
    )
    positions = positions_result.scalars().all()

    if not positions:
        await db.commit()
        _invalidate_futures_cache(user_id_str)
        return {
            "success": True,
            "closed": 0,
            "cancelled_orders": cancelled,
            "message": f"No open futures positions. Cancelled {cancelled} pending order(s).",
        }

    closed = 0
    errors = []

    for position in positions:
        qty = int(position.quantity or 0)
        if qty == 0:
            continue
        side = "SELL" if qty > 0 else "BUY"
        close_qty = abs(qty)
        contract_symbol = position.contract_symbol

        try:
            quote = await futures_service.get_quote(contract_symbol)
            ltp = None
            if quote:
                ltp = quote.get("ltp") or quote.get("price") or quote.get("lp")
            if not ltp:
                ltp = float(position.current_price or position.avg_entry_price or 0)
            if not ltp or ltp <= 0:
                errors.append(f"{contract_symbol}: no live price")
                continue

            result = await place_futures_order(
                db=db,
                user_id=user_id,
                contract_symbol=contract_symbol,
                side=side,
                order_type="MARKET",
                quantity=close_qty,
                client_price=float(ltp),
                tag="KILL_SWITCH",
                bypass_market_session=True,
            )
            if result.get("success"):
                closed += 1
            else:
                errors.append(f"{contract_symbol}: {result.get('error', 'close failed')}")
        except Exception as e:
            logger.error(f"[FuturesKillSwitch] {contract_symbol}: {e}", exc_info=True)
            errors.append(f"{contract_symbol}: {str(e)}")

    await db.commit()
    _invalidate_futures_cache(user_id_str)

    message = f"Closed {closed} futures position(s)"
    if cancelled:
        message += f", cancelled {cancelled} order(s)"
    if errors:
        message += f". Errors: {'; '.join(errors[:5])}"

    return {
        "success": closed > 0 or cancelled > 0,
        "closed": closed,
        "cancelled_orders": cancelled,
        "errors": errors,
        "message": message,
    }
