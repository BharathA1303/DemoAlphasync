"""
Auto Square-Off Worker — Closes MIS (intraday) positions at 3:20 PM IST.

Real brokers auto square-off intraday positions before market close.
Delivery (CNC) holdings are marked to the closing price and carried overnight.

Runs every 30 seconds, checks if it's past 15:20 IST, and closes MIS lots only.
"""

import asyncio
import logging
from datetime import datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_

from database.connection import async_session_factory
from models.order import Order
from models.portfolio import Portfolio, Holding
from services import market_data
from services.trading_engine import (
    _to_decimal,
    resolve_open_lots_from_orders,
    close_open_lots,
    mark_holding_to_market,
)
from engines.market_session import market_session, MarketState

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SQUAREOFF_TIME = time(15, 20)  # 3:20 PM IST


class AutoSquareOffWorker:
    """Closes MIS intraday positions at 3:20 PM IST; marks CNC to market."""

    def __init__(self):
        self._running = False
        self._squared_off_today = False
        self._last_date = None

    async def run(self):
        """Main loop — checks every 30s if square-off time has been reached."""
        self._running = True
        logger.info("Auto Square-Off Worker started (trigger: 15:20 IST)")

        while self._running:
            try:
                now = datetime.now(IST)
                today = now.date()

                if self._last_date != today:
                    self._squared_off_today = False
                    self._last_date = today

                state = market_session.get_current_state()
                if (
                    not self._squared_off_today
                    and state not in (MarketState.WEEKEND, MarketState.HOLIDAY)
                    and now.time() >= SQUAREOFF_TIME
                ):
                    await self._square_off_all()
                    self._squared_off_today = True

            except Exception as e:
                logger.error(f"Square-off worker error: {e}", exc_info=True)

            await asyncio.sleep(30)

    async def _square_off_all(self):
        """Square off MIS lots; mark CNC holdings to closing price."""
        logger.info("[SquareOff] 3:20 PM IST — Auto square-off triggered")

        async with async_session_factory() as db:
            try:
                result = await db.execute(select(Portfolio))
                portfolios = result.scalars().all()

                total_mis_closed = 0
                total_cnc_marked = 0
                total_cancelled_orders = 0

                for portfolio in portfolios:
                    user_id = portfolio.user_id

                    open_orders_result = await db.execute(
                        select(Order).where(
                            and_(
                                Order.user_id == user_id,
                                Order.product_type == "MIS",
                                Order.status.in_(["OPEN", "PENDING"]),
                            )
                        )
                    )
                    open_orders = open_orders_result.scalars().all()
                    if open_orders:
                        now_utc = datetime.now(timezone.utc)
                        for ord_ in open_orders:
                            ord_.status = "CANCELLED"
                            ord_.updated_at = now_utc
                            total_cancelled_orders += 1

                    holdings_result = await db.execute(
                        select(Holding).where(
                            and_(
                                Holding.portfolio_id == portfolio.id,
                                Holding.quantity != 0,
                            )
                        )
                    )
                    holdings = holdings_result.scalars().all()

                    for holding in holdings:
                        try:
                            quote = await market_data.get_system_quote_safe(
                                holding.symbol
                            )
                            close_price = _to_decimal(
                                quote["price"]
                                if quote and quote.get("price")
                                else float(
                                    holding.current_price or holding.avg_price
                                )
                            )

                            lots = await resolve_open_lots_from_orders(
                                db, user_id, holding.symbol
                            )
                            if not lots:
                                product_type = (
                                    "MIS"
                                    if abs(int(holding.quantity)) > 0
                                    else "CNC"
                                )
                                lots = [
                                    {
                                        "qty": abs(int(holding.quantity)),
                                        "product_type": product_type,
                                        "side": (
                                            "LONG"
                                            if holding.quantity > 0
                                            else "SHORT"
                                        ),
                                    }
                                ]

                            mis_lots = [
                                lot
                                for lot in lots
                                if lot.get("product_type") == "MIS"
                            ]
                            cnc_lots = [
                                lot
                                for lot in lots
                                if lot.get("product_type") == "CNC"
                            ]

                            if mis_lots:
                                results = await close_open_lots(
                                    db,
                                    user_id,
                                    holding.symbol,
                                    mis_lots,
                                    tag="SQUAREOFF",
                                    client_price=float(close_price),
                                    bypass_market_session=True,
                                )
                                if all(r.get("success") for r in results):
                                    total_mis_closed += 1
                                else:
                                    for r in results:
                                        if not r.get("success"):
                                            logger.warning(
                                                "[SquareOff] MIS close failed %s: %s",
                                                holding.symbol,
                                                r.get("error"),
                                            )

                            if cnc_lots:
                                await mark_holding_to_market(
                                    db, holding, close_price
                                )
                                total_cnc_marked += 1

                        except Exception as e:
                            logger.error(
                                f"[SquareOff] Failed {holding.symbol}: {e}",
                                exc_info=True,
                            )

                    try:
                        from strategies.zeroloss.manager import zeroloss_manager

                        controller = zeroloss_manager.get_controller(user_id)
                        if controller.get_active_positions():
                            controller.clear_active_positions()
                    except Exception:
                        pass

                await db.commit()
                logger.info(
                    "[SquareOff] Complete — MIS closed: %s, CNC marked: %s, "
                    "MIS orders cancelled: %s",
                    total_mis_closed,
                    total_cnc_marked,
                    total_cancelled_orders,
                )

            except Exception as e:
                await db.rollback()
                logger.error(f"[SquareOff] Transaction failed: {e}", exc_info=True)

    async def stop(self):
        self._running = False

    def get_stats(self):
        return {
            "squared_off_today": self._squared_off_today,
            "squareoff_time": str(SQUAREOFF_TIME),
        }


auto_squareoff_worker = AutoSquareOffWorker()
