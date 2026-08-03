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

    async def get_historical_data(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> list:
        from market_data.replay.delayed_candle_builder import DelayedCandleBuilder
        from datetime import timedelta

        clean_sym = symbol.upper()
        ex = "NSE"
        if "." in clean_sym:
            parts = clean_sym.split(".")
            clean_sym = parts[0]
            ex = "BSE" if parts[1] == "BO" else "NSE"

        async with async_session_factory() as session:
            delay_seconds = await DelayEngine.get_current_delay_seconds(session)
            cutoff = DelayEngine.get_visible_cutoff(delay_seconds)
            start_time = cutoff - timedelta(days=30)
            ticks = await DelayEngine.fetch_raw_ticks_until_cutoff(
                session, clean_sym, ex, start_time=start_time, delay_seconds=delay_seconds
            )

            if not ticks:
                # If raw_ticks database has no ticks stored yet, fall back to ReplayProvider's initial candle generator
                from providers.replay_provider import ReplayProvider
                replay = ReplayProvider()
                return await replay.get_historical_data(symbol, period=period, interval=interval)

            tf_mins = 1
            if interval == "5m":
                tf_mins = 5
            elif interval == "15m":
                tf_mins = 15
            elif interval in ("1h", "60m"):
                tf_mins = 60
            elif interval == "1d":
                tf_mins = 1440

            return DelayedCandleBuilder.build_candles_from_ticks(ticks, timeframe_minutes=tf_mins)

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

