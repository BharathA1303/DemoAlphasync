from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Numeric, Boolean, Date, DateTime, Index, text
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class SymbolMaster(Base):
    """Normalized symbol master table derived from Zebu symbol master files.
    Serves as single source of truth for exchange <-> token <-> trading symbol mapping.
    """

    __tablename__ = "symbol_master"

    exchange = Column(String(10), primary_key=True, nullable=False)
    token = Column(String(20), primary_key=True, nullable=False)
    symbol = Column(String(50), nullable=False)           # e.g. RELIANCE, NIFTY
    trading_symbol = Column(String(100), nullable=False)  # e.g. RELIANCE-EQ, NIFTY26SEP26C25000
    instrument_type = Column(String(20), nullable=False)   # EQ, INDEX, OPTSTK, OPTIDX, FUTSTK, FUTIDX, FUTCOM
    lot_size = Column(Integer, nullable=False, default=1)
    tick_size = Column(Numeric(10, 4), nullable=False, default=0.05)
    expiry = Column(Date, nullable=True)
    strike = Column(Numeric(12, 2), nullable=True)
    option_type = Column(String(2), nullable=True)        # CE, PE
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    synced_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("ix_symbol_master_symbol", "symbol", "exchange"),
        Index("ix_symbol_master_active", "is_active"),
        Index("ix_symbol_master_trading_symbol", "trading_symbol"),
    )

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "token": self.token,
            "symbol": self.symbol,
            "trading_symbol": self.trading_symbol,
            "instrument_type": self.instrument_type,
            "lot_size": self.lot_size,
            "tick_size": float(self.tick_size) if self.tick_size is not None else 0.05,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "strike": float(self.strike) if self.strike is not None else None,
            "option_type": self.option_type,
            "is_active": self.is_active,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
        }
