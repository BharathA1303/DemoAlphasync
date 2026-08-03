from datetime import datetime, timezone
from sqlalchemy import Column, String, BigInteger, Numeric, DateTime, Index, text
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RawTick(Base):
    """PostgreSQL storage for raw intraday ticks (equity & indices).
    Ingestion writes real feed timestamps (real_timestamp), while DelayEngine
    queries with `real_timestamp <= now() - delay_seconds`.
    """

    __tablename__ = "raw_ticks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange = Column(String(10), nullable=False)
    token = Column(String(20), nullable=False)
    symbol = Column(String(50), nullable=False)
    ltp = Column(Numeric(12, 4), nullable=False)
    open = Column(Numeric(12, 4), nullable=True)
    high = Column(Numeric(12, 4), nullable=True)
    low = Column(Numeric(12, 4), nullable=True)
    close = Column(Numeric(12, 4), nullable=True)
    volume = Column(BigInteger, nullable=True)
    best_bid = Column(Numeric(12, 4), nullable=True)
    best_ask = Column(Numeric(12, 4), nullable=True)
    real_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    ingested_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("ix_raw_ticks_lookup", "exchange", "token", "real_timestamp"),
        Index("ix_raw_ticks_symbol_lookup", "symbol", "exchange", "real_timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "exchange": self.exchange,
            "token": self.token,
            "symbol": self.symbol,
            "ltp": float(self.ltp),
            "open": float(self.open) if self.open is not None else None,
            "high": float(self.high) if self.high is not None else None,
            "low": float(self.low) if self.low is not None else None,
            "close": float(self.close) if self.close is not None else None,
            "volume": self.volume,
            "best_bid": float(self.best_bid) if self.best_bid is not None else None,
            "best_ask": float(self.best_ask) if self.best_ask is not None else None,
            "real_timestamp": self.real_timestamp.isoformat() if self.real_timestamp else None,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
        }
