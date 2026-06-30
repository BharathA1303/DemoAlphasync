import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from models.order import Order
from models.portfolio import Portfolio, Holding, Transaction
from models.user import User
from services import market_data
from providers.symbol_mapper import is_mcx_symbol
from core.event_bus import event_bus, Event, EventType
from engines.risk_engine import risk_engine
from cache.smart_cache import portfolio_cache, holdings_cache
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

_ORDER_TYPE_ALIASES = {
    "SL": "STOP_LOSS",
    "SL-M": "STOP_LOSS_LIMIT",
    "STOP LOSS": "STOP_LOSS",
    "STOP LOSS LIMIT": "STOP_LOSS_LIMIT",
    "TAKE PROFIT": "TAKE_PROFIT",
    "TP": "TAKE_PROFIT",
    "LIMIT + TP + SL": "BRACKET",
}

_HOLDING_UPDATE_LOCKS: dict[str, asyncio.Lock] = {}


def _get_holding_update_lock(portfolio_id, symbol: str) -> asyncio.Lock:
    key = f"{portfolio_id}:{str(symbol or '').upper()}"
    lock = _HOLDING_UPDATE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _HOLDING_UPDATE_LOCKS[key] = lock
    return lock


def _normalize_order_type(value: str) -> str:
    normalized = str(value or "MARKET").strip().upper()
    normalized = " ".join(normalized.split())
    return _ORDER_TYPE_ALIASES.get(normalized, normalized.replace("-", "_"))


def _invalidate_portfolio_cache(user_id: str) -> None:
    """Clear cached portfolio data after a trade so the next fetch is fresh."""
    portfolio_cache.invalidate_prefix(f"summary:{user_id}")
    holdings_cache.invalidate_prefix(f"holdings:{user_id}")


def _normalize_available_capital(
    available_capital: Decimal, net_equity: Decimal, holdings_count: int
) -> Decimal:
    if holdings_count <= 0:
        return net_equity
    if available_capital > net_equity:
        return net_equity
    return available_capital


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _is_position_reducing(side: str, held_qty: int) -> bool:
    """True when the order closes/reduces an existing open position."""
    if held_qty > 0 and side == "SELL":
        return True
    if held_qty < 0 and side == "BUY":
        return True
    return False


def compute_realized_pnl_by_order_id(orders: list[Order]) -> dict[str, float]:
    """FIFO realized P&L per filled order (for orders API / UI)."""
    books: dict[str, dict] = {}
    pnl_by_id: dict[str, float] = {}

    sorted_orders = sorted(
        orders,
        key=lambda o: (
            o.executed_at or o.created_at or datetime.min.replace(tzinfo=timezone.utc),
            str(o.id),
        ),
    )

    for order in sorted_orders:
        if str(order.status or "").upper() != "FILLED":
            continue

        qty = int(order.filled_quantity or order.quantity or 0)
        if qty <= 0:
            continue

        try:
            price = float(order.filled_price or order.price or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue

        symbol = str(order.symbol or "").upper()
        side = str(order.side or "").upper()
        if not symbol or side not in ("BUY", "SELL"):
            continue

        book = books.setdefault(symbol, {"longs": [], "shorts": []})
        remaining = qty
        realized = 0.0
        matched_qty = 0

        if side == "BUY":
            while remaining > 0 and book["shorts"]:
                lot = book["shorts"][0]
                close_qty = min(remaining, lot["qty"])
                realized += (lot["price"] - price) * close_qty
                matched_qty += close_qty
                lot["qty"] -= close_qty
                remaining -= close_qty
                if lot["qty"] <= 0:
                    book["shorts"].pop(0)
            if remaining > 0:
                book["longs"].append({"qty": remaining, "price": price})
        else:
            while remaining > 0 and book["longs"]:
                lot = book["longs"][0]
                close_qty = min(remaining, lot["qty"])
                realized += (price - lot["price"]) * close_qty
                matched_qty += close_qty
                lot["qty"] -= close_qty
                remaining -= close_qty
                if lot["qty"] <= 0:
                    book["longs"].pop(0)
            if remaining > 0:
                book["shorts"].append({"qty": remaining, "price": price})

        if matched_qty > 0:
            pnl_by_id[str(order.id)] = round(realized, 2)

    return pnl_by_id


async def close_net_holding(
    db: AsyncSession,
    user_id,
    holding: Holding,
    *,
    tag: str,
    client_price: Optional[float] = None,
    bypass_market_session: bool = True,
) -> dict:
    """Close the net holding quantity with one MARKET order (kill switch / strategy stop)."""
    held_qty = int(holding.quantity or 0)
    if held_qty == 0:
        return {"success": True, "message": "No open quantity"}

    side = "SELL" if held_qty > 0 else "BUY"
    qty = abs(held_qty)

    product_type = str(holding.product_type or "CNC").upper()

    return await place_order(
        db=db,
        user_id=user_id,
        symbol=holding.symbol,
        side=side,
        order_type="MARKET",
        quantity=qty,
        product_type=product_type,
        tag=tag,
        client_price=client_price,
        bypass_market_session=bypass_market_session,
    )


async def close_zeroloss_holdings(db: AsyncSession, user_id) -> list[dict]:
    """Close portfolio holdings that still have open qty from Alpha Auto (ZEROLOSS) fills."""
    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return []

    symbols_result = await db.execute(
        select(Order.symbol)
        .where(
            Order.user_id == user_id,
            Order.tag == "ZEROLOSS",
            Order.status == "FILLED",
        )
        .distinct()
    )
    symbols = [str(s) for s in symbols_result.scalars().all() if s]
    if not symbols:
        return []

    holdings_result = await db.execute(
        select(Holding).where(
            and_(
                Holding.portfolio_id == portfolio.id,
                Holding.symbol.in_(symbols),
                Holding.quantity != 0,
            )
        )
    )
    holdings = holdings_result.scalars().all()
    results: list[dict] = []

    for holding in holdings:
        try:
            quote = await market_data.get_quote_safe(holding.symbol, str(user_id))
            close_price = (
                float(quote["price"])
                if quote and quote.get("price")
                else float(holding.current_price or holding.avg_price or 0)
            )
            close_result = await close_net_holding(
                db,
                user_id,
                holding,
                tag="ZEROLOSS",
                client_price=close_price,
                bypass_market_session=True,
            )
            results.append(
                {
                    "symbol": holding.symbol,
                    "success": bool(close_result.get("success")),
                    "error": close_result.get("error"),
                }
            )
        except Exception as e:
            logger.error(
                "[ZeroLoss] Failed closing holding %s: %s",
                holding.symbol,
                e,
                exc_info=True,
            )
            results.append(
                {"symbol": holding.symbol, "success": False, "error": str(e)}
            )

    return results


async def resolve_open_lots_from_orders(
    db: AsyncSession, user_id, symbol: str
) -> list[dict]:
    """FIFO open lots for a symbol with product type (MIS/CNC/NRML)."""
    formatted_symbol = market_data._format_symbol(symbol)
    result = await db.execute(
        select(Order)
        .where(
            and_(
                Order.user_id == user_id,
                Order.symbol == formatted_symbol,
                Order.status == "FILLED",
            )
        )
        .order_by(Order.executed_at.asc().nulls_last(), Order.created_at.asc())
    )
    orders = result.scalars().all()

    long_lots: list[list] = []
    short_lots: list[list] = []

    for order in orders:
        qty = int(order.filled_quantity or order.quantity or 0)
        if qty <= 0:
            continue
        product_type = str(order.product_type or "CNC").upper().strip()

        if order.side == "BUY":
            remaining = qty
            while remaining > 0 and short_lots:
                lot_qty, _lot_pt = short_lots[0]
                close_qty = min(remaining, lot_qty)
                lot_qty -= close_qty
                remaining -= close_qty
                if lot_qty <= 0:
                    short_lots.pop(0)
                else:
                    short_lots[0][0] = lot_qty
            if remaining > 0:
                long_lots.append([remaining, product_type])
        else:
            remaining = qty
            while remaining > 0 and long_lots:
                lot_qty, _lot_pt = long_lots[0]
                close_qty = min(remaining, lot_qty)
                lot_qty -= close_qty
                remaining -= close_qty
                if lot_qty <= 0:
                    long_lots.pop(0)
                else:
                    long_lots[0][0] = lot_qty
            if remaining > 0:
                short_lots.append([remaining, product_type])

    open_lots: list[dict] = []
    for qty, product_type in long_lots:
        if qty > 0:
            open_lots.append(
                {"qty": qty, "product_type": product_type, "side": "LONG"}
            )
    for qty, product_type in short_lots:
        if qty > 0:
            open_lots.append(
                {"qty": qty, "product_type": product_type, "side": "SHORT"}
            )
    return open_lots


async def mark_holding_to_market(
    db: AsyncSession,
    holding: Holding,
    close_price: Decimal,
) -> None:
    """Update delivery (CNC) holding to the latest market price at EOD."""
    price = _to_decimal(close_price)
    qty = int(holding.quantity or 0)
    if qty == 0:
        return

    avg_price = _to_decimal(holding.avg_price or 0)
    holding.current_price = price
    holding.current_value = price * qty
    holding.invested_value = avg_price * qty
    holding.pnl = holding.current_value - holding.invested_value
    invested_abs = abs(holding.invested_value)
    holding.pnl_percent = (
        (holding.pnl / invested_abs * 100) if invested_abs else Decimal("0")
    )
    holding.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def close_open_lots(
    db: AsyncSession,
    user_id,
    symbol: str,
    lots: list[dict],
    *,
    tag: str,
    client_price: Optional[float] = None,
    bypass_market_session: bool = True,
) -> list[dict]:
    """Close explicit open lots via MARKET orders (creates FILLED exit orders)."""
    results: list[dict] = []
    for lot in lots:
        qty = int(lot.get("qty") or 0)
        if qty <= 0:
            continue
        side = "SELL" if lot.get("side") == "LONG" else "BUY"
        product_type = str(lot.get("product_type") or "CNC").upper().strip()
        result = await place_order(
            db=db,
            user_id=user_id,
            symbol=symbol,
            side=side,
            order_type="MARKET",
            quantity=qty,
            product_type=product_type,
            tag=tag,
            client_price=client_price,
            bypass_market_session=bypass_market_session,
        )
        results.append(result)
    return results


async def _upsert_holding(db: AsyncSession, portfolio: Portfolio, symbol: str, values: dict, product_type: str = "CNC") -> None:
    stmt = pg_insert(Holding).values(
        portfolio_id=portfolio.id,
        symbol=symbol,
        product_type=product_type,
        **values,
    )
    update_values = {k: stmt.excluded[k] for k in values.keys()}
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Holding.portfolio_id, Holding.symbol, Holding.product_type],
            set_=update_values,
        )
    )


async def place_order(
    db: AsyncSession,
    user_id: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: int,
    price: Optional[float] = None,
    trigger_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    client_price: Optional[float] = None,
    product_type: str = "CNC",
    tag: Optional[str] = None,
    bypass_market_session: bool = False,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Place and potentially execute a simulated order."""

    if idempotency_key:
        result = await db.execute(
            select(Order).where(
                and_(Order.user_id == user_id, Order.idempotency_key == idempotency_key)
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return {
                "success": True,
                "order_id": str(existing.id),
                "status": existing.status,
                "message": "Duplicate order detected; returning original order.",
            }

    order_type = _normalize_order_type(order_type)
    side = str(side or "").upper().strip()
    product_type = str(product_type or "CNC").upper().strip()
    symbol = market_data._format_symbol(symbol)

    if side not in ("BUY", "SELL"):
        return {"success": False, "error": "Side must be BUY or SELL"}
    if quantity <= 0:
        return {"success": False, "error": "Quantity must be positive"}

    if order_type == "LIMIT" or order_type == "BRACKET":
        # LIMIT/BRACKET MUST use fresh market data to avoid premature fills
        # from stale client_price (market may have moved since user opened panel)
        quote = await market_data.get_quote_safe(symbol, user_id)
        if not quote or not quote.get("price"):
            return {
                "success": False,
                "error": "Unable to fetch market price for this symbol",
            }
        client_price = None

    elif order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT", "TAKE_PROFIT"):
        # Exit orders always need fresh live price for trigger direction validation
        quote = await market_data.get_quote_safe(symbol, user_id)
        if not quote or not quote.get("price"):
            return {
                "success": False,
                "error": "Unable to fetch market price for this symbol",
            }
        # Override client_price with fresh data so route-level validation is accurate
        client_price = quote["price"]

    else:
        # MARKET orders: prefer client_price for speed, fall back to broker quote
        if client_price and client_price > 0:
            quote = {
                "price": client_price,
                "name": (
                    symbol.replace(".NS", "") if not is_mcx_symbol(symbol) else symbol
                ),
            }
        else:
            quote = await market_data.get_quote_safe(symbol, user_id)
            if not quote or not quote.get("price"):
                return {
                    "success": False,
                    "error": "Unable to fetch market price for this symbol",
                }

    current_price = _to_decimal(quote["price"])
    if current_price <= 0:
        return {"success": False, "error": "Invalid live market price"}

    # Get portfolio with row lock
    result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == user_id).with_for_update()
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return {"success": False, "error": "Portfolio not found"}

    # Ensure available_capital is not None before comparisons
    if portfolio.available_capital is None:
        portfolio.available_capital = Decimal("0")

    # Validate order
    if order_type == "MARKET":
        execution_price = current_price
    elif order_type == "LIMIT":
        if price is None:
            return {"success": False, "error": "Limit price required for LIMIT orders"}
        if _to_decimal(price) <= 0:
            return {"success": False, "error": "Limit price must be greater than 0"}
        execution_price = _to_decimal(price)
    elif order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
        if trigger_price is None:
            return {
                "success": False,
                "error": "Trigger price required for stop-loss orders",
            }
        if _to_decimal(trigger_price) <= 0:
            return {
                "success": False,
                "error": "Trigger price must be greater than 0",
            }
        if price is not None and _to_decimal(price) <= 0:
            return {
                "success": False,
                "error": "Limit price must be greater than 0",
            }
        execution_price = _to_decimal(price) if price else current_price
    elif order_type == "TAKE_PROFIT":
        if price is None:
            return {
                "success": False,
                "error": "Target price required for TAKE_PROFIT orders",
            }
        if _to_decimal(price) <= 0:
            return {
                "success": False,
                "error": "Target price must be greater than 0",
            }
        execution_price = _to_decimal(price)
    elif order_type == "BRACKET":
        if price is None:
            return {
                "success": False,
                "error": "Entry price required for BRACKET orders",
            }
        if trigger_price is None:
            return {
                "success": False,
                "error": "Stop-loss price required for BRACKET orders",
            }
        if take_profit_price is None:
            return {
                "success": False,
                "error": "Take-profit price required for BRACKET orders",
            }

        entry_price = _to_decimal(price)
        sl_price = _to_decimal(trigger_price)
        tp_price = _to_decimal(take_profit_price)
        if entry_price <= 0 or sl_price <= 0 or tp_price <= 0:
            return {
                "success": False,
                "error": "Entry, stop-loss, and take-profit prices must be greater than 0",
            }
        if side == "BUY" and not (tp_price > entry_price > sl_price):
            return {
                "success": False,
                "error": "BUY bracket requires: take-profit > entry > stop-loss",
            }
        if side == "SELL" and not (sl_price > entry_price > tp_price):
            return {
                "success": False,
                "error": "SELL bracket requires: stop-loss > entry > take-profit",
            }
        execution_price = _to_decimal(price)
    else:
        return {"success": False, "error": f"Invalid order type: {order_type}"}

    total_cost = execution_price * quantity

    result = await db.execute(
        select(Holding).where(
            and_(
                Holding.portfolio_id == portfolio.id,
                Holding.symbol == symbol,
                Holding.product_type == product_type,
            )
        ).with_for_update()
    )
    symbol_holding = result.scalar_one_or_none()
    held_qty = int(symbol_holding.quantity or 0) if symbol_holding else 0
    is_reducing = _is_position_reducing(side, held_qty)
    force_close_tag = str(tag or "").upper() in (
        "KILL_SWITCH",
        "SQUAREOFF",
        "ZEROLOSS",
        "ZEROLOSS_STOP",
    )
    is_exit_order = order_type in (
        "STOP_LOSS",
        "STOP_LOSS_LIMIT",
        "TAKE_PROFIT",
    ) or (is_reducing and (order_type == "MARKET" or force_close_tag))

    if is_exit_order:
        if not symbol_holding or symbol_holding.quantity == 0:
            return {
                "success": False,
                "error": "Stop-loss/Take-profit can only be placed for an open position",
            }

        held_qty = int(symbol_holding.quantity or 0)
        if side == "SELL":
            if held_qty <= 0:
                return {
                    "success": False,
                    "error": "SELL exit orders require an open LONG position",
                }
            if quantity > held_qty:
                return {
                    "success": False,
                    "error": f"Exit quantity exceeds long position. Available: {held_qty}, Requested: {quantity}",
                }
        else:
            short_qty = abs(held_qty) if held_qty < 0 else 0
            if short_qty <= 0:
                return {
                    "success": False,
                    "error": "BUY exit orders require an open SHORT position",
                }
            if quantity > short_qty:
                return {
                    "success": False,
                    "error": f"Exit quantity exceeds short position. Available: {short_qty}, Requested: {quantity}",
                }

        if order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
            trigger = _to_decimal(trigger_price)
            if side == "SELL" and trigger >= current_price:
                return {
                    "success": False,
                    "error": "SELL stop-loss trigger must be below current market price",
                }
            if side == "BUY" and trigger <= current_price:
                return {
                    "success": False,
                    "error": "BUY stop-loss trigger must be above current market price",
                }

        if order_type == "TAKE_PROFIT":
            target = _to_decimal(price)
            entry = _to_decimal(symbol_holding.avg_price or current_price)
            if side == "SELL" and target <= entry:
                return {
                    "success": False,
                    "error": "SELL take-profit target must be above entry price",
                }
            if side == "BUY" and target >= entry:
                return {
                    "success": False,
                    "error": "BUY take-profit target must be below entry price",
                }

    # ── Risk Engine pre-trade validation ────────────────────────
    risk_result = await risk_engine.validate_order(
        db=db,
        user_id=user_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=float(execution_price),
        is_algo=bool(
            tag
            and str(tag).upper() in ("ZEROLOSS", "ALGO")
            and not is_exit_order
        ),
        bypass_market_session=bypass_market_session,
        is_reducing=is_reducing,
    )
    if not risk_result.passed:
        return {
            "success": False,
            "error": f"Risk check failed ({risk_result.check_name}): {risk_result.reason}",
        }

    # Check capital for BUY orders that increase exposure (not position-reducing exits)
    # MIS (intraday) gets 5x leverage — only 1/5 margin required (like real brokers)
    if side == "BUY" and not is_exit_order and not is_reducing:
        required_capital = (
            total_cost / Decimal("5") if product_type == "MIS" else total_cost
        )
        available_capital = _to_decimal(portfolio.available_capital or 0)
        if required_capital > available_capital:
            return {
                "success": False,
                "error": f"Insufficient capital. Required: ₹{required_capital:,.2f}, Available: ₹{available_capital:,.2f}",
            }

    # Check holdings for SELL orders — only CNC (delivery) requires holdings.
    # MIS (intraday) and NRML allow short selling.
    if side == "SELL" and product_type == "CNC" and not is_exit_order:
        holding = symbol_holding
        if not holding or holding.quantity < quantity:
            available = holding.quantity if holding else 0
            return {
                "success": False,
                "error": f"Insufficient holdings for CNC sell. Available: {available}, Requested: {quantity}. Use MIS for short selling.",
            }

    # For MIS/NRML short sell, ensure sufficient margin (require capital for the position)
    if side == "SELL" and product_type != "CNC" and not is_exit_order:
        # Check if user has existing holdings to sell
        holding = symbol_holding
        has_holdings = holding and holding.quantity >= quantity
        # If no holdings, this is a short sell — require margin capital
        if not has_holdings:
            margin_required = (
                total_cost / Decimal("5") if product_type == "MIS" else total_cost
            )
            available_capital = _to_decimal(portfolio.available_capital or 0)
            if margin_required > available_capital:
                return {
                    "success": False,
                    "error": f"Insufficient margin for short sell. Required: ₹{margin_required:,.2f}, Available: ₹{available_capital:,.2f}",
                }

    # Create order
    exchange = "MCX" if is_mcx_symbol(symbol) else "NSE"
    order = Order(
        user_id=uuid.UUID(str(user_id)) if isinstance(user_id, (str, uuid.UUID)) else user_id,
        symbol=symbol,
        exchange=exchange,
        order_type=order_type,
        side=side,
        product_type=product_type,
        quantity=quantity,
        price=price,
        trigger_price=trigger_price,
        take_profit_price=take_profit_price,
        tag=tag,
        idempotency_key=idempotency_key,
    )
    db.add(order)
    await db.flush()

    # Execute MARKET orders immediately
    if order_type == "MARKET":
        order.status = "FILLED"
        order.filled_quantity = quantity
        order.filled_price = current_price
        order.executed_at = datetime.now(timezone.utc)

        # Update portfolio
        await _update_portfolio_on_fill(
            db,
            portfolio,
            symbol,
            side,
            quantity,
            current_price,
            order.id,
            user_id,
            quote.get("name", symbol),
            product_type=product_type,
        )
    elif order_type in ("LIMIT", "BRACKET"):
        # LIMIT orders: only fill immediately if price has ALREADY reached/passed the limit.
        # BUY LIMIT at price X: only fill if current_price <= X (price at or BELOW your limit)
        # SELL LIMIT at price X: only fill if current_price >= X (price at or ABOVE your limit)
        # Otherwise, stay OPEN pending price movement to the limit level.
        should_fill_now = (side == "BUY" and current_price <= execution_price) or (
            side == "SELL" and current_price >= execution_price
        )
        if should_fill_now:
            # Price has already reached the limit — execute immediately
            order.status = "FILLED"
            order.filled_quantity = quantity
            order.filled_price = execution_price
            order.executed_at = datetime.now(timezone.utc)
            await _update_portfolio_on_fill(
                db,
                portfolio,
                symbol,
                side,
                quantity,
                execution_price,
                order.id,
                user_id,
                quote.get("name", symbol),
                product_type=product_type,
            )
            if order_type == "BRACKET":
                await _create_bracket_child_orders(db, order, user_id)
        else:
            # Price hasn't reached the limit yet — place as OPEN pending price movement
            order.status = "OPEN"
            # Reserve capital for open BUY orders so capital isn't double-allocated.
            if side == "BUY":
                reserved = (
                    total_cost / Decimal("5") if product_type == "MIS" else total_cost
                )
                portfolio.available_capital = (
                    _to_decimal(portfolio.available_capital or 0) - reserved
                )

    elif order_type == "TAKE_PROFIT":
        # TAKE_PROFIT orders are for closing positions at profit targets.
        # BUY TP (close SHORT position): fills when price DROPS to at/below target (good exit price for short)
        # SELL TP (close LONG position): fills when price RISES to at/above target (good exit price for long)
        should_fill_now = (side == "BUY" and current_price <= execution_price) or (
            side == "SELL" and current_price >= execution_price
        )
        if should_fill_now:
            # Target price reached — execute immediately
            order.status = "FILLED"
            order.filled_quantity = quantity
            order.filled_price = execution_price
            order.executed_at = datetime.now(timezone.utc)
            await _update_portfolio_on_fill(
                db,
                portfolio,
                symbol,
                side,
                quantity,
                execution_price,
                order.id,
                user_id,
                quote.get("name", symbol),
                product_type=product_type,
            )
        else:
            # Target not reached yet — stay OPEN
            order.status = "OPEN"

    elif order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
        # STOP_LOSS orders are for cutting losses / protecting positions.
        # SELL SL (protect LONG position): triggered when price falls AT/BELOW stop level
        # BUY SL (protect SHORT position): triggered when price rises AT/ABOVE stop level
        # Always stay OPEN at placement — will be evaluated by order worker when price hits trigger.
        order.status = "OPEN"
    else:
        # Unknown order type — mark as OPEN (should not reach here)
        order.status = "OPEN"

    await db.flush()

    # ── Emit events for downstream consumers ────────────────────
    if order.status == "FILLED":
        event_bus.emit_nowait(
            Event(
                type=EventType.ORDER_FILLED,
                data={
                    "order_id": str(order.id),
                    "user_id": user_id,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "filled_price": (
                        float(order.filled_price) if order.filled_price else None
                    ),
                },
                user_id=user_id,
                source="trading_engine",
            )
        )
    else:
        event_bus.emit_nowait(
            Event(
                type=EventType.ORDER_PLACED,
                data={
                    "order_id": str(order.id),
                    "user_id": user_id,
                    "symbol": symbol,
                    "side": side,
                    "order_type": order_type,
                    "quantity": quantity,
                    "price": price,
                    "trigger_price": trigger_price,
                    "take_profit_price": take_profit_price,
                    "status": order.status,
                },
                user_id=user_id,
                source="trading_engine",
            )
        )

    return {
        "success": True,
        "order_id": str(order.id),
        "order": {
            "id": str(order.id),
            "symbol": order.symbol,
            "side": order.side,
            "order_type": order.order_type,
            "product_type": order.product_type,
            "quantity": order.quantity,
            "price": float(order.price) if order.price is not None else None,
            "trigger_price": (
                float(order.trigger_price) if order.trigger_price is not None else None
            ),
            "take_profit_price": (
                float(order.take_profit_price)
                if order.take_profit_price is not None
                else None
            ),
            "filled_price": (
                float(order.filled_price) if order.filled_price is not None else None
            ),
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        },
    }


async def _create_bracket_child_orders(
    db: AsyncSession, parent_order: Order, user_id: str
) -> None:
    """Create the attached stop-loss and take-profit exit legs for a bracket entry."""
    if parent_order.order_type != "BRACKET":
        return

    exit_side = "SELL" if parent_order.side == "BUY" else "BUY"
    bracket_ref = str(parent_order.id)[-8:]

    if parent_order.trigger_price is not None:
        db.add(
            Order(
                user_id=user_id,
                symbol=parent_order.symbol,
                exchange=parent_order.exchange,
                order_type="STOP_LOSS",
                side=exit_side,
                product_type=parent_order.product_type,
                quantity=parent_order.quantity,
                price=None,
                trigger_price=parent_order.trigger_price,
                take_profit_price=None,
                tag=f"BRK_SL_{bracket_ref}",
                status="OPEN",
            )
        )

    if parent_order.take_profit_price is not None:
        db.add(
            Order(
                user_id=user_id,
                symbol=parent_order.symbol,
                exchange=parent_order.exchange,
                order_type="TAKE_PROFIT",
                side=exit_side,
                product_type=parent_order.product_type,
                quantity=parent_order.quantity,
                price=parent_order.take_profit_price,
                trigger_price=None,
                take_profit_price=None,
                tag=f"BRK_TP_{bracket_ref}",
                status="OPEN",
            )
        )


async def _cancel_orphaned_exit_orders(
    db: AsyncSession, user_id: str, symbol: str
) -> int:
    """Cancel open SL/TP orders for a symbol when its position is fully closed.

    Called automatically when a holding is deleted (quantity reaches 0) so that
    dangling stop-loss / take-profit orders don't trigger against a position that
    no longer exists.
    """
    result = await db.execute(
        select(Order).where(
            and_(
                Order.user_id == user_id,
                Order.symbol == symbol,
                Order.status == "OPEN",
                Order.order_type.in_(["STOP_LOSS", "TAKE_PROFIT", "STOP_LOSS_LIMIT"]),
            )
        )
    )
    orders = result.scalars().all()
    cancelled = 0
    now = datetime.now(timezone.utc)
    for o in orders:
        o.status = "CANCELLED"
        o.updated_at = now
        cancelled += 1
    if cancelled:
        logger.info(
            f"Auto-cancelled {cancelled} orphaned exit order(s) for {symbol} "
            f"(user={user_id}) after position fully closed."
        )
    return cancelled


async def _update_portfolio_on_fill(
    db: AsyncSession,
    portfolio: Portfolio,
    symbol: str,
    side: str,
    quantity: int,
    price,
    order_id: str,
    user_id: str,
    company_name: str = "",
    product_type: str = "CNC",
):
    """Update portfolio holdings after order fill."""
    lock = _get_holding_update_lock(portfolio.id, symbol)
    async with lock:
        await _update_portfolio_on_fill_unlocked(
            db=db,
            portfolio=portfolio,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_id=order_id,
            user_id=user_id,
            company_name=company_name,
            product_type=product_type,
        )


async def _update_portfolio_on_fill_unlocked(
    db: AsyncSession,
    portfolio: Portfolio,
    symbol: str,
    side: str,
    quantity: int,
    price,
    order_id: str,
    user_id: str,
    company_name: str = "",
    product_type: str = "CNC",
):
    """Update portfolio holdings after order fill."""
    # Serialize updates per portfolio to avoid concurrent duplicate inserts
    # on unique key (portfolio_id, symbol).
    await db.execute(
        select(Portfolio.id).where(Portfolio.id == portfolio.id).with_for_update()
    )

    price = _to_decimal(price)
    total_value = price * quantity

    # Ensure all portfolio fields are Decimal before arithmetic
    portfolio.available_capital = _to_decimal(portfolio.available_capital or 0)
    portfolio.total_invested = _to_decimal(portfolio.total_invested or 0)
    portfolio.total_pnl = _to_decimal(portfolio.total_pnl or 0)

    if side == "BUY":
        # Update or create holding
        result = await db.execute(
            select(Holding).where(
                and_(
                    Holding.portfolio_id == portfolio.id,
                    Holding.symbol == symbol,
                    Holding.product_type == product_type,
                )
            )
        )
        holding = result.scalar_one_or_none()

        # Normalize holding numeric fields to Decimal to avoid None/float mixing
        if holding:
            holding.avg_price = _to_decimal(holding.avg_price or 0)
            holding.invested_value = _to_decimal(holding.invested_value or 0)
            holding.current_price = _to_decimal(holding.current_price or 0)
            holding.current_value = _to_decimal(holding.current_value or 0)

        if holding and holding.quantity < 0:
            # Closing (or reducing) a SHORT position — buy back shares
            close_qty = min(quantity, abs(holding.quantity))
            # P&L for short: sold high (avg_price), buying back at current price
            holding_avg_price = _to_decimal(holding.avg_price or 0)
            short_pnl = (holding_avg_price - price) * close_qty
            # Release the margin that was blocked when opening the short,
            # then apply the P&L (profit or loss from the short trade)
            margin_per_share = (
                holding_avg_price / Decimal("5")
                if product_type == "MIS"
                else holding_avg_price
            )
            portfolio.available_capital += (margin_per_share * close_qty) + short_pnl
            portfolio.total_pnl += short_pnl

            remaining_short = abs(holding.quantity) - close_qty
            if remaining_short <= 0:
                await db.delete(holding)
                await db.flush()
                await _cancel_orphaned_exit_orders(db, user_id, symbol)
            else:
                holding.quantity = -remaining_short
                holding.invested_value = -(holding_avg_price * remaining_short)
                holding.current_price = price
                holding.current_value = -(price * remaining_short)
                holding.pnl = holding.invested_value - holding.current_value
                holding.pnl_percent = (
                    (holding.pnl / abs(holding.invested_value) * 100)
                    if holding.invested_value
                    else 0
                )

            # If buying more than the short, create a long position with the remainder
            leftover = quantity - close_qty
            if leftover > 0:
                portfolio.available_capital -= price * leftover
                portfolio.total_invested += price * leftover
                existing_result = await db.execute(
                    select(Holding).where(
                        and_(
                            Holding.portfolio_id == portfolio.id,
                            Holding.symbol == symbol,
                            Holding.product_type == product_type,
                        )
                    )
                )
                existing_holding = existing_result.scalar_one_or_none()
                if existing_holding:
                    existing_holding.company_name = company_name
                    existing_holding.quantity = leftover
                    existing_holding.avg_price = price
                    existing_holding.current_price = price
                    existing_holding.invested_value = price * leftover
                    existing_holding.current_value = price * leftover
                    existing_holding.pnl = existing_holding.current_value - existing_holding.invested_value
                    existing_holding.pnl_percent = 0
                else:
                    await _upsert_holding(
                        db,
                        portfolio,
                        symbol,
                        {
                            "exchange": "NSE",
                            "company_name": company_name,
                            "quantity": leftover,
                            "avg_price": price,
                            "current_price": price,
                            "invested_value": price * leftover,
                            "current_value": price * leftover,
                            "pnl": 0,
                            "pnl_percent": 0,
                        },
                        product_type=product_type,
                    )
        elif holding and holding.quantity >= 0:
            # Adding to existing LONG position — average out
            holding_avg_price = _to_decimal(holding.avg_price or 0)
            portfolio.available_capital -= total_value
            portfolio.total_invested += total_value
            total_qty = holding.quantity + quantity
            holding.avg_price = (
                (holding_avg_price * holding.quantity) + (price * quantity)
            ) / total_qty
            holding.quantity = total_qty
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
            # Brand new long position
            portfolio.available_capital -= total_value
            portfolio.total_invested += total_value
            existing_result = await db.execute(
                select(Holding).where(
                    and_(
                        Holding.portfolio_id == portfolio.id,
                        Holding.symbol == symbol,
                        Holding.product_type == product_type,
                    )
                )
            )
            existing_holding = existing_result.scalar_one_or_none()
            if existing_holding:
                existing_holding.company_name = company_name
                existing_holding.quantity = quantity
                existing_holding.avg_price = price
                existing_holding.current_price = price
                existing_holding.invested_value = total_value
                existing_holding.current_value = total_value
                existing_holding.pnl = existing_holding.current_value - existing_holding.invested_value
                existing_holding.pnl_percent = 0
            else:
                await _upsert_holding(
                    db,
                    portfolio,
                    symbol,
                    {
                        "exchange": "NSE",
                        "company_name": company_name,
                        "quantity": quantity,
                        "avg_price": price,
                        "current_price": price,
                        "invested_value": total_value,
                        "current_value": total_value,
                        "pnl": 0,
                        "pnl_percent": 0,
                    },
                    product_type=product_type,
                )

    elif side == "SELL":
        result = await db.execute(
            select(Holding).where(
                and_(
                    Holding.portfolio_id == portfolio.id,
                    Holding.symbol == symbol,
                    Holding.product_type == product_type,
                )
            )
        )
        holding = result.scalar_one_or_none()

        # Normalize holding numeric fields to Decimal to avoid None/float mixing
        if holding:
            holding.avg_price = _to_decimal(holding.avg_price or 0)
            holding.invested_value = _to_decimal(holding.invested_value or 0)
            holding.current_price = _to_decimal(holding.current_price or 0)
            holding.current_value = _to_decimal(holding.current_value or 0)

        if holding and holding.quantity >= quantity:
            # Normal sell — selling existing holdings
            holding_avg_price = _to_decimal(holding.avg_price or 0)
            sell_pnl = (price - holding_avg_price) * quantity
            portfolio.available_capital += total_value
            portfolio.total_invested -= holding_avg_price * quantity
            portfolio.total_pnl += sell_pnl

            holding.quantity -= quantity
            if holding.quantity <= 0:
                await db.delete(holding)
                await _cancel_orphaned_exit_orders(db, user_id, symbol)
            else:
                holding.invested_value = holding_avg_price * holding.quantity
                holding.current_price = price
                holding.current_value = price * holding.quantity
                holding.pnl = holding.current_value - holding.invested_value
                holding.pnl_percent = (
                    (holding.pnl / holding.invested_value * 100)
                    if holding.invested_value
                    else 0
                )
        elif holding and holding.quantity < 0:
            # Add to an existing SHORT position.
            holding_avg_price = _to_decimal(holding.avg_price or 0)
            short_qty = abs(holding.quantity) + quantity
            margin_blocked = (
                (price * quantity) / Decimal("5")
                if product_type == "MIS"
                else price * quantity
            )
            portfolio.available_capital -= margin_blocked
            portfolio.total_pnl += (holding_avg_price - price) * quantity

            holding.quantity = -short_qty
            holding.invested_value = -(holding_avg_price * short_qty)
            holding.current_price = price
            holding.current_value = -(price * short_qty)
            holding.pnl = holding.invested_value - holding.current_value
            holding.pnl_percent = (
                (holding.pnl / abs(holding.invested_value) * 100)
                if holding.invested_value
                else 0
            )
        else:
            # Short sell — no holdings or partial. Create short position.
            # For short: we receive cash now, owe shares. Track as negative holding.
            short_qty = quantity - (
                holding.quantity if holding and holding.quantity > 0 else 0
            )

            # Close out any existing long position first
            if holding and holding.quantity > 0:
                close_qty = holding.quantity
                holding_avg_price = _to_decimal(holding.avg_price or 0)
                sell_pnl = (price - holding_avg_price) * close_qty
                portfolio.available_capital += price * close_qty
                portfolio.total_invested -= holding_avg_price * close_qty
                portfolio.total_pnl += sell_pnl
                await db.delete(holding)
                await db.flush()
                holding = None

            # Create short position — block margin from available capital
            # MIS gets 5x leverage, so only 1/5 margin is blocked
            margin_blocked = (
                (price * short_qty) / Decimal("5")
                if product_type == "MIS"
                else price * short_qty
            )
            portfolio.available_capital -= margin_blocked

            if holding and holding.quantity == 0:
                holding.company_name = company_name
                holding.quantity = -short_qty
                holding.avg_price = price
                holding.current_price = price
                holding.invested_value = -(price * short_qty)
                holding.current_value = -(price * short_qty)
                holding.pnl = 0
                holding.pnl_percent = 0
            else:
                await _upsert_holding(
                    db,
                    portfolio,
                    symbol,
                    {
                        "exchange": "NSE",
                        "company_name": company_name,
                        "quantity": -short_qty,  # Negative = short position
                        "avg_price": price,
                        "current_price": price,
                        "invested_value": -(price * short_qty),
                        "current_value": -(price * short_qty),
                        "pnl": 0,
                        "pnl_percent": 0,
                    },
                    product_type=product_type,
                )

    # Create transaction record
    txn = Transaction(
        user_id=uuid.UUID(str(user_id)) if isinstance(user_id, (str, uuid.UUID)) else user_id,
        order_id=uuid.UUID(str(order_id)) if isinstance(order_id, (str, uuid.UUID)) else order_id,
        symbol=symbol,
        transaction_type=side,
        quantity=quantity,
        price=price,
        total_value=total_value,
    )
    db.add(txn)

    # Recalculate portfolio totals
    await _recalculate_portfolio(db, portfolio)

    # Invalidate cached portfolio data so the next API fetch is fresh
    _invalidate_portfolio_cache(str(user_id))


async def _recalculate_portfolio(db: AsyncSession, portfolio: Portfolio):
    """Recalculate portfolio current value and P&L."""
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio.id)
    )
    holdings = result.scalars().all()

    total_invested = sum(_to_decimal(h.invested_value or 0) for h in holdings)
    current_value = sum(_to_decimal(h.current_value or 0) for h in holdings)

    portfolio.total_invested = total_invested
    portfolio.current_value = current_value
    unrealized_pnl = current_value - total_invested
    # total_pnl already tracks realized P&L from sells; don't overwrite
    total_pnl = _to_decimal(portfolio.total_pnl or 0)
    user_result = await db.execute(
        select(User.virtual_capital).where(User.id == portfolio.user_id)
    )
    base_capital = _to_decimal(user_result.scalar_one_or_none() or 0)
    abs_total_invested = abs(total_invested) if total_invested else 0
    pnl_denominator = abs(base_capital) if base_capital else abs_total_invested
    net_equity = base_capital + total_pnl + unrealized_pnl
    portfolio.available_capital = _normalize_available_capital(
        _to_decimal(portfolio.available_capital or 0),
        net_equity,
        len(holdings),
    )
    portfolio.total_pnl_percent = (
        ((total_pnl + unrealized_pnl) / pnl_denominator * 100) if pnl_denominator else 0
    )


async def cancel_order(db: AsyncSession, user_id: str, order_id: str) -> dict:
    """Cancel an open order and release any reserved capital."""
    result = await db.execute(
        select(Order).where(and_(Order.id == order_id, Order.user_id == user_id))
    )
    order = result.scalar_one_or_none()

    if not order:
        return {"success": False, "error": "Order not found"}
    if order.status not in ("OPEN", "PENDING"):
        return {
            "success": False,
            "error": f"Cannot cancel order with status: {order.status}",
        }

    order.status = "CANCELLED"
    order.updated_at = datetime.now(timezone.utc)

    # Release capital that was reserved when the open BUY LIMIT order was placed.
    if (
        order.side == "BUY"
        and order.order_type in ("LIMIT", "BRACKET")
        and order.price is not None
    ):
        try:
            port_result = await db.execute(
                select(Portfolio).where(Portfolio.user_id == user_id)
            )
            portfolio = port_result.scalar_one_or_none()
            if portfolio:
                reserved_price = _to_decimal(order.price)
                qty = order.quantity or 0
                product_type = order.product_type or "CNC"
                reserved = (
                    reserved_price * qty / Decimal("5")
                    if product_type == "MIS"
                    else reserved_price * qty
                )
                portfolio.available_capital = (
                    _to_decimal(portfolio.available_capital or 0) + reserved
                )
        except Exception as e:
            logger.warning(
                f"Capital release on cancel failed for order {order_id}: {e}"
            )

    await db.commit()

    event_bus.emit_nowait(
        Event(
            type=EventType.ORDER_CANCELLED,
            data={
                "order_id": str(order.id),
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
            },
            user_id=user_id,
            source="trading_engine",
        )
    )

    return {"success": True, "message": "Order cancelled successfully"}


async def check_pending_orders(db: AsyncSession, user_id: str):
    """Check and execute pending limit/stop-loss orders against current prices."""
    result = await db.execute(
        select(Order).where(and_(Order.user_id == user_id, Order.status == "OPEN"))
    )
    open_orders = result.scalars().all()

    for order in open_orders:
        quote = await market_data.get_quote_safe(order.symbol, user_id)
        if not quote:
            continue

        current_price = _to_decimal(quote["price"])
        should_execute = False

        if order.order_type in ("LIMIT", "BRACKET"):
            if order.price is None:
                continue
            if order.side == "BUY" and current_price <= _to_decimal(order.price):
                should_execute = True
            elif order.side == "SELL" and current_price >= _to_decimal(order.price):
                should_execute = True

        elif order.order_type == "TAKE_PROFIT":
            if order.price is None:
                continue
            # SELL TP (close long): fires when price rises to/above target
            # BUY TP (close short): fires when price drops to/below target
            if order.side == "SELL" and current_price >= _to_decimal(order.price):
                should_execute = True
            elif order.side == "BUY" and current_price <= _to_decimal(order.price):
                should_execute = True

        elif order.order_type in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
            if order.trigger_price is None:
                continue
            # SELL SL (protect long): fires when price drops to/below trigger
            # BUY SL (protect short): fires when price rises to/above trigger
            if order.side == "SELL" and current_price <= _to_decimal(order.trigger_price):
                should_execute = True
            elif order.side == "BUY" and current_price >= _to_decimal(order.trigger_price):
                should_execute = True

        if should_execute:
            portfolio_result = await db.execute(
                select(Portfolio).where(Portfolio.user_id == user_id)
            )
            portfolio = portfolio_result.scalar_one_or_none()
            if portfolio:
                order.status = "FILLED"
                order.filled_quantity = order.quantity
                order.filled_price = current_price
                order.executed_at = datetime.now(timezone.utc)
                await _update_portfolio_on_fill(
                    db,
                    portfolio,
                    order.symbol,
                    order.side,
                    order.quantity,
                    current_price,
                    order.id,
                    user_id,
                    product_type=order.product_type or "CNC",
                )
