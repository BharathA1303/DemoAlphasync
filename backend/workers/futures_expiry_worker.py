"""
Futures Expiry Settlement Worker — Auto-settles expired futures positions.

Real broker behavior simulated:
- Positions in expired contracts are auto-closed at settlement price (last known LTP)
- Open orders on expired contracts are auto-cancelled
- Expired contract cleanup from active tracking
- Runs every 60 seconds, checks all positions against contract expiry dates

This worker ONLY affects futures positions/orders. Does NOT touch equity, options,
commodities, or any other module.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from database.connection import async_session_factory
from models.futures_order import FuturesOrder, FuturesPosition
from models.portfolio import Portfolio
from services import futures_service
from services.futures_contract_registry import futures_contract_registry
from core.event_bus import event_bus, Event, EventType

logger = logging.getLogger(__name__)

# Settlement runs at this interval
SETTLEMENT_CHECK_INTERVAL = 60  # seconds

# Grace period after expiry date before auto-settlement (allows for EOD settlement)
EXPIRY_GRACE_HOURS = 18  # Settle after 6 PM on expiry day (market closes 3:30 PM)


def _extract_expiry_from_symbol(contract_symbol: str) -> Optional[str]:
    """
    Extract expiry date from contract symbol using registry or pattern matching.
    Returns YYYY-MM-DD string or None.
    """
    import re

    # Try registry first
    contract = futures_contract_registry.get_contract(contract_symbol)
    if contract and contract.get("expiry_date"):
        return contract["expiry_date"]

    # Fallback: parse from symbol pattern (e.g., NIFTY29MAY26F)
    match = re.search(r"(\d{1,2})([A-Z]{3})(\d{2,4})", contract_symbol)
    if match:
        day, month, year = match.groups()
        for fmt in ("%d%b%y", "%d%b%Y"):
            try:
                dt = datetime.strptime(f"{day}{month}{year}", fmt)
                return dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

    return None


def _is_contract_expired(contract_symbol: str) -> bool:
    """
    Check if a contract has expired (past expiry date + grace period).
    Grace period ensures we don't settle before EOD on expiry day.
    """
    expiry_str = _extract_expiry_from_symbol(contract_symbol)
    if not expiry_str:
        return False

    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d")
        # Add grace period: settle after 6 PM IST on expiry day
        settlement_cutoff = expiry_date.replace(
            hour=12, minute=30, second=0  # 6 PM IST = 12:30 UTC
        )
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        return now_utc > settlement_cutoff
    except (ValueError, TypeError):
        return False


class FuturesExpirySettlementWorker:
    """
    Background worker that simulates real broker expiry settlement:

    1. Scans all open positions for expired contracts
    2. Settles positions at last known price (settlement price)
    3. Cancels open orders on expired contracts
    4. Releases margin back to portfolio
    5. Records realized PnL from settlement

    Settlement behavior matches real brokers:
    - LONG positions settled: PnL = (settlement_price - avg_entry) * qty
    - SHORT positions settled: PnL = (avg_entry - settlement_price) * qty
    - Margin is fully released
    - Position quantity set to 0
    """

    def __init__(self):
        self._running = False
        self._stats = {
            "checks": 0,
            "positions_settled": 0,
            "orders_cancelled": 0,
            "errors": 0,
        }

    async def run(self) -> None:
        """Main loop — runs alongside other workers."""
        self._running = True
        logger.info("Futures Expiry Settlement Worker started")

        # Initial delay to let other services initialize
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._settlement_sweep()
                self._stats["checks"] += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Expiry settlement sweep error: {e}", exc_info=True)
                self._stats["errors"] += 1

            await asyncio.sleep(SETTLEMENT_CHECK_INTERVAL)

        logger.info(f"Futures Expiry Settlement Worker stopped. Stats: {self._stats}")

    async def stop(self) -> None:
        self._running = False

    async def _settlement_sweep(self) -> None:
        """Scan all open positions and orders, settle expired ones."""
        async with async_session_factory() as db:
            try:
                # 1. Find all open positions
                pos_result = await db.execute(
                    select(FuturesPosition).where(FuturesPosition.quantity != 0)
                )
                open_positions = pos_result.scalars().all()

                # 2. Find all open/pending orders
                ord_result = await db.execute(
                    select(FuturesOrder).where(
                        FuturesOrder.status.in_(("OPEN", "PENDING"))
                    )
                )
                open_orders = ord_result.scalars().all()

                # 3. Check each position for expiry
                for position in open_positions:
                    if _is_contract_expired(position.contract_symbol):
                        await self._settle_position(db, position)

                # 4. Cancel orders on expired contracts
                for order in open_orders:
                    if _is_contract_expired(order.contract_symbol):
                        await self._cancel_expired_order(db, order)

                await db.commit()

            except Exception as e:
                await db.rollback()
                raise

    async def _settle_position(
        self, db: AsyncSession, position: FuturesPosition
    ) -> None:
        """
        Settle an expired position at the last known price.
        Simulates real broker settlement behavior.
        """
        contract_symbol = position.contract_symbol
        qty = int(position.quantity or 0)
        if qty == 0:
            return

        # Get settlement price (last known LTP from cache or live)
        settlement_price = await self._get_settlement_price(contract_symbol, position)
        if settlement_price is None or settlement_price <= 0:
            logger.warning(
                f"Cannot settle {contract_symbol} for user {position.user_id}: "
                f"no settlement price available. Using last known price."
            )
            settlement_price = position.current_price or position.avg_entry_price
            if not settlement_price or settlement_price <= 0:
                return

        settlement_price = Decimal(str(settlement_price))
        avg_entry = Decimal(str(position.avg_entry_price or 0))

        # Calculate settlement PnL
        if qty > 0:
            # LONG: profit if settlement > entry
            pnl = (settlement_price - avg_entry) * abs(qty)
        else:
            # SHORT: profit if settlement < entry
            pnl = (avg_entry - settlement_price) * abs(qty)

        # Release margin
        margin_held = (avg_entry * abs(qty)) * self._get_margin_rate(contract_symbol)

        # Update portfolio
        portfolio_result = await db.execute(
            select(Portfolio).where(Portfolio.user_id == position.user_id)
        )
        portfolio = portfolio_result.scalar_one_or_none()
        if portfolio:
            portfolio.available_capital = (
                (portfolio.available_capital or Decimal("0")) + margin_held + pnl
            )

        # Close position
        position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl
        position.unrealized_pnl = Decimal("0")
        position.current_price = settlement_price
        position.quantity = 0
        position.updated_at = datetime.now(timezone.utc)

        self._stats["positions_settled"] += 1

        logger.info(
            f"EXPIRY SETTLEMENT: {contract_symbol} | "
            f"User: {position.user_id} | "
            f"{'LONG' if qty > 0 else 'SHORT'} {abs(qty)} @ {avg_entry} | "
            f"Settlement: {settlement_price} | PnL: {pnl:+.2f}"
        )

        # Emit event for WS notification
        try:
            event_bus.emit_nowait(
                Event(
                    type=EventType.FUTURES_ORDER_FILLED,
                    user_id=str(position.user_id),
                    data={
                        "contract_symbol": contract_symbol,
                        "side": "SELL" if qty > 0 else "BUY",
                        "quantity": abs(qty),
                        "filled_price": float(settlement_price),
                        "status": "SETTLED",
                        "tag": "EXPIRY_SETTLEMENT",
                        "settlement": True,
                    },
                )
            )
        except Exception:
            pass

    async def _cancel_expired_order(
        self, db: AsyncSession, order: FuturesOrder
    ) -> None:
        """Cancel an open order on an expired contract."""
        order.status = "EXPIRED"
        order.updated_at = datetime.now(timezone.utc)
        order.rejection_reason = "Contract expired — auto-cancelled by settlement engine"

        self._stats["orders_cancelled"] += 1

        logger.info(
            f"EXPIRY CANCEL: Order {order.id} on {order.contract_symbol} "
            f"({order.side} {order.quantity} @ {order.price}) — contract expired"
        )

        try:
            event_bus.emit_nowait(
                Event(
                    type=EventType.FUTURES_ORDER_EXPIRED,
                    user_id=str(order.user_id),
                    data={
                        "order_id": str(order.id),
                        "contract_symbol": order.contract_symbol,
                        "reason": "contract_expired",
                    },
                )
            )
        except Exception:
            pass

    async def _get_settlement_price(
        self, contract_symbol: str, position: FuturesPosition
    ) -> Optional[Decimal]:
        """
        Get the settlement price for an expired contract.
        Priority: live quote > cached quote > last position price > entry price
        """
        try:
            quote = await futures_service.get_quote(contract_symbol)
            if quote:
                raw = quote.get("ltp") or quote.get("price") or quote.get("lp")
                if raw:
                    val = float(raw)
                    if val > 0:
                        return Decimal(str(val))
        except Exception:
            pass

        # Fallback to last known price on position
        if position.current_price and float(position.current_price) > 0:
            return Decimal(str(position.current_price))

        return None

    def _get_margin_rate(self, contract_symbol: str) -> Decimal:
        """Get the margin rate for a contract (used for margin release calculation)."""
        # Uses the same margin model as the trading service
        # Will be enhanced when SPAN margin is implemented
        from workers.futures_margin_engine import get_margin_fraction
        return get_margin_fraction(contract_symbol)

    def get_stats(self) -> dict:
        return dict(self._stats)


# Global worker instance
futures_expiry_worker = FuturesExpirySettlementWorker()
