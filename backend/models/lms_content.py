# models/lms_content.py - LMS Course Content Hierarchy (Course -> Module -> Lesson -> ContentBlock)
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
    Text,
    Enum as SQLEnum,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ContentState(str, enum.Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class BlockType(str, enum.Enum):
    TEXT = "text"
    VIDEO = "video"
    QUIZ = "quiz"
    CODE = "code"
    FILE = "file"


class CourseModule(Base):
    """Module grouping within a course."""
    __tablename__ = "academy_modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id = Column(
        UUID(as_uuid=True), ForeignKey("academy_courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    lessons = relationship("CourseLesson", back_populates="module", cascade="all, delete-orphan")


class CourseLesson(Base):
    """An individual lesson within a module."""
    __tablename__ = "academy_lessons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_id = Column(
        UUID(as_uuid=True), ForeignKey("academy_modules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    video_url = Column(String(500), nullable=True)
    transcript_json = Column(JSONB, nullable=True)  # Timestamps & segment transcriptions
    duration_seconds = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    module = relationship("CourseModule", back_populates="lessons")
    blocks = relationship("ContentBlock", back_populates="lesson", cascade="all, delete-orphan")


class ContentBlock(Base):
    """Atomic content unit (text, video, quiz, code playground, file) within a lesson."""
    __tablename__ = "academy_content_blocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id = Column(
        UUID(as_uuid=True), ForeignKey("academy_lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    block_type = Column(SQLEnum(BlockType), nullable=False, default=BlockType.TEXT)
    title = Column(String(200), nullable=True)
    content_data = Column(JSONB, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    state = Column(SQLEnum(ContentState), nullable=False, default=ContentState.DRAFT)
    version = Column(Integer, nullable=False, default=1)
    approved_by_faculty_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    lesson = relationship("CourseLesson", back_populates="blocks")
