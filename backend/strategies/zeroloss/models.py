"""
AlphaSync ZeroLoss — SQLAlchemy ORM Models (PostgreSQL).
"""

from datetime import datetime, date, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Numeric,
    DateTime,
    Date,
    ForeignKey,
    CheckConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ZeroLossSignal(Base):
    __tablename__ = "zeroloss_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    symbol = Column(String(30), nullable=False, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    confidence_score = Column(Numeric(precision=6, scale=2), nullable=False, default=0)
    direction = Column(String(10), nullable=False)  # LONG / SHORT / NO_TRADE
    entry_price = Column(Numeric(precision=14, scale=2), nullable=True)
    stop_loss = Column(Numeric(precision=14, scale=2), nullable=True)
    target = Column(Numeric(precision=14, scale=2), nullable=True)
    status = Column(
        String(15), nullable=False, default="WAITING", server_default=text("'WAITING'")
    )
    pnl = Column(
        Numeric(precision=16, scale=2),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint(
            "direction IN ('LONG', 'SHORT', 'NO_TRADE')",
            name="ck_zeroloss_direction",
        ),
        CheckConstraint(
            "status IN ('WAITING', 'ACTIVE', 'PROFIT', 'BREAKEVEN', 'STOPLOSS')",
            name="ck_zeroloss_status",
        ),
        Index("ix_zeroloss_signals_user_symbol_ts", "user_id", "symbol", "timestamp"),
    )


class ZeroLossPerformance(Base):
    __tablename__ = "zeroloss_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    date = Column(Date, nullable=False)
    total_trades = Column(Integer, nullable=False, default=0, server_default=text("0"))
    profit_trades = Column(Integer, nullable=False, default=0, server_default=text("0"))
    breakeven_trades = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    loss_trades = Column(Integer, nullable=False, default=0, server_default=text("0"))
    net_pnl = Column(
        Numeric(precision=16, scale=2),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_zeroloss_performance_user_date"),
        Index("ix_zeroloss_performance_user_date", "user_id", "date"),
    )


class ZeroLossRuntimeState(Base):
    """Durable on/off state so strategy survives page refreshes/process restarts."""

    __tablename__ = "zeroloss_runtime_state"

    user_id = Column(String(128), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (Index("ix_zeroloss_runtime_enabled", "enabled"),)
