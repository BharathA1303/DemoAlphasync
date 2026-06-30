"""
BrokerAccount — per-user broker connection storage (PostgreSQL).

Stores ONLY the minimum data needed to authenticate a market-data
WebSocket session.  No demat details, no order-placement credentials.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broker = Column(
        String(32), nullable=False, default="zebu", server_default=text("'zebu'")
    )
    broker_user_id = Column(String(128), nullable=True)
    display_name = Column(String(100), nullable=True)

    # Encrypted tokens — see services/broker_crypto.py
    access_token_enc = Column(Text, nullable=True)
    refresh_token_enc = Column(Text, nullable=True)

    token_expiry = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(
        Boolean, default=True, nullable=False, server_default=text("true")
    )
    extra_data_enc = Column(Text, nullable=True)

    # User-supplied broker app credentials (API key/secret, vendor code),
    # encrypted JSON — independent of the session token above. Saved once,
    # editable later, reused on every reconnect/refresh so the user never
    # has to re-type their app credentials. See services/broker_crypto.py.
    credentials_enc = Column(Text, nullable=True)

    connected_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    user = relationship("User", backref="broker_accounts")

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "broker", name="uq_user_broker"),
        Index("ix_broker_active", "broker", "is_active"),
    )

    def __repr__(self) -> str:
        uid = str(self.user_id)[:8] if self.user_id else "?"
        return (
            f"<BrokerAccount user={uid} broker={self.broker} active={self.is_active}>"
        )
