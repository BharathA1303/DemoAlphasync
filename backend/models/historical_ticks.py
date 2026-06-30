# historical_ticks.py - Database model for historical ticks
from sqlalchemy import Column, String, Integer, Numeric, DateTime, Index, text
from database.connection import Base


class HistoricalTick(Base):
    __tablename__ = "historical_ticks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(30), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    price = Column(Numeric(precision=14, scale=2), nullable=False)
    volume = Column(Integer, default=0, nullable=False)
    oi = Column(Integer, nullable=True)
    bid_price = Column(Numeric(precision=14, scale=2), nullable=True)
    ask_price = Column(Numeric(precision=14, scale=2), nullable=True)
    bid_qty = Column(Integer, nullable=True)
    ask_qty = Column(Integer, nullable=True)
    exchange = Column(String(10), default="NSE", nullable=False, server_default=text("'NSE'"))

    __table_args__ = (
        Index("ix_historical_ticks_symbol_timestamp", "symbol", "timestamp"),
        Index("ix_historical_ticks_timestamp", "timestamp"),
    )
