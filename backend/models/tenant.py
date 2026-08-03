# models/tenant.py - Tenant (Institution) & 7-Tier Tenant-Scoped RBAC models for AlphaSync Campus
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    DateTime,
    ForeignKey,
    Index,
    Enum as SQLEnum,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class TenantRole(str, enum.Enum):
    """7-tier tenant role hierarchy as specified in AlphaSync Campus design docs."""
    SUPER_ADMIN = "super_admin"
    INSTITUTION_ADMIN = "institution_admin"
    DEPT_HEAD = "dept_head"
    FACULTY = "faculty"
    TA = "ta"
    STUDENT = "student"
    GUEST = "guest"


class Tenant(Base):
    """An institutional tenant (e.g. University, Academy, College)."""
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    domain = Column(String(255), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False, server_default=text("true"))
    max_users = Column(Integer, default=1000, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    tenant_roles = relationship("UserTenantRole", back_populates="tenant", cascade="all, delete-orphan")


class UserTenantRole(Base):
    """Maps a user identity to a tenant-scoped role.
    One identity can hold different roles across different institutions/tenants.
    """
    __tablename__ = "user_tenant_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SQLEnum(TenantRole), nullable=False, default=TenantRole.STUDENT, index=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="tenant_roles")
    user = relationship("User", back_populates="tenant_roles")

    __table_args__ = (
        Index("idx_user_tenant_role_unique", "tenant_id", "user_id", "role", unique=True),
    )
