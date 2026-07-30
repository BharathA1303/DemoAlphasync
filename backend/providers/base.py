"""
MarketProvider — Abstract base class for all market data providers.

Every provider MUST implement:
    - start()          → Connect / initialize the data source
    - stop()           → Gracefully disconnect / clean up
    - subscribe()      → Request price updates for symbols
    - unsubscribe()    → Stop receiving price updates for symbols
    - get_quote()      → Fetch latest quote for a single symbol
    - get_batch_quotes() → Fetch quotes for multiple symbols
    - health()         → Return provider health / connectivity status

Providers are NOT responsible for emitting EventBus events.
That is handled by the MarketDataWorker which consumes the provider.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ProviderStatus(Enum):
    """Connection status of a market data provider."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class Quote:
    """
    Canonical quote object returned by all providers.

    Providers map their raw tick data into this structure so the rest
    of the system never touches provider-specific formats.
    """

    symbol: str
    name: str = ""
    price: float = 0.0
    change: float = 0.0
    change_percent: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0  # previous close
    volume: int = 0
    market_cap: float = 0.0
    pe_ratio: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    exchange: str = "NSE"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        """Serialize to dict (compatible with existing quote format)."""
        return {
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "change": round(self.change, 2),
            "change_percent": round(self.change_percent, 2),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "market_cap": self.market_cap,
            "pe_ratio": self.pe_ratio,
            "week_52_high": self.week_52_high,
            "week_52_low": self.week_52_low,
            "exchange": self.exchange,
            "timestamp": self.timestamp,
        }


@dataclass
class ProviderHealth:
    """Health status returned by provider.health()."""

    status: ProviderStatus
    provider_name: str
    subscribed_symbols: int = 0
    last_tick_at: Optional[str] = None
    uptime_seconds: float = 0.0
    reconnect_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "provider_name": self.provider_name,
            "subscribed_symbols": self.subscribed_symbols,
            "last_tick_at": self.last_tick_at,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "reconnect_count": self.reconnect_count,
            "error": self.error,
        }


class MarketProvider(ABC):
    """
    Abstract interface for market data providers.

    Lifecycle:
        provider = SomeProvider(settings)
        await provider.start()
        await provider.subscribe(["RELIANCE.NS", "TCS.NS"])
        quote = await provider.get_quote("RELIANCE.NS")
        await provider.unsubscribe(["TCS.NS"])
        await provider.stop()
    """

    @abstractmethod
    async def start(self) -> None:
        """Initialize connections and start receiving data."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully disconnect and release resources."""
        ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to price updates for the given symbols."""
        ...

    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from price updates for the given symbols."""
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> Optional[dict]:
        """
        Get latest quote for a symbol.

        Returns a dict matching the existing quote format used by
        market_data.get_quote() for backward compatibility.
        Returns None if the symbol is not available.
        """
        ...

    @abstractmethod
    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """
        Get latest quotes for multiple symbols.

        Returns { symbol: quote_dict } for each available symbol.
        """
        ...

    async def get_historical_data(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> list:
        """
        Get historical OHLCV candle data for a symbol.

        Returns a list of dicts with keys: time, open, high, low, close, volume.
        Default implementation raises NotImplementedError — override in
        providers that support historical queries.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support historical data"
        )

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Return current provider health status."""
        ...

    @abstractmethod
    def get_subscribed_symbols(self) -> set[str]:
        """Return the set of currently subscribed symbols."""
        ...
