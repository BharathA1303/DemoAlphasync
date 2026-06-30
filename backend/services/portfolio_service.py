"""
Portfolio Service — Holdings and P&L with batch quote optimization.

Fixes the N+1 query pattern: instead of fetching quotes one-by-one per holding,
we batch-fetch all symbols in a single call, then apply to each holding.
Results are cached in the SmartCache to avoid redundant DB + quote lookups
on rapid-fire frontend polling.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from models.portfolio import Portfolio, Holding
from models.order import Order
from models.portfolio import Transaction
from models.user import User
from services import market_data
from cache.smart_cache import portfolio_cache, holdings_cache, quote_cache
import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import uuid

logger = logging.getLogger(__name__)


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _to_iso_utc(value) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _derive_position_metadata(holding_qty: int, transactions: list, orders_by_id: dict, target_product_type: str) -> dict:
    """Derive position lifecycle metadata for a symbol.

    Returns entry_time, product_type and position_status for the currently-open
    lifecycle (the one that produced the current non-zero holding quantity).
    """
    net_qty = 0
    lifecycle_start = None
    lifecycle_open_order_id = None
    lifecycle_last_order_id = None
    lifecycle_max_abs_qty = 0
    lifecycle_had_reduction = False

    target_product_type = str(target_product_type or "CNC").upper()

    for tx in transactions:
        tx_order_id = getattr(tx, "order_id", None)
        tx_order = orders_by_id.get(tx_order_id) if tx_order_id else None
        tx_pt = str(getattr(tx_order, "product_type", None) or "CNC").upper()
        if tx_pt != target_product_type:
            continue

        side = str(getattr(tx, "transaction_type", "") or "").upper().strip()
        qty = int(getattr(tx, "quantity", 0) or 0)
        if side not in ("BUY", "SELL") or qty <= 0:
            continue

        signed_qty = qty if side == "BUY" else -qty
        prev_qty = net_qty
        next_qty = prev_qty + signed_qty

        prev_sign = _sign(prev_qty)
        trade_sign = _sign(signed_qty)
        next_sign = _sign(next_qty)

        if prev_qty == 0 and next_qty != 0:
            lifecycle_start = getattr(tx, "created_at", None)
            lifecycle_open_order_id = getattr(tx, "order_id", None)
            lifecycle_last_order_id = getattr(tx, "order_id", None)
            lifecycle_max_abs_qty = abs(next_qty)
            lifecycle_had_reduction = False
        elif prev_qty != 0:
            if trade_sign != prev_sign:
                lifecycle_had_reduction = True

            if next_qty == 0:
                lifecycle_start = None
                lifecycle_open_order_id = None
                lifecycle_last_order_id = None
                lifecycle_max_abs_qty = 0
                lifecycle_had_reduction = False
            elif next_sign != prev_sign:
                lifecycle_start = getattr(tx, "created_at", None)
                lifecycle_open_order_id = getattr(tx, "order_id", None)
                lifecycle_last_order_id = getattr(tx, "order_id", None)
                lifecycle_max_abs_qty = abs(next_qty)
                lifecycle_had_reduction = False
            else:
                lifecycle_last_order_id = getattr(tx, "order_id", None)
                lifecycle_max_abs_qty = max(lifecycle_max_abs_qty, abs(next_qty))

        net_qty = next_qty

    entry_time = _to_iso_utc(lifecycle_start)
    opening_order = orders_by_id.get(lifecycle_open_order_id)
    latest_order = orders_by_id.get(lifecycle_last_order_id)

    product_type = (
        (getattr(opening_order, "product_type", None) if opening_order else None)
        or (getattr(latest_order, "product_type", None) if latest_order else None)
        or target_product_type
    )

    current_abs_qty = abs(int(holding_qty or 0))
    position_status = "FULL"
    if lifecycle_had_reduction and current_abs_qty > 0 and current_abs_qty < max(
        lifecycle_max_abs_qty, current_abs_qty
    ):
        position_status = "PARTIAL"

    return {
        "entry_time": entry_time,
        "product_type": str(product_type or "CNC").upper(),
        "position_status": position_status,
    }


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_available_capital(
    available_capital: Decimal,
    net_equity: Decimal,
    holdings_count: int,
) -> Decimal:
    """Keep cash and equity internally consistent.

    - Cash should never exceed net equity.
    - When there are no holdings, cash should match net equity.
    """
    if holdings_count <= 0:
        return net_equity
    if available_capital > net_equity:
        return net_equity
    return available_capital


def invalidate_user_portfolio_cache(user_id: str) -> None:
    portfolio_cache.invalidate_prefix(f"summary:{user_id}")
    holdings_cache.invalidate_prefix(f"holdings:{user_id}")


async def _batch_fetch_quotes(symbols: list[str], user_id: str) -> dict[str, dict]:
    """Fetch quotes for all symbols in one batch call instead of N individual calls.

    Uses a three-tier lookup:
        1. SmartCache (in-memory, <1μs)
        2. Batch provider call (network)
    """
    if not symbols:
        return {}

    quotes = {}
    missing = []

    # Tier 1: Check in-memory quote cache
    for sym in symbols:
        cached = quote_cache.get(f"q:{sym}")
        if cached:
            quotes[sym] = cached
        else:
            missing.append(sym)

    # Tier 2: Batch fetch missing symbols
    if missing:
        try:
            batch = await market_data.get_batch_quotes(missing, user_id=user_id)
            for sym, q in batch.items():
                if q:
                    quotes[sym] = q
                    quote_cache.set(f"q:{sym}", q, ttl=5)
        except Exception:
            pass

        # Tier 3: Individual fallback for still-missing symbols
        still_missing = [s for s in missing if s not in quotes]
        for sym in still_missing:
            try:
                q = await market_data.get_quote_safe(sym, user_id)
                if q:
                    quotes[sym] = q
                    quote_cache.set(f"q:{sym}", q, ttl=5)
            except Exception:
                pass

    return quotes


def _apply_quote_to_holding(
    holding, quote: dict, quantity: Decimal, invested_value: Decimal
):
    """Apply a live quote to a holding's computed fields."""
    if quote and quote.get("price"):
        live_price = _to_decimal(quote["price"])
        holding.current_price = live_price
        holding.current_value = live_price * quantity
        holding.pnl = holding.current_value - invested_value
        abs_invested = abs(invested_value)
        holding.pnl_percent = (
            (holding.pnl / abs_invested * 100) if abs_invested else Decimal("0")
        )


def _serialize_leaderboard_entry(user: User, portfolio: Portfolio, rank: int) -> dict:
    total_pnl = _to_decimal(portfolio.total_pnl)
    total_pnl_percent = _to_decimal(portfolio.total_pnl_percent)
    current_value = _to_decimal(portfolio.current_value)
    available_capital = _to_decimal(portfolio.available_capital)
    total_invested = _to_decimal(portfolio.total_invested)

    return {
        "rank": rank,
        "user_id": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "pnl": float(round(total_pnl, 2)),
        "pnl_percent": float(round(total_pnl_percent, 2)),
        "current_value": float(round(current_value, 2)),
        "available_capital": float(round(available_capital, 2)),
        "total_invested": float(round(total_invested, 2)),
    }


def _period_start(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    normalized = (period or "all_time").strip().lower()
    if normalized in {"today", "daily"}:
        return now - timedelta(days=1)
    if normalized == "weekly":
        return now - timedelta(days=7)
    if normalized == "monthly":
        return now - timedelta(days=30)
    if normalized == "yearly":
        return now - timedelta(days=365)
    return None


async def get_portfolio_summary(db: AsyncSession, user_id: str) -> dict:
    """Get complete portfolio summary with real-time P&L.

    Uses batch quote fetching and in-memory caching to minimize latency.
    """
    # Check in-memory cache first
    cache_key = f"summary:{user_id}"
    cached = portfolio_cache.get(cache_key)
    if cached is not None:
        return cached

    user_result = await db.execute(select(User).where(User.id == user_id))
    db_user = user_result.scalar_one_or_none()
    base_capital = _to_decimal(
        db_user.virtual_capital
        if db_user and db_user.virtual_capital is not None
        else Decimal("1000000")
    )

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
    portfolio = result.scalar_one_or_none()

    if not portfolio:
        empty = {
            "total_invested": 0,
            "current_value": 0,
            "available_capital": float(round(base_capital, 2)),
            "base_capital": float(round(base_capital, 2)),
            "net_equity": float(round(base_capital, 2)),
            "total_pnl": 0,
            "total_pnl_percent": 0,
            "realized_pnl": 0,
            "unrealized_pnl": 0,
            "day_pnl": 0,
            "holdings_count": 0,
        }
        portfolio_cache.set(cache_key, empty, ttl=5)
        return empty

    result = await db.execute(
        select(Holding).where(
            Holding.portfolio_id == portfolio.id, Holding.quantity != 0
        )
    )
    holdings = result.scalars().all()

    # Batch fetch all quotes at once (fixes N+1 query)
    symbols = [h.symbol for h in holdings if h.symbol]
    quotes = await _batch_fetch_quotes(symbols, user_id)

    total_invested_signed = Decimal("0")
    current_value_signed = Decimal("0")
    total_invested_gross = Decimal("0")
    current_value_gross = Decimal("0")

    for holding in holdings:
        quantity = _to_decimal(holding.quantity or 0)
        avg_price = _to_decimal(holding.avg_price or 0)
        invested_value = avg_price * quantity
        gross_invested_value = abs(invested_value)

        # Deterministic baseline
        holding.invested_value = invested_value
        holding.current_price = avg_price
        holding.current_value = invested_value
        holding.pnl = Decimal("0")
        holding.pnl_percent = Decimal("0")

        # Apply live quote from batch result
        _apply_quote_to_holding(
            holding, quotes.get(holding.symbol), quantity, invested_value
        )

        holding_current_value = _to_decimal(holding.current_value or 0)
        total_invested_signed += invested_value
        current_value_signed += holding_current_value
        total_invested_gross += gross_invested_value
        current_value_gross += abs(holding_current_value)

    portfolio.total_invested = total_invested_signed
    portfolio.current_value = current_value_signed
    unrealized_pnl = current_value_signed - total_invested_signed
    realized_pnl = _to_decimal(portfolio.total_pnl or 0)
    total_pnl = realized_pnl + unrealized_pnl

    pnl_denominator = abs(base_capital) if base_capital else abs(total_invested_gross)
    total_pnl_percent = (total_pnl / pnl_denominator * 100) if pnl_denominator else 0
    net_equity = base_capital + total_pnl

    available_capital = _normalize_available_capital(
        _to_decimal(portfolio.available_capital),
        net_equity,
        len(holdings),
    )
    portfolio.available_capital = available_capital

    summary = {
        "total_invested": float(round(total_invested_gross, 2)),
        "current_value": float(round(current_value_gross, 2)),
        "available_capital": float(round(available_capital, 2)),
        "base_capital": float(round(base_capital, 2)),
        "net_equity": float(round(net_equity, 2)),
        "total_pnl": float(round(total_pnl, 2)),
        "total_pnl_percent": float(round(total_pnl_percent, 2)),
        "realized_pnl": float(round(realized_pnl, 2)),
        "unrealized_pnl": float(round(unrealized_pnl, 2)),
        "holdings_count": len(holdings),
    }

    portfolio_cache.set(cache_key, summary, ttl=3)
    return summary


async def get_holdings(db: AsyncSession, user_id: str) -> list:
    """Get all holdings with live prices (batch-optimized)."""
    # Check in-memory cache first
    cache_key = f"holdings:{user_id}"
    cached = holdings_cache.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        return []

    result = await db.execute(
        select(Holding).where(
            Holding.portfolio_id == portfolio.id, Holding.quantity != 0
        )
    )
    holdings = result.scalars().all()

    # Batch fetch all quotes at once (fixes N+1 query)
    symbols = [h.symbol for h in holdings if h.symbol]
    quotes = await _batch_fetch_quotes(symbols, user_id)

    holdings_list = []
    for h in holdings:
        quantity = _to_decimal(h.quantity or 0)
        avg_price = _to_decimal(h.avg_price or 0)
        invested_value = avg_price * quantity
        gross_invested_value = abs(invested_value)

        # Deterministic baseline
        h.invested_value = invested_value
        h.current_price = avg_price
        h.current_value = invested_value
        h.pnl = Decimal("0")
        h.pnl_percent = Decimal("0")

        # Apply live quote from batch result
        _apply_quote_to_holding(h, quotes.get(h.symbol), quantity, invested_value)

        position_type = "SHORT" if int(quantity) < 0 else "LONG"
        exchange = (
            str(h.exchange).upper().strip()
            if getattr(h, "exchange", None)
            else "NSE"
        )

        holdings_list.append(
            {
                "id": str(h.id),
                "symbol": h.symbol,
                "company_name": h.company_name
                or (h.symbol.replace(".NS", "") if h.symbol else ""),
                "exchange": exchange,
                "quantity": int(quantity),
                "position_type": position_type,
                "product_type": str(h.product_type or "CNC").upper(),
                "entry_time": _to_iso_utc(h.created_at),
                "position_status": "FULL",
                "avg_price": float(round(avg_price, 2)),
                "current_price": float(round(h.current_price, 2)),
                "invested_value": float(round(gross_invested_value, 2)),
                "current_value": float(round(abs(h.current_value), 2)),
                "pnl": float(round(h.pnl, 2)),
                "pnl_percent": float(round(h.pnl_percent, 2)),
            }
        )

    holdings_cache.set(cache_key, holdings_list, ttl=3)
    return holdings_list


async def get_global_pnl_leaderboard(
    db: AsyncSession,
    limit: int = 10,
    period: str = "all_time",
    current_user_id=None,
) -> dict:
    """Return a global PnL leaderboard visible to all authenticated users.

    The leaderboard is sourced directly from PostgreSQL portfolio rows.
    Winners and losers are computed from the same live DB snapshot so the UI
    can render both sides without any mocked or local fallback values.
    """
    safe_limit = max(1, min(int(limit or 10), 50))
    safe_period = (period or "all_time").strip().lower()
    if safe_period == "daily":
        safe_period = "today"
    if safe_period not in {"today", "weekly", "monthly", "yearly", "all_time"}:
        safe_period = "all_time"

    holdings_snapshot_sq = (
        select(
            Holding.portfolio_id.label("portfolio_id"),
            func.coalesce(func.sum(Holding.avg_price * Holding.quantity), 0).label(
                "total_invested"
            ),
            func.coalesce(
                func.sum(func.coalesce(Holding.current_price, Holding.avg_price) * Holding.quantity),
                0,
            ).label("current_value"),
        )
        .group_by(Holding.portfolio_id)
        .subquery()
    )

    active_filters = []
    period_start = _period_start(safe_period)
    if period_start is not None:
        active_filters.append(Portfolio.updated_at >= period_start)

    effective_pnl_expr = (
        func.coalesce(Portfolio.total_pnl, 0)
        + func.coalesce(holdings_snapshot_sq.c.current_value, 0)
        - func.coalesce(holdings_snapshot_sq.c.total_invested, 0)
    )
    effective_pnl_percent_expr = (
        effective_pnl_expr
        / func.nullif(func.abs(func.coalesce(User.virtual_capital, 1000000)), 0)
        * 100
    )

    non_zero_pnl_filter = func.abs(effective_pnl_expr) > 0

    winners_result = await db.execute(
        select(
            User,
            Portfolio,
            effective_pnl_expr.label("effective_pnl"),
            effective_pnl_percent_expr.label("effective_pnl_percent"),
        )
        .join(Portfolio, Portfolio.user_id == User.id)
        .outerjoin(holdings_snapshot_sq, holdings_snapshot_sq.c.portfolio_id == Portfolio.id)
        .where(*active_filters, non_zero_pnl_filter)
        .order_by(effective_pnl_expr.desc(), effective_pnl_percent_expr.desc())
        .limit(safe_limit)
    )
    losers_result = await db.execute(
        select(
            User,
            Portfolio,
            effective_pnl_expr.label("effective_pnl"),
            effective_pnl_percent_expr.label("effective_pnl_percent"),
        )
        .join(Portfolio, Portfolio.user_id == User.id)
        .outerjoin(holdings_snapshot_sq, holdings_snapshot_sq.c.portfolio_id == Portfolio.id)
        .where(*active_filters, non_zero_pnl_filter)
        .order_by(effective_pnl_expr.asc(), effective_pnl_percent_expr.asc())
        .limit(safe_limit)
    )

    summary_result = await db.execute(
        select(
            func.count(User.id),
            func.sum(case((effective_pnl_expr > 0, 1), else_=0)),
            func.sum(case((effective_pnl_expr < 0, 1), else_=0)),
            func.coalesce(func.sum(effective_pnl_expr), 0),
        )
        .select_from(User)
        .join(Portfolio, Portfolio.user_id == User.id)
        .outerjoin(holdings_snapshot_sq, holdings_snapshot_sq.c.portfolio_id == Portfolio.id)
        .where(*active_filters, non_zero_pnl_filter)
    )
    active_users, profitable_users, losing_users, total_pnl_sum = summary_result.one()

    winners = []
    for idx, (user, portfolio, effective_pnl, effective_pnl_percent) in enumerate(
        winners_result.all(), start=1
    ):
        entry = _serialize_leaderboard_entry(user, portfolio, idx)
        entry["pnl"] = float(round(_to_decimal(effective_pnl), 2))
        entry["pnl_percent"] = float(round(_to_decimal(effective_pnl_percent), 2))
        winners.append(entry)

    losers = []
    for idx, (user, portfolio, effective_pnl, effective_pnl_percent) in enumerate(
        losers_result.all(), start=1
    ):
        entry = _serialize_leaderboard_entry(user, portfolio, idx)
        entry["pnl"] = float(round(_to_decimal(effective_pnl), 2))
        entry["pnl_percent"] = float(round(_to_decimal(effective_pnl_percent), 2))
        losers.append(entry)

    my_position = None
    if current_user_id:
        try:
            current_user_uuid = (
                current_user_id
                if isinstance(current_user_id, uuid.UUID)
                else uuid.UUID(str(current_user_id))
            )
        except (ValueError, TypeError):
            current_user_uuid = None

        if current_user_uuid is not None:
            my_row_result = await db.execute(
                select(
                    User.id,
                    effective_pnl_expr.label("effective_pnl"),
                    effective_pnl_percent_expr.label("effective_pnl_percent"),
                )
                .join(Portfolio, Portfolio.user_id == User.id)
                .outerjoin(holdings_snapshot_sq, holdings_snapshot_sq.c.portfolio_id == Portfolio.id)
                .where(*active_filters, User.id == current_user_uuid)
                .limit(1)
            )
            my_row = my_row_result.first()
            if my_row is not None:
                my_pnl = _to_decimal(my_row.effective_pnl)
                rank_result = await db.execute(
                    select(func.count(User.id))
                    .select_from(User)
                    .join(Portfolio, Portfolio.user_id == User.id)
                    .outerjoin(holdings_snapshot_sq, holdings_snapshot_sq.c.portfolio_id == Portfolio.id)
                    .where(*active_filters, non_zero_pnl_filter, effective_pnl_expr > my_pnl)
                )
                users_above = int(rank_result.scalar_one() or 0)
                rank = users_above + 1
                total_users = int(active_users or 0)
                percentile = (
                    round(((total_users - users_above) / total_users) * 100, 2)
                    if total_users > 0
                    else 0.0
                )
                my_position = {
                    "rank": rank,
                    "participants": total_users,
                    "percentile": percentile,
                    "pnl": float(round(my_pnl, 2)),
                    "pnl_percent": float(round(_to_decimal(my_row.effective_pnl_percent), 2)),
                }

    return {
        "period": safe_period,
        "limit": safe_limit,
        "entries": winners,
        "winners": winners,
        "losers": losers,
        "my_position": my_position,
        "summary": {
            "active_users": int(active_users or 0),
            "profitable_users": int(profitable_users or 0),
            "losing_users": int(losing_users or 0),
            "total_pnl": float(round(_to_decimal(total_pnl_sum), 2)),
        },
        "data_source": "postgres_portfolios",
        "calculation_mode": "live_portfolio_snapshot",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
