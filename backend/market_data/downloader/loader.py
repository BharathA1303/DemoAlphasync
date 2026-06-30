# loader.py - Daily loader script to download, validate, and store ticks
import logging
from datetime import datetime
from typing import List

from database.connection import async_session_factory
from models.historical_ticks import HistoricalTick
from market_data.downloader.vendor_client import vendor_client
from market_data.downloader.validator import validator

logger = logging.getLogger(__name__)

class Loader:
    """
    Orchestrates the daily data acquisition pipeline:
      1. Downloads ticks from VendorClient
      2. Validates and normalizes them using Validator
      3. Saves them in batch into the PostgreSQL Historical Tick Store
    """

    async def run_daily_ingestion(self, date: datetime, symbols: List[str]) -> int:
        """
        Run ingestion for a list of symbols on a given date.
        Returns the number of successfully ingested ticks.
        """
        total_ingested = 0
        
        async with async_session_factory() as db:
            for symbol in symbols:
                try:
                    # 1. Download
                    raw_ticks = await vendor_client.fetch_ticks_for_date(date, symbol)
                    if not raw_ticks:
                        continue
                    
                    # 2. Validate & Normalize
                    valid_ticks = []
                    for raw in raw_ticks:
                        norm = validator.normalize_tick(raw)
                        if norm:
                            valid_ticks.append(
                                HistoricalTick(
                                    symbol=norm["symbol"],
                                    timestamp=norm["timestamp"],
                                    price=norm["price"],
                                    volume=norm["volume"],
                                    oi=norm["oi"],
                                    bid_price=norm["bid_price"],
                                    ask_price=norm["ask_price"],
                                    bid_qty=norm["bid_qty"],
                                    ask_qty=norm["ask_qty"],
                                    exchange=norm["exchange"],
                                )
                            )
                    
                    # 3. Store in batch
                    if valid_ticks:
                        db.add_all(valid_ticks)
                        await db.commit()
                        total_ingested += len(valid_ticks)
                        logger.info(f"Loader: Successfully ingested {len(valid_ticks)} ticks for {symbol}")
                except Exception as e:
                    await db.rollback()
                    logger.error(f"Loader: Ingestion failed for {symbol}: {e}")
                    
        return total_ingested

loader = Loader()
