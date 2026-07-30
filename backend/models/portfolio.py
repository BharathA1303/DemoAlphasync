import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    from market_data.replay.simulation_clock import simulation_clock
    return simulation_clock.now()


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    total_invested = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    current_value = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    available_capital = Column(
        Numeric(precision=16, scale=2), default=1000000.0, nullable=False
    )
    total_pnl = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    total_pnl_percent = Column(
        Numeric(precision=10, scale=4),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    user = relationship("User", back_populates="portfolio")
    holdings = relationship(
        "Holding", back_populates="portfolio", cascade="all, delete-orphan"
    )


class Holding(Base):
    __tablename__ = "holdings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol = Column(String(30), nullable=False)
    exchange = Column(
        String(10), default="NSE", nullable=False, server_default=text("'NSE'")
    )
    company_name = Column(String(200), nullable=True)
    quantity = Column(Integer, nullable=False)
    avg_price = Column(Numeric(precision=14, scale=2), nullable=False)
    current_price = Column(
        Numeric(precision=14, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    invested_value = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    current_value = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    pnl = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    pnl_percent = Column(
        Numeric(precision=10, scale=4),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    product_type = Column(
        String(10), default="CNC", nullable=False, server_default=text("'CNC'")
    )  # CNC (Delivery), MIS (Intraday)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    portfolio = relationship("Portfolio", back_populates="holdings")

    __table_args__ = (
        Index("ix_holdings_portfolio_symbol_product", "portfolio_id", "symbol", "product_type", unique=True),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    symbol = Column(String(30), nullable=False, index=True)
    transaction_type = Column(String(10), nullable=False)  # BUY, SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(precision=14, scale=2), nullable=False)
    total_value = Column(Numeric(precision=16, scale=2), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (Index("ix_transactions_user_created", "user_id", "created_at"),)
