# validator.py - Validation and symbol normalization for downloaded tick data
import logging
from typing import Dict, Any, Optional
from decimal import Decimal

logger = logging.getLogger(__name__)

class Validator:
    """
    Validates and normalizes raw tick data from the vendor
    before inserting it into the PostgreSQL Tick Store.
    """

    def normalize_tick(self, raw_tick: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalize raw tick data from the vendor into our internal format.
        Checks for required fields, filters out bad ticks (negative prices, etc.),
        and formats symbol names.
        """
        symbol = str(raw_tick.get("symbol", "")).strip().upper()
        if not symbol:
            return None

        try:
            price = float(raw_tick.get("price", 0))
            if price <= 0:
                return None
            
            # Map exchanges
            exchange = str(raw_tick.get("exchange", "NSE")).strip().upper()

            return {
                "symbol": symbol,
                "timestamp": raw_tick.get("timestamp"),
                "price": Decimal(str(price)),
                "volume": int(raw_tick.get("volume", 0)),
                "oi": int(raw_tick.get("oi", 0)) if raw_tick.get("oi") else None,
                "bid_price": Decimal(str(raw_tick["bid_price"])) if raw_tick.get("bid_price") else None,
                "ask_price": Decimal(str(raw_tick["ask_price"])) if raw_tick.get("ask_price") else None,
                "bid_qty": int(raw_tick["bid_qty"]) if raw_tick.get("bid_qty") else None,
                "ask_qty": int(raw_tick["ask_qty"]) if raw_tick.get("ask_qty") else None,
                "exchange": exchange,
            }
        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Validator: Skipping invalid tick for {symbol}: {e}")
            return None

validator = Validator()
