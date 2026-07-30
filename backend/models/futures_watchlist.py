"""
FuturesWatchlist Models — Futures contract watchlists (separate from equity watchlists).
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class FuturesWatchlist(Base):
    __tablename__ = "futures_watchlists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False, default="My Futures Watchlist")
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

    user = relationship("User", foreign_keys=[user_id])
    items = relationship(
        "FuturesWatchlistItem",
        back_populates="watchlist",
        cascade="all, delete-orphan",
    )


class FuturesWatchlistItem(Base):
    __tablename__ = "futures_watchlist_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchlist_id = Column(
        UUID(as_uuid=True),
        ForeignKey("futures_watchlists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_symbol = Column(
        String(50), nullable=False
    )  # e.g., "NIFTY25MAR2026FUT", "RELIANCE25MAR2026FUT"
    added_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    watchlist = relationship("FuturesWatchlist", back_populates="items")

    __table_args__ = (
        Index(
            "ix_futures_watchlist_items_unique",
            "watchlist_id",
            "contract_symbol",
            unique=True,
        ),
    )
