import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.raw_ticks import RawTick
from models.symbol_master import SymbolMaster
from models.data_feed_config import DataFeedConfig

logger = logging.getLogger(__name__)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class DelayEngine:
    """Core Time-Delay Gate service.
    Enforces that no user endpoint, chart, quote, or paper trading query receives
    data newer than `now_utc() - feed_delay_seconds`.
    """

    @staticmethod
    def get_visible_cutoff(delay_seconds: int) -> datetime:
        return now_utc() - timedelta(seconds=max(0, delay_seconds))

    @classmethod
    async def get_current_delay_seconds(cls, session: AsyncSession) -> int:
        stmt = select(DataFeedConfig.feed_delay_seconds).limit(1)
        res = await session.execute(stmt)
        val = res.scalar_one_or_none()
        return val if val is not None else 300  # Default 5 min (300s)

    @classmethod
    async def get_delayed_quote(
        cls,
        session: AsyncSession,
        symbol: str,
        exchange: str = "NSE",
    ) -> dict:
        """Fetch latest tick for (symbol, exchange) visible as of cutoff (now - delay)."""
        delay_seconds = await cls.get_current_delay_seconds(session)
        cutoff = cls.get_visible_cutoff(delay_seconds)

        # 1. Query raw_ticks table for tick at or before cutoff
        stmt = (
            select(RawTick)
            .where(
                RawTick.symbol == symbol.upper(),
                RawTick.exchange == exchange.upper(),
                RawTick.real_timestamp <= cutoff,
            )
            .order_by(RawTick.real_timestamp.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        tick = res.scalar_one_or_none()

        if tick:
            return {
                "symbol": tick.symbol,
                "exchange": tick.exchange,
                "token": tick.token,
                "price": float(tick.ltp),
                "open": float(tick.open) if tick.open else float(tick.ltp),
                "high": float(tick.high) if tick.high else float(tick.ltp),
                "low": float(tick.low) if tick.low else float(tick.ltp),
                "close": float(tick.close) if tick.close else float(tick.ltp),
                "volume": tick.volume or 0,
                "bid": float(tick.best_bid) if tick.best_bid else float(tick.ltp),
                "ask": float(tick.best_ask) if tick.best_ask else float(tick.ltp),
                "delayed_as_of": cutoff.isoformat(),
                "real_timestamp": tick.real_timestamp.isoformat(),
                "delay_seconds": delay_seconds,
                "is_delayed": True,
            }

        # 2. Fallback: Lookup symbol_master for base info
        sm_stmt = (
            select(SymbolMaster)
            .where(SymbolMaster.symbol == symbol.upper(), SymbolMaster.exchange == exchange.upper())
            .limit(1)
        )
        sm_res = await session.execute(sm_stmt)
        sm = sm_res.scalar_one_or_none()

        # Determine realistic fallback price matching real stock/index prices
        sym_clean = symbol.upper().replace(".NS", "").replace(".BO", "").replace("NSE:EQ:", "").replace("BSE:EQ:", "").strip()
        default_price = 1000.0
        if sym_clean in ("NIFTY", "^NSEI", "NIFTY50", "NSE:IDX:NIFTY50"):
            default_price = 24600.0
        elif sym_clean in ("BANKNIFTY", "^NSEBANK", "NSE:IDX:BANKNIFTY"):
            default_price = 57700.0
        elif sym_clean in ("FINNIFTY", "NSE:IDX:FINNIFTY"):
            default_price = 24100.0
        elif sym_clean in ("SENSEX", "^BSESN", "BSE:IDX:SENSEX"):
            default_price = 80200.0
        else:
            try:
                from data_layer.ingestion.nse_bhavcopy import _NSE_MOCK_ANCHORS
                if sym_clean in _NSE_MOCK_ANCHORS:
                    default_price = float(_NSE_MOCK_ANCHORS[sym_clean][0])
            except Exception:
                pass

        return {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "token": sm.token if sm else "0",
            "price": default_price,
            "open": default_price,
            "high": default_price,
            "low": default_price,
            "close": default_price,
            "volume": 0,
            "bid": default_price,
            "ask": default_price,
            "delayed_as_of": cutoff.isoformat(),
            "real_timestamp": cutoff.isoformat(),
            "delay_seconds": delay_seconds,
            "is_delayed": True,
            "is_fallback": True,
        }

    @classmethod
    async def fetch_raw_ticks_until_cutoff(
        cls,
        session: AsyncSession,
        symbol: str,
        exchange: str,
        start_time: datetime,
        delay_seconds: int,
    ) -> List[RawTick]:
        cutoff = cls.get_visible_cutoff(delay_seconds)
        stmt = (
            select(RawTick)
            .where(
                RawTick.symbol == symbol.upper(),
                RawTick.exchange == exchange.upper(),
                RawTick.real_timestamp >= start_time,
                RawTick.real_timestamp <= cutoff,
            )
            .order_by(RawTick.real_timestamp.asc())
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())
