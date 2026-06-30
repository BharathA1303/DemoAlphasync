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
    CheckConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    from core.simulation_clock import simulation_clock
    return simulation_clock.now()


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol = Column(String(30), nullable=False, index=True)
    exchange = Column(
        String(10), default="NSE", nullable=False, server_default=text("'NSE'")
    )
    order_type = Column(
        String(20), nullable=False
    )  # MARKET, LIMIT, STOP_LOSS, TAKE_PROFIT, BRACKET, STOP_LOSS_LIMIT
    side = Column(String(4), nullable=False)  # BUY, SELL
    product_type = Column(
        String(10), default="CNC", nullable=False, server_default=text("'CNC'")
    )  # CNC (Delivery), MIS (Intraday), NRML (F&O)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(precision=14, scale=2), nullable=True)  # For limit orders
    trigger_price = Column(
        Numeric(precision=14, scale=2), nullable=True
    )  # For stop-loss
    take_profit_price = Column(
        Numeric(precision=14, scale=2), nullable=True
    )  # For bracket take-profit leg
    filled_quantity = Column(
        Integer, default=0, nullable=False, server_default=text("0")
    )
    filled_price = Column(Numeric(precision=14, scale=2), nullable=True)
    status = Column(
        String(20), default="PENDING", nullable=False, server_default=text("'PENDING'")
    )
    rejection_reason = Column(String(500), nullable=True)
    tag = Column(String(30), nullable=True)  # "ZEROLOSS", "ALGO", or null for manual
    idempotency_key = Column(String(100), nullable=True, index=True)
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
    executed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="orders")

    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_order_side"),
        CheckConstraint(
            "order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS', 'TAKE_PROFIT', 'BRACKET', 'STOP_LOSS_LIMIT')",
            name="ck_order_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'OPEN', 'FILLED', 'PARTIALLY_FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED')",
            name="ck_order_status",
        ),
        CheckConstraint("quantity > 0", name="ck_order_qty_positive"),
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_user_created", "user_id", "created_at"),
    )
