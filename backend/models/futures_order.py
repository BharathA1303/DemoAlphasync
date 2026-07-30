"""
FuturesOrder Model — Simulated futures trading orders (local DB only, never sent to broker).
"""

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
    return datetime.now(timezone.utc)


class FuturesOrder(Base):
    """Simulated futures order — stored in local DB only, NEVER sent to broker."""

    __tablename__ = "futures_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_symbol = Column(
        String(50), nullable=False, index=True
    )  # e.g., "RELIANCE25MAR2026FUT"
    order_type = Column(
        String(20), nullable=False
    )  # MARKET, LIMIT, STOP_LOSS, STOP_LOSS_LIMIT
    side = Column(String(4), nullable=False)  # BUY, SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(precision=14, scale=2), nullable=True)  # For limit orders
    trigger_price = Column(
        Numeric(precision=14, scale=2), nullable=True
    )  # For stop-loss orders

    # Execution details
    status = Column(
        String(20),
        default="PENDING",
        nullable=False,
        server_default=text("'PENDING'"),
    )  # PENDING, OPEN, FILLED, CANCELLED, EXPIRED, REJECTED
    filled_quantity = Column(
        Integer, default=0, nullable=False, server_default=text("0")
    )
    filled_price = Column(Numeric(precision=14, scale=2), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
    executed_at = Column(DateTime(timezone=True), nullable=True)

    # Optional fields
    tag = Column(String(50), nullable=True)  # User-provided label
    rejection_reason = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_futures_orders_user_contract", "user_id", "contract_symbol"),
        Index("ix_futures_orders_user_status", "user_id", "status"),
        CheckConstraint("quantity > 0", name="ck_futures_quantity_positive"),
        CheckConstraint(
            "filled_quantity >= 0", name="ck_futures_filled_quantity_nonneg"
        ),
        CheckConstraint(
            "filled_quantity <= quantity", name="ck_futures_filled_quantity_lteq_quantity"
        ),
    )


class FuturesPosition(Base):
    """User's open position in a futures contract (simulated)."""

    __tablename__ = "futures_positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_symbol = Column(String(50), nullable=False, index=True)

    # Position details
    quantity = Column(Integer, nullable=False)  # Net position (positive=long, negative=short)
    avg_entry_price = Column(Numeric(precision=14, scale=2), nullable=False)
    current_price = Column(Numeric(precision=14, scale=2), nullable=False)

    # Profit/Loss tracking
    unrealized_pnl = Column(Numeric(precision=14, scale=2), default=0, nullable=False)
    realized_pnl = Column(Numeric(precision=14, scale=2), default=0, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_futures_positions_user_contract", "user_id", "contract_symbol"),
    )
