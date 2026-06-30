import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
    Text,
    Index,
    CheckConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class AlgoStrategy(Base):
    __tablename__ = "algo_strategies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    strategy_type = Column(
        String(50), nullable=False
    )  # SMA_CROSSOVER, RSI, MACD, CUSTOM
    symbol = Column(String(30), nullable=False)
    exchange = Column(
        String(10), default="NSE", nullable=False, server_default=text("'NSE'")
    )
    parameters = Column(JSONB, nullable=True)
    is_active = Column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    max_position_size = Column(
        Integer, default=100, nullable=False, server_default=text("100")
    )
    stop_loss_percent = Column(
        Numeric(precision=6, scale=2), default=2.0, nullable=False
    )
    take_profit_percent = Column(
        Numeric(precision=6, scale=2), default=5.0, nullable=False
    )
    total_trades = Column(Integer, default=0, nullable=False, server_default=text("0"))
    total_pnl = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    win_rate = Column(
        Numeric(precision=6, scale=2),
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

    user = relationship("User", back_populates="algo_strategies")
    trades = relationship(
        "AlgoTrade", back_populates="strategy", cascade="all, delete-orphan"
    )
    logs = relationship(
        "AlgoLog", back_populates="strategy", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_algo_user_active", "user_id", "is_active"),)


class AlgoTrade(Base):
    __tablename__ = "algo_trades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("algo_strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol = Column(String(30), nullable=False)
    side = Column(String(4), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(precision=14, scale=2), nullable=False)
    pnl = Column(
        Numeric(precision=16, scale=2),
        default=0.0,
        nullable=False,
        server_default=text("0"),
    )
    signal = Column(String(50), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    strategy = relationship("AlgoStrategy", back_populates="trades")

    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_algo_trade_side"),
        Index("ix_algo_trades_strategy_created", "strategy_id", "created_at"),
    )


class AlgoLog(Base):
    __tablename__ = "algo_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("algo_strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    level = Column(
        String(10), default="INFO", nullable=False, server_default=text("'INFO'")
    )
    message = Column(Text, nullable=False)
    data = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    strategy = relationship("AlgoStrategy", back_populates="logs")

    __table_args__ = (
        Index("ix_algo_logs_strategy_created", "strategy_id", "created_at"),
    )
