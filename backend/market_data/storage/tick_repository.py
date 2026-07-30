# tick_repository.py - Database operations for historical ticks
import logging
from datetime import datetime
from typing import List
from decimal import Decimal

from sqlalchemy import select, and_
from database.connection import async_session_factory
from models.historical_ticks import HistoricalTick

logger = logging.getLogger(__name__)

class TickRepository:
    """
    Handles retrieval of tick-by-tick market data from PostgreSQL.
    Used by the Replay Buffer Loader to load ticks in chunks.
    """

    async def get_ticks_for_range(
        self, 
        start_time: datetime, 
        end_time: datetime, 
        symbols: List[str] = None
    ) -> List[dict]:
        """
        Fetch all ticks between start_time and end_time (inclusive).
        Optionally filter by a list of symbols.
        Returns a list of dicts ordered chronologically.
        """
        async with async_session_factory() as db:
            try:
                stmt = select(HistoricalTick).where(
                    and_(
                        HistoricalTick.timestamp >= start_time,
                        HistoricalTick.timestamp <= end_time
                    )
                )
                if symbols:
                    clean_symbols = [str(s).strip().upper() for s in symbols if s]
                    if clean_symbols:
                        stmt = stmt.where(HistoricalTick.symbol.in_(clean_symbols))

                stmt = stmt.order_by(HistoricalTick.timestamp.asc())
                res = await db.execute(stmt)
                ticks = res.scalars().all()
                
                return [
                    {
                        "symbol": t.symbol,
                        "timestamp": t.timestamp,
                        "price": float(t.price),
                        "volume": t.volume,
                        "oi": t.oi or 0,
                        "bid_price": float(t.bid_price) if t.bid_price else None,
                        "ask_price": float(t.ask_price) if t.ask_price else None,
                        "bid_qty": t.bid_qty or 0,
                        "ask_qty": t.ask_qty or 0,
                        "exchange": t.exchange,
                    }
                    for t in ticks
                ]
            except Exception as e:
                logger.error(f"TickRepository: Failed to fetch ticks: {e}", exc_info=True)
                return []

    async def get_available_dates(self) -> List[datetime]:
        """
        Get all unique dates that have tick data stored in the database.
        """
        from sqlalchemy import func
        async with async_session_factory() as db:
            try:
                stmt = select(func.date(HistoricalTick.timestamp)).distinct()
                res = await db.execute(stmt)
                dates = res.scalars().all()
                return [
                    datetime.combine(d, datetime.min.time())
                    for d in dates
                    if d
                ]
            except Exception as e:
                logger.error(f"TickRepository: Failed to fetch available dates: {e}")
                return []

tick_repository = TickRepository()
