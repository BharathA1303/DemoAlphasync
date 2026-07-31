import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Set, Dict, List

from providers.base import MarketProvider, ProviderStatus, ProviderHealth, Quote
from services.delay_engine import DelayEngine
from database.connection import async_session_factory

logger = logging.getLogger(__name__)


class DelayedFeedProvider(MarketProvider):
    """MarketProvider implementation backed strictly by DelayEngine time-delayed reads.
    Guarantees no real-time leakage to user clients.
    """

    def __init__(self, settings=None):
        self._settings = settings
        self._status = ProviderStatus.DISCONNECTED
        self._subscribed_symbols: Set[str] = set()
        self._start_time: Optional[datetime] = None

    async def start(self) -> None:
        self._status = ProviderStatus.CONNECTED
        self._start_time = datetime.now(timezone.utc)
        logger.info("DelayedFeedProvider initialized and ready.")

    async def stop(self) -> None:
        self._status = ProviderStatus.DISCONNECTED
        logger.info("DelayedFeedProvider stopped.")

    async def subscribe(self, symbols: list[str]) -> None:
        for s in symbols:
            self._subscribed_symbols.add(s.upper())

    async def unsubscribe(self, symbols: list[str]) -> None:
        for s in symbols:
            self._subscribed_symbols.discard(s.upper())

    async def get_quote(self, symbol: str) -> Optional[dict]:
        clean_sym = symbol.upper()
        ex = "NSE"
        if "." in clean_sym:
            parts = clean_sym.split(".")
            clean_sym = parts[0]
            ex = "BSE" if parts[1] == "BO" else "NSE"

        async with async_session_factory() as session:
            raw_quote = await DelayEngine.get_delayed_quote(session, clean_sym, exchange=ex)
            if not raw_quote:
                return None

            price = raw_quote["price"]
            close = raw_quote["close"] or price
            change = price - close
            change_pct = (change / close * 100.0) if close > 0 else 0.0

            canonical_quote = Quote(
                symbol=symbol,
                name=clean_sym,
                price=price,
                change=change,
                change_percent=change_pct,
                open=raw_quote["open"],
                high=raw_quote["high"],
                low=raw_quote["low"],
                close=close,
                volume=raw_quote["volume"],
                exchange=ex,
                timestamp=raw_quote["delayed_as_of"],
            )
            return canonical_quote.to_dict()

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        res = {}
        for s in symbols:
            q = await self.get_quote(s)
            if q:
                res[s] = q
        return res

    async def health(self) -> ProviderHealth:
        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds() if self._start_time else 0.0
        return ProviderHealth(
            status=self._status,
            provider_name="DelayedFeedProvider (Zebu OAuth)",
            subscribed_symbols=len(self._subscribed_symbols),
            last_tick_at=datetime.now(timezone.utc).isoformat(),
            uptime_seconds=uptime,
        )

    def get_subscribed_symbols(self) -> set[str]:
        return set(self._subscribed_symbols)
