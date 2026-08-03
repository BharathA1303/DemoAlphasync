# models/auth.py - Refresh Tokens & Time-Boxed Audited Impersonation Sessions
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RefreshToken(Base):
    """Rotating refresh token with server-side revocation capability."""
    __tablename__ = "auth_refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    is_revoked = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))


class ImpersonationSession(Base):
    """Time-boxed (max 30 min), reason-coded, fully audited admin impersonation session."""
    __tablename__ = "auth_impersonation_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    admin_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason_code = Column(String(100), nullable=False)  # e.g. "SUPPORT_TICKET_1234", "DEBUG_PERMISSION_ISSUE"
    read_only = Column(Boolean, default=True, nullable=False, server_default=text("true"))
    is_active = Column(Boolean, default=True, nullable=False, server_default=text("true"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    ended_at = Column(DateTime(timezone=True), nullable=True)
