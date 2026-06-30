import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    text,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class BugReport(Base):
    """Bug/Issue reports submitted by users"""
    __tablename__ = "bug_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Report Details
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, default="medium", server_default=text("'medium'"))  # low, medium, high, critical
    category = Column(String(100), nullable=False, index=True)  # UI Bug, Performance, Data Issue, etc.
    
    # Status tracking
    status = Column(String(50), nullable=False, default="open", server_default=text("'open'"), index=True)  # open, in-review, in-progress, resolved, closed, wont-fix
    
    # Page/Component Information
    page_url = Column(String(500), nullable=True)
    component_name = Column(String(200), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Screenshots and attachments (stored as URL or file paths)
    screenshot_url = Column(String(500), nullable=True)
    attachment_url = Column(String(500), nullable=True)
    
    # Environment and diagnostic info
    browser = Column(String(100), nullable=True)
    os_info = Column(String(100), nullable=True)
    app_version = Column(String(50), nullable=True)
    
    # Additional metadata
    error_message = Column(Text, nullable=True)
    steps_to_reproduce = Column(Text, nullable=True)
    expected_behavior = Column(Text, nullable=True)
    actual_behavior = Column(Text, nullable=True)
    
    # Admin notes
    admin_notes = Column(Text, nullable=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="bug_reports")
    assigned_admin = relationship("User", foreign_keys=[assigned_to], backref="assigned_bug_reports")
    
    # Indexes for common queries
    __table_args__ = (
        Index("idx_user_id_status", "user_id", "status"),
        Index("idx_status_severity", "status", "severity"),
        Index("idx_created_at_desc", "created_at"),
    )
