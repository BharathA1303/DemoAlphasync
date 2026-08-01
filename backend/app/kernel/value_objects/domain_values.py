from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CanonicalSymbol:
    """Canonical representation of a market instrument symbol.
    Format: EXCHANGE:SEGMENT:TICKER (e.g. NSE:EQ:RELIANCE)
    """

    exchange: str
    segment: str
    ticker: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", self.exchange.strip().upper())
        object.__setattr__(self, "segment", self.segment.strip().upper())
        object.__setattr__(self, "ticker", self.ticker.strip().upper())

        if not self.exchange or not self.segment or not self.ticker:
            raise ValueError(f"Invalid CanonicalSymbol fields: {self}")

    @classmethod
    def parse(cls, raw: str) -> "CanonicalSymbol":
        parts = str(raw or "").split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid canonical symbol format: '{raw}'. Expected EXCHANGE:SEGMENT:TICKER")
        return cls(exchange=parts[0], segment=parts[1], ticker=parts[2])

    def __str__(self) -> str:
        return f"{self.exchange}:{self.segment}:{self.ticker}"


@dataclass(frozen=True)
class Money:
    """Monetary value representation."""

    amount: Decimal
    currency: str = "INR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", Decimal(str(self.amount)))

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot add different currencies: {self.currency} vs {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract different currencies: {self.currency} vs {other.currency}")
        return Money(amount=self.amount - other.amount, currency=self.currency)


@dataclass(frozen=True)
class Price:
    """Instrument unit price."""

    value: Decimal

    def __post_init__(self) -> None:
        dec_val = Decimal(str(self.value))
        if dec_val < Decimal("0"):
            raise ValueError("Price cannot be negative")
        object.__setattr__(self, "value", dec_val)

    def __float__(self) -> float:
        return float(self.value)


@dataclass(frozen=True)
class Quantity:
    """Trade or position share volume."""

    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("Quantity must be strictly positive (> 0)")

    def __int__(self) -> int:
        return self.value
