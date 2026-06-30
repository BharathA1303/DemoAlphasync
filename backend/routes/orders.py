from datetime import datetime, timezone
from decimal import Decimal
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel
from typing import Optional
from database.connection import get_db
from models.user import User
from models.order import Order
from models.portfolio import Portfolio, Holding
from routes.auth import get_current_user
from services.trading_engine import (
    place_order,
    cancel_order,
    check_pending_orders,
    close_net_holding,
    compute_realized_pnl_by_order_id,
    _to_decimal,
)
from services.portfolio_service import invalidate_user_portfolio_cache
from services import market_data
from engines.market_session import market_session
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["Orders"])

_EDITABLE_ORDER_STATUSES = {
    "OPEN",
    "PENDING",
    "TRIGGER_PENDING",
    "AMO_RECEIVED",
    "MODIFY_PENDING",
    "PARTIALLY_FILLED",
}


# Frontend → Backend order-type mapping
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "BRACKET": "BRACKET",
    "LIMIT + TP + SL": "BRACKET",
    "STOP_LOSS": "STOP_LOSS",
    "STOP LOSS": "STOP_LOSS",
    "SL": "STOP_LOSS",
    "STOP_LOSS_LIMIT": "STOP_LOSS_LIMIT",
    "STOP LOSS LIMIT": "STOP_LOSS_LIMIT",
    "SL-M": "STOP_LOSS_LIMIT",
    "TAKE_PROFIT": "TAKE_PROFIT",
    "TAKE PROFIT": "TAKE_PROFIT",
    "TP": "TAKE_PROFIT",
}


def _normalize_order_type(value: str) -> str:
    normalized = str(value or "MARKET").strip().upper().replace("-", "_")
    normalized = " ".join(normalized.split())
    return _ORDER_TYPE_MAP.get(normalized, normalized)


def _parse_uuid_or_400(value, field_name: str) -> uuid.UUID:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    order_type: str = (
        "MARKET"  # MARKET, LIMIT, STOP_LOSS, TAKE_PROFIT, BRACKET, SL, SL-M
    )
    product_type: str = "CNC"  # CNC (delivery), MIS (intraday), NRML (F&O)
    quantity: int
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    client_price: Optional[float] = None  # Fallback price from chart for simulation
    idempotency_key: Optional[str] = None


class ModifyOrderRequest(BaseModel):
    quantity: Optional[int] = None
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    take_profit_price: Optional[float] = None


@router.post("")
async def create_order(
    req: PlaceOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    req.product_type = str(req.product_type or "CNC").upper().strip()
    req.side = str(req.side or "").upper().strip()

    if req.side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Side must be BUY or SELL")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if req.product_type not in ("CNC", "MIS", "NRML"):
        raise HTTPException(
            status_code=400, detail="Product type must be CNC, MIS, or NRML"
        )

    # Enforce market hours — all trades are simulated but only during market open
    if not market_session.can_place_orders():
        session_info = market_session.get_session_info()
        state = session_info["state"]
        state_label = {
            "weekend": "Weekend",
            "holiday": "Holiday",
            "closed": "Market Closed",
            "after_market": "After Market Hours",
        }.get(state, "Market Closed")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot place orders — {state_label}. Trading is available Mon–Fri 9:15 AM – 3:30 PM IST.",
        )

    # Normalize frontend order type aliases to backend canonical values
    order_type = _normalize_order_type(req.order_type)

    if order_type in ("LIMIT", "BRACKET", "TAKE_PROFIT") and (
        req.price is None or req.price <= 0
    ):
        raise HTTPException(status_code=400, detail="Price must be greater than 0")

    if order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT", "BRACKET") and (
        req.trigger_price is None or req.trigger_price <= 0
    ):
        raise HTTPException(
            status_code=400, detail="Trigger price must be greater than 0"
        )

    if order_type == "BRACKET" and (
        req.take_profit_price is None or req.take_profit_price <= 0
    ):
        raise HTTPException(
            status_code=400, detail="Take-profit price must be greater than 0"
        )

    # BRACKET price logic validation is handled inside trading_engine.place_order()
    # to avoid double-rejection. The engine uses Decimal arithmetic for precision.

    price = req.price
    trigger_price = req.trigger_price
    take_profit_price = req.take_profit_price

    if order_type == "TAKE_PROFIT" and price is None and take_profit_price is not None:
        price = take_profit_price
    if (
        order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT")
        and trigger_price is None
        and price is not None
    ):
        trigger_price = price

    try:
        result = await place_order(
            db=db,
            user_id=user.id,
            symbol=req.symbol,
            side=req.side,
            order_type=order_type,
            product_type=req.product_type,
            quantity=req.quantity,
            price=price,
            trigger_price=trigger_price,
            take_profit_price=take_profit_price,
            client_price=req.client_price,
            idempotency_key=req.idempotency_key,
        )
    except Exception as e:
        logger.exception("Order placement crashed")
        raise HTTPException(status_code=400, detail=f"Order failed: {e}")

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.get("")
async def get_orders(
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Safety net: evaluate OPEN orders against latest quotes before returning list.
    # This prevents crossed LIMIT/SL/TP orders from appearing stale if worker lagged.
    try:
        await check_pending_orders(db, user.id)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"Pending order check failed during get_orders: {e}")

    # Clamp limit to prevent excessively large queries
    limit = max(1, min(limit, 500))

    query = select(Order).where(Order.user_id == user.id)
    if status_filter:
        query = query.where(Order.status == status_filter)
    query = query.order_by(Order.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    orders = result.scalars().all()
    pnl_by_order_id = compute_realized_pnl_by_order_id(orders)

    return {
        "orders": [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "exchange": o.exchange,
                "order_type": o.order_type,
                "side": o.side,
                "product_type": o.product_type,
                "quantity": o.quantity,
                "price": float(o.price) if o.price is not None else None,
                "trigger_price": (
                    float(o.trigger_price) if o.trigger_price is not None else None
                ),
                "take_profit_price": (
                    float(o.take_profit_price)
                    if getattr(o, "take_profit_price", None) is not None
                    else None
                ),
                "filled_quantity": o.filled_quantity,
                "filled_price": (
                    float(o.filled_price) if o.filled_price is not None else None
                ),
                "pnl": pnl_by_order_id.get(str(o.id)),
                "realized_pnl": pnl_by_order_id.get(str(o.id)),
                "status": o.status,
                "tag": o.tag,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "updated_at": o.updated_at.isoformat() if o.updated_at else None,
                "executed_at": o.executed_at.isoformat() if o.executed_at else None,
            }
            for o in orders
        ],
        "pagination": {"limit": limit, "offset": offset, "count": len(orders)},
    }


@router.get("/{order_id}")
async def get_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order_uuid = _parse_uuid_or_400(order_id, "order_id")
    result = await db.execute(
        select(Order).where(Order.id == order_uuid, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": str(order.id),
        "symbol": order.symbol,
        "exchange": order.exchange,
        "order_type": order.order_type,
        "side": order.side,
        "product_type": order.product_type,
        "quantity": order.quantity,
        "price": float(order.price) if order.price is not None else None,
        "trigger_price": (
            float(order.trigger_price) if order.trigger_price is not None else None
        ),
        "take_profit_price": (
            float(order.take_profit_price)
            if getattr(order, "take_profit_price", None) is not None
            else None
        ),
        "filled_quantity": order.filled_quantity,
        "filled_price": (
            float(order.filled_price) if order.filled_price is not None else None
        ),
        "status": order.status,
        "tag": order.tag,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "executed_at": order.executed_at.isoformat() if order.executed_at else None,
    }


@router.patch("/{order_id}")
async def modify_order(
    order_id: str,
    req: ModifyOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order_uuid = _parse_uuid_or_400(order_id, "order_id")
    try:
        result = await db.execute(
            select(Order).where(and_(Order.id == order_uuid, Order.user_id == user.id))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        status_norm = str(order.status or "").upper().strip()
        if status_norm not in _EDITABLE_ORDER_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Only open/pending orders can be modified. Current status: {order.status}",
            )

        updates_applied = False
        order_type = str(order.order_type or "").upper().strip()

        if req.quantity is not None:
            if req.quantity <= 0:
                raise HTTPException(status_code=400, detail="Quantity must be positive")
            if order.filled_quantity and req.quantity < int(order.filled_quantity):
                raise HTTPException(
                    status_code=400,
                    detail=f"Quantity cannot be less than already filled quantity ({order.filled_quantity})",
                )
            order.quantity = req.quantity
            updates_applied = True

        if req.price is not None:
            if req.price <= 0:
                raise HTTPException(status_code=400, detail="Price must be greater than 0")
            if order_type == "MARKET":
                raise HTTPException(
                    status_code=400,
                    detail="Market orders cannot be modified with a limit/target price",
                )
            order.price = req.price
            updates_applied = True

        if req.trigger_price is not None:
            if req.trigger_price <= 0:
                raise HTTPException(
                    status_code=400, detail="Trigger price must be greater than 0"
                )
            if order_type not in ("STOP_LOSS", "STOP_LOSS_LIMIT", "BRACKET"):
                raise HTTPException(
                    status_code=400,
                    detail="Trigger price can be modified only for stop-loss/bracket orders",
                )
            order.trigger_price = req.trigger_price
            updates_applied = True

        if req.take_profit_price is not None:
            if req.take_profit_price <= 0:
                raise HTTPException(
                    status_code=400, detail="Take-profit price must be greater than 0"
                )
            if order_type not in ("TAKE_PROFIT", "BRACKET"):
                raise HTTPException(
                    status_code=400,
                    detail="Take-profit price can be modified only for TP/bracket orders",
                )
            order.take_profit_price = req.take_profit_price
            updates_applied = True

        if order_type == "BRACKET":
            entry = _to_decimal(order.price or 0)
            sl = _to_decimal(order.trigger_price or 0)
            tp = _to_decimal(order.take_profit_price or 0)
            if entry <= 0 or sl <= 0 or tp <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Bracket order must have valid entry, stop-loss and take-profit prices",
                )
            if order.side == "BUY" and not (tp > entry > sl):
                raise HTTPException(
                    status_code=400,
                    detail="BUY bracket requires: take-profit > entry > stop-loss",
                )
            if order.side == "SELL" and not (sl > entry > tp):
                raise HTTPException(
                    status_code=400,
                    detail="SELL bracket requires: stop-loss > entry > take-profit",
                )

        if order_type in ("LIMIT", "TAKE_PROFIT") and order.price is None:
            raise HTTPException(
                status_code=400, detail="Price is required for this order type"
            )
        if (
            order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT", "BRACKET")
            and order.trigger_price is None
        ):
            raise HTTPException(
                status_code=400, detail="Trigger price is required for this order type"
            )

        if not updates_applied:
            raise HTTPException(
                status_code=400, detail="No valid fields provided to modify"
            )

        order.updated_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "success": True,
            "order": {
                "id": str(order.id),
                "symbol": order.symbol,
                "exchange": order.exchange,
                "order_type": order.order_type,
                "side": order.side,
                "product_type": order.product_type,
                "quantity": order.quantity,
                "price": float(order.price) if order.price is not None else None,
                "trigger_price": (
                    float(order.trigger_price) if order.trigger_price is not None else None
                ),
                "take_profit_price": (
                    float(order.take_profit_price)
                    if getattr(order, "take_profit_price", None) is not None
                    else None
                ),
                "filled_quantity": order.filled_quantity,
                "filled_price": (
                    float(order.filled_price) if order.filled_price is not None else None
                ),
                "status": order.status,
                "tag": order.tag,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None,
                "executed_at": order.executed_at.isoformat() if order.executed_at else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("Order modification failed")
        raise HTTPException(status_code=400, detail=f"Modify order failed: {e}")


@router.delete("/{order_id}")
async def delete_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order_uuid = _parse_uuid_or_400(order_id, "order_id")
    try:
        result = await cancel_order(db, user.id, order_uuid)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("Order cancellation failed")
        raise HTTPException(status_code=400, detail=f"Cancel order failed: {e}")


@router.post("/close-all")
async def close_all_positions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kill Switch — cancel open orders and close every position via MARKET fills.

    Exit orders are written to the orders table so the Orders page can compute P&L.
    """
    user_id = user.id
    user_id_str = str(user.id)

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return {"success": True, "closed": 0, "message": "No portfolio found"}

    # ── 1. Cancel all OPEN orders ─────────────────────────────────────────────
    cancellable_statuses = [
        "OPEN",
        "PENDING",
        "PARTIALLY_FILLED",
        "TRIGGER_PENDING",
        "AMO_RECEIVED",
        "MODIFY_PENDING",
    ]
    open_orders_result = await db.execute(
        select(Order).where(
            and_(Order.user_id == user_id, Order.status.in_(cancellable_statuses))
        )
    )
    open_orders = open_orders_result.scalars().all()
    cancelled = 0
    for ord_ in open_orders:
        try:
            cancel_result = await cancel_order(db, user_id, ord_.id)
            if cancel_result.get("success"):
                cancelled += 1
            else:
                ord_.status = "CANCELLED"
                ord_.updated_at = datetime.now(timezone.utc)
                cancelled += 1
        except Exception as e:
            logger.warning(f"[KillSwitch] Could not cancel order {ord_.id}: {e}")

    # ── 2. Close holdings via MARKET exit orders (FIFO lots) ─────────────────
    holdings_result = await db.execute(
        select(Holding).where(
            and_(Holding.portfolio_id == portfolio.id, Holding.quantity != 0)
        )
    )
    holdings = holdings_result.scalars().all()

    if not holdings:
        await db.commit()
        invalidate_user_portfolio_cache(user_id_str)
        _sync_zeroloss_after_kill_switch(user_id)
        return {
            "success": True,
            "closed": 0,
            "cancelled_orders": cancelled,
            "message": f"No open positions. Cancelled {cancelled} pending order(s).",
        }

    closed = 0
    errors = []

    for holding in holdings:
        try:
            quote = await market_data.get_quote_safe(holding.symbol, user_id_str)
            close_price = (
                float(quote["price"])
                if quote and quote.get("price")
                else float(holding.current_price or holding.avg_price or 0)
            )

            close_result = await close_net_holding(
                db,
                user_id,
                holding,
                tag="KILL_SWITCH",
                client_price=close_price,
                bypass_market_session=True,
            )
            if close_result.get("success"):
                closed += 1
            else:
                errors.append(
                    f"{holding.symbol}: {close_result.get('error', 'unknown error')}"
                )
        except Exception as e:
            errors.append(f"{holding.symbol}: {str(e)}")
            logger.error(
                f"[KillSwitch] Error closing {holding.symbol}: {e}", exc_info=True
            )

    await db.commit()
    invalidate_user_portfolio_cache(user_id_str)
    _sync_zeroloss_after_kill_switch(user_id)

    return {
        "success": True,
        "closed": closed,
        "total": len(holdings),
        "cancelled_orders": cancelled,
        "errors": errors if errors else None,
        "message": f"Closed {closed}/{len(holdings)} positions, cancelled {cancelled} pending order(s)",
    }


def _sync_zeroloss_after_kill_switch(user_id) -> None:
    """Clear in-memory Alpha Auto positions after an external kill switch."""
    try:
        from strategies.zeroloss.manager import zeroloss_manager

        controller = zeroloss_manager.get_controller(user_id)
        controller.clear_active_positions()
    except Exception as e:
        logger.debug(f"[KillSwitch] ZeroLoss sync skipped: {e}")
