# models/user.py - User and admin management models with enhanced security and audit logging
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
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid = Column(String(128), unique=True, nullable=True, index=True)
    auth_provider = Column(
        String(30),
        default="firebase",
        nullable=False,
        server_default=text("'firebase'"),
    )
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(
        String(255), nullable=True
    )  # nullable — Firebase users have no password
    full_name = Column(String(100), nullable=False)
    is_verified = Column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    is_active = Column(
        Boolean, default=True, nullable=False, server_default=text("true")
    )
    virtual_capital = Column(
        Numeric(precision=16, scale=2), default=1000000.0, nullable=False
    )
    role = Column(
        String(20), default="user", nullable=False, server_default=text("'user'")
    )
    avatar_url = Column(String(500), nullable=True)
    phone = Column(String(20), nullable=True)

    # ── Admin hierarchy ────────────────────────────────────────────
    # "root" = super admin (only one, set via ROOT_ADMIN_EMAIL config)
    # "manage" = full user management access
    # "view_only" = read-only dashboard access
    admin_level = Column(
        String(20), nullable=True
    )
    admin_assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    admin_assigned_at = Column(DateTime(timezone=True), nullable=True)

    # ── Admin panel fields ───────────────────────────────────────────
    account_status = Column(
        String(30),
        default="pending_approval",
        nullable=False,
        server_default=text("'pending_approval'"),
    )
    access_expires_at = Column(DateTime(timezone=True), nullable=True)
    access_duration_days = Column(Integer, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    deactivation_reason = Column(String(500), nullable=True)

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

    # Relationships
    portfolio = relationship(
        "Portfolio", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    watchlists = relationship(
        "Watchlist", back_populates="user", cascade="all, delete-orphan"
    )
    futures_watchlists = relationship(
        "FuturesWatchlist", cascade="all, delete-orphan"
    )
    algo_strategies = relationship(
        "AlgoStrategy", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_users_role_active", "role", "is_active"),
        Index("ix_users_account_status", "account_status"),
    )


class TwoFactorAuth(Base):
    """Encrypted TOTP secrets for admin 2FA."""

    __tablename__ = "admin_totp_secrets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    secret_enc = Column(Text, nullable=False)  # AES-256-GCM encrypted TOTP secret
    is_enabled = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    backup_codes_enc = Column(Text, nullable=True)  # encrypted JSON array
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP"))


class AdminSession(Base):
    """Short-lived admin session tokens issued after 2FA verification."""

    __tablename__ = "admin_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_token = Column(String(256), unique=True, nullable=False, index=True)
    totp_verified = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    expires_at = Column(DateTime(timezone=True), nullable=False)


class UserSession(Base):
    """Track user device sessions for security visibility."""

    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_key = Column(String(64), unique=True, nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    first_seen_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_seen_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    is_active = Column(Boolean, default=True, nullable=False, server_default=text("true"))

    __table_args__ = (
        Index("ix_user_sessions_user_last_seen", "user_id", "last_seen_at"),
    )


class AdminAuditLog(Base):
    """Immutable log of every admin action for accountability."""

    __tablename__ = "admin_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action = Column(String(100), nullable=False)
    target_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("ix_audit_admin_user", "admin_user_id"),
        Index("ix_audit_created", "created_at"),
    )


class EmailNotificationLog(Base):
    """Track all emails sent for debugging and dedup."""

    __tablename__ = "email_notifications_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_type = Column(String(50), nullable=False)
    sent_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    status = Column(String(20), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_email_log_user_type", "user_id", "email_type"),
    )
