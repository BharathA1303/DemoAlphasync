from decimal import Decimal
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from database.connection import get_db
from models.user import User
from models.order import Order
from models.portfolio import Portfolio, Holding, Transaction
from routes.auth import get_current_user
from services.portfolio_service import (
    get_portfolio_summary,
    get_holdings,
    get_global_pnl_leaderboard,
    invalidate_user_portfolio_cache,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])

DEFAULT_CAPITAL = Decimal("1000000.00")  # 10 Lakh


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _sort_dt(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _reconcile_lots_to_target(
    lots: list[dict],
    target_qty: int,
    fallback_entry: Decimal,
    fallback_ts,
    symbol: str,
) -> list[dict]:
    if target_qty == 0:
        return []

    sign = 1 if target_qty > 0 else -1
    required = abs(int(target_qty))

    same_sign = [
        dict(lot) for lot in lots if int(lot.get("remaining_qty", 0)) * sign > 0
    ]
    same_sign.sort(key=lambda lot: _sort_dt(lot.get("created_at")), reverse=True)

    kept = []
    remaining = required
    for lot in same_sign:
        if remaining <= 0:
            break
        lot_qty = abs(int(lot.get("remaining_qty", 0)))
        if lot_qty <= 0:
            continue
        take = min(lot_qty, remaining)
        lot["remaining_qty"] = sign * take
        kept.append(lot)
        remaining -= take

    if remaining > 0:
        kept.append(
            {
                "id": f"synthetic-{symbol}-{sign}-{remaining}",
                "order_id": None,
                "symbol": symbol,
                "entry_price": fallback_entry,
                "remaining_qty": sign * remaining,
                "created_at": fallback_ts,
                "synthetic": True,
            }
        )

    return kept


@router.get("")
async def get_portfolio(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await get_portfolio_summary(db, user.id)
    return summary


@router.get("/holdings")
async def get_user_holdings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    holdings = await get_holdings(db, user.id)
    return {"holdings": holdings}


@router.get("/summary")
async def get_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await get_portfolio_summary(db, user.id)
    holdings = await get_holdings(db, user.id)
    return {
        "summary": summary,
        "holdings": holdings,
    }


@router.get("/transactions")
async def get_transactions(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    symbol: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Transaction, Order.product_type)
        .outerjoin(Order, Transaction.order_id == Order.id)
        .where(Transaction.user_id == user.id)
    )
    if symbol:
        query = query.where(Transaction.symbol == symbol)

    query = query.order_by(Transaction.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.all()

    return {
        "transactions": [
            {
                "id": str(tx.id),
                "order_id": str(tx.order_id) if tx.order_id else None,
                "symbol": tx.symbol,
                "product_type": str(prod_type or "CNC").upper(),
                "transaction_type": tx.transaction_type,
                "quantity": tx.quantity,
                "price": float(tx.price) if tx.price is not None else None,
                "total_value": (
                    float(tx.total_value) if tx.total_value is not None else None
                ),
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx, prod_type in rows
        ],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(rows),
        },
    }


@router.get("/open-lots")
async def get_open_lots(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return {"open_lots": [], "count": 0}

    holdings_result = await db.execute(
        select(Holding).where(
            Holding.portfolio_id == portfolio.id,
            Holding.quantity != 0,
        )
    )
    holdings = holdings_result.scalars().all()
    if not holdings:
        return {"open_lots": [], "count": 0}

    # Group holdings by (symbol, product_type)
    holdings_by_key = {}
    symbols_set = set()
    for holding in holdings:
        symbol = _normalize_symbol(holding.symbol)
        product_type = str(holding.product_type or "CNC").upper()
        if symbol:
            holdings_by_key[(symbol, product_type)] = holding
            symbols_set.add(symbol)

    symbols = list(symbols_set)
    if not symbols:
        return {"open_lots": [], "count": 0}

    # Query transactions with their corresponding order's product_type
    tx_result = await db.execute(
        select(Transaction, Order.product_type)
        .outerjoin(Order, Transaction.order_id == Order.id)
        .where(
            Transaction.user_id == user.id,
            Transaction.symbol.in_(symbols),
        )
        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
    )
    tx_rows = tx_result.all()

    lots_by_key = {}

    for row in tx_rows:
        tx = row[0]
        product_type = str(row[1] or "CNC").upper()
        symbol = _normalize_symbol(tx.symbol)
        key = (symbol, product_type)

        if key not in lots_by_key:
            lots_by_key[key] = []

        side = str(tx.transaction_type or "").upper().strip()
        qty = int(tx.quantity or 0)
        price = _to_decimal(tx.price or 0)
        if side not in ("BUY", "SELL") or qty <= 0 or price <= 0:
            continue

        lots = lots_by_key[key]
        remaining = qty

        if side == "BUY":
            # Buy closes earlier short lots first, then opens long lots.
            for lot in lots:
                if remaining <= 0:
                    break
                lot_qty = int(lot.get("remaining_qty", 0))
                if lot_qty >= 0:
                    continue
                cover = min(remaining, abs(lot_qty))
                lot["remaining_qty"] = lot_qty + cover
                remaining -= cover

            if remaining > 0:
                lots.append(
                    {
                        "id": str(tx.id),
                        "order_id": str(tx.order_id) if tx.order_id else None,
                        "symbol": symbol,
                        "product_type": product_type,
                        "entry_price": price,
                        "remaining_qty": remaining,
                        "created_at": tx.created_at,
                        "synthetic": False,
                    }
                )
        else:
            # Sell closes earlier long lots first, then opens short lots.
            for lot in lots:
                if remaining <= 0:
                    break
                lot_qty = int(lot.get("remaining_qty", 0))
                if lot_qty <= 0:
                    continue
                close = min(remaining, lot_qty)
                lot["remaining_qty"] = lot_qty - close
                remaining -= close

            if remaining > 0:
                lots.append(
                    {
                        "id": str(tx.id),
                        "order_id": str(tx.order_id) if tx.order_id else None,
                        "symbol": symbol,
                        "product_type": product_type,
                        "entry_price": price,
                        "remaining_qty": -remaining,
                        "created_at": tx.created_at,
                        "synthetic": False,
                    }
                )

    open_lots = []

    for key, holding in holdings_by_key.items():
        symbol, product_type = key
        target_qty = int(holding.quantity or 0)
        if target_qty == 0:
            continue

        holding_avg = _to_decimal(holding.avg_price or 0)
        reconciled = _reconcile_lots_to_target(
            lots=lots_by_key.get(key, []),
            target_qty=target_qty,
            fallback_entry=holding_avg,
            fallback_ts=getattr(holding, "updated_at", None),
            symbol=symbol,
        )

        current_price = _to_decimal(holding.current_price or holding_avg)

        for lot in reconciled:
            remaining_qty = int(lot.get("remaining_qty", 0))
            qty = abs(remaining_qty)
            if qty <= 0:
                continue

            entry_price = _to_decimal(lot.get("entry_price") or holding_avg)
            side = "LONG" if remaining_qty > 0 else "SHORT"
            pnl = (
                (entry_price - current_price) * qty
                if side == "SHORT"
                else (current_price - entry_price) * qty
            )
            base_value = entry_price * qty
            pnl_percent = (pnl / base_value * 100) if base_value else Decimal("0")

            open_lots.append(
                {
                    "id": lot.get("id"),
                    "order_id": lot.get("order_id"),
                    "symbol": symbol,
                    "product_type": product_type,
                    "side": side,
                    "entry_price": float(entry_price),
                    "remaining_qty": remaining_qty,
                    "quantity": qty,
                    "current_price": float(current_price),
                    "pnl": float(pnl),
                    "pnl_percent": float(pnl_percent),
                    "synthetic": bool(lot.get("synthetic", False)),
                    "created_at": (
                        lot.get("created_at").isoformat()
                        if isinstance(lot.get("created_at"), datetime)
                        else None
                    ),
                }
            )

    open_lots.sort(
        key=lambda row: row.get("created_at") or "",
        reverse=True,
    )

    return {"open_lots": open_lots, "count": len(open_lots)}


@router.get("/leaderboard")
async def get_leaderboard(
    limit: int = Query(default=10, ge=1, le=50),
    period: str = Query(default="all_time"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Global PnL leaderboard shared across all authenticated users."""
    data = await get_global_pnl_leaderboard(
        db,
        limit=limit,
        period=period,
        current_user_id=user.id,
    )
    return data


# ── Capital Management ─────────────────────────────────────────────────────


class AddCapitalRequest(BaseModel):
    amount: float  # Amount in rupees to add


class SetCapitalRequest(BaseModel):
    amount: float  # New total capital amount


@router.post("/add-capital")
async def add_capital(
    req: AddCapitalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add additional capital to the portfolio."""
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if req.amount > 100_000_000:  # 10 crore max
        raise HTTPException(
            status_code=400, detail="Maximum single addition is 10 crore"
        )

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    amount = Decimal(str(req.amount))
    portfolio.available_capital = Decimal(str(portfolio.available_capital or 0))
    user.virtual_capital = Decimal(str(user.virtual_capital or 0))
    portfolio.available_capital += amount
    user.virtual_capital += amount
    await db.commit()
    invalidate_user_portfolio_cache(str(user.id))

    logger.info(f"[Capital] User {str(user.id)[:8]} added ₹{amount:,.2f}")
    return {
        "success": True,
        "available_capital": float(portfolio.available_capital),
        "message": f"Added ₹{amount:,.2f} to your portfolio",
    }


@router.post("/reset-capital")
async def reset_capital(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset capital back to default (10 Lakh) without affecting positions."""
    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    portfolio.available_capital = DEFAULT_CAPITAL
    portfolio.total_pnl = Decimal("0")
    portfolio.total_pnl_percent = Decimal("0")
    user.virtual_capital = DEFAULT_CAPITAL
    await db.commit()
    invalidate_user_portfolio_cache(str(user.id))

    logger.info(
        f"[Capital] User {str(user.id)[:8]} reset capital to ₹{DEFAULT_CAPITAL:,.2f}"
    )
    return {
        "success": True,
        "available_capital": float(portfolio.available_capital),
        "message": f"Capital reset to ₹{DEFAULT_CAPITAL:,.2f}",
    }


@router.post("/set-capital")
async def set_capital(
    req: SetCapitalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set available capital to a custom amount."""
    if req.amount < 0:
        raise HTTPException(status_code=400, detail="Amount cannot be negative")
    if req.amount > 1_000_000_000:  # 100 crore max
        raise HTTPException(status_code=400, detail="Maximum capital is 100 crore")

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    amount = Decimal(str(req.amount))
    portfolio.available_capital = amount
    user.virtual_capital = amount
    await db.commit()
    invalidate_user_portfolio_cache(str(user.id))

    logger.info(f"[Capital] User {str(user.id)[:8]} set capital to ₹{req.amount:,.2f}")
    return {
        "success": True,
        "available_capital": float(portfolio.available_capital),
        "message": f"Capital set to ₹{req.amount:,.2f}",
    }


@router.post("/reset-account")
async def reset_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full account reset — clears all positions, orders, and resets capital to 10L."""
    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Delete all holdings
    await db.execute(delete(Holding).where(Holding.portfolio_id == portfolio.id))

    # Delete all orders
    await db.execute(delete(Order).where(Order.user_id == user.id))

    # Delete all transactions
    try:
        await db.execute(delete(Transaction).where(Transaction.user_id == user.id))
    except Exception:
        pass  # Transaction table may not exist

    # Reset portfolio
    portfolio.available_capital = DEFAULT_CAPITAL
    portfolio.total_invested = Decimal("0")
    portfolio.current_value = Decimal("0")
    portfolio.total_pnl = Decimal("0")
    portfolio.total_pnl_percent = Decimal("0")
    user.virtual_capital = DEFAULT_CAPITAL

    await db.commit()
    invalidate_user_portfolio_cache(str(user.id))

    logger.info(f"[Account] User {str(user.id)[:8]} full account reset")
    return {
        "success": True,
        "message": "Account reset complete. Capital restored to ₹10,00,000. All positions and orders cleared.",
    }
