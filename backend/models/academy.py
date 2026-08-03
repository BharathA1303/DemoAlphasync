# models/academy.py - AlphaSync Academy (LMS) domain models.
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    Numeric,
    Date,
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


class Course(Base):
    """A learnable subject/topic."""

    __tablename__ = "academy_courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title = Column(String(150), nullable=False)
    slug = Column(String(150), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=False, index=True)
    total_lessons = Column(Integer, nullable=False, default=0)
    instructor_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(
        DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        Index("ix_academy_course_tenant_slug", "tenant_id", "slug", unique=True),
    )


class Enrollment(Base):
    """One row per (user, course) the student has started."""

    __tablename__ = "academy_enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("academy_courses.id", ondelete="CASCADE"), nullable=False)
    progress_percent = Column(Integer, nullable=False, default=0)
    enrolled_at = Column(
        DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    last_activity_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_academy_enroll_user_course", "user_id", "course_id", unique=True),
    )


class LessonProgress(Base):
    """Tracks completion of specific lessons within a course."""

    __tablename__ = "academy_lesson_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("academy_courses.id", ondelete="CASCADE"), nullable=False)
    lesson_id = Column(String(100), nullable=False)
    completed = Column(Boolean, default=False, nullable=False, server_default=text("false"))

    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_academy_lesson_user_course", "user_id", "course_id", "lesson_id", unique=True),
    )


class StudyActivity(Base):
    """Daily study time log."""

    __tablename__ = "academy_study_activity"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("academy_courses.id", ondelete="SET NULL"), nullable=True)
    activity_date = Column(Date, nullable=False)
    minutes_spent = Column(Integer, nullable=False, default=0)
    activity_type = Column(String(20), nullable=False, default="study")

    __table_args__ = (
        Index("ix_academy_activity_user_date", "user_id", "activity_date"),
    )


class QuizAttempt(Base):
    """A single scored quiz attempt."""

    __tablename__ = "academy_quiz_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("academy_courses.id", ondelete="SET NULL"), nullable=True)
    score_percent = Column(Numeric(5, 2), nullable=False)
    taken_at = Column(
        DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        Index("ix_academy_quiz_user_taken", "user_id", "taken_at"),
    )


class SkillMastery(Base):
    """Per-user, per-skill mastery percentage."""

    __tablename__ = "academy_skill_mastery"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    skill_name = Column(String(100), nullable=False)
    mastery_percent = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        Index("ix_academy_skill_user_name", "user_id", "skill_name", unique=True),
    )

    @property
    def level(self) -> str:
        if self.mastery_percent >= 80:
            return "Advanced"
        if self.mastery_percent >= 60:
            return "Intermediate"
        return "Beginner"


class TeacherStudentAssignment(Base):
    """Mapping table establishing teacher-student relationships in the academy."""

    __tablename__ = "academy_teacher_student_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(
        DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    notes = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_academy_teacher_student", "teacher_id", "student_id", unique=True),
        Index("ix_academy_student_teacher", "student_id"),
    )


class Challenge(Base):
    """Trading and financial literacy challenge definitions created by Teachers or Admins."""

    __tablename__ = "academy_challenges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=False, default="Trading & Risk")
    difficulty = Column(String(20), nullable=False, default="Beginner")
    target_metric = Column(String(50), nullable=False, default="pnl")
    target_value = Column(Numeric(14, 2), nullable=False, default=1000.0)
    reward_points = Column(Integer, nullable=False, default=100)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class StudentChallengeProgress(Base):
    """Tracks a student's participation and progress in a challenge."""

    __tablename__ = "academy_student_challenge_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    challenge_id = Column(UUID(as_uuid=True), ForeignKey("academy_challenges.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="in_progress")
    current_value = Column(Numeric(14, 2), nullable=False, default=0.0)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        Index("ix_academy_student_challenge", "user_id", "challenge_id", unique=True),
    )
