# models/academy.py - AlphaSync Academy (LMS) domain models.
#
# Additive, new subsystem living alongside the trading-platform models in
# this same file (users, orders, portfolio, ...). Reuses the same User
# table (see models/user.py's `academy_role` column) rather than a
# separate account system, and the same UUID-PK / Base declarative style
# used across the rest of backend/models/.
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
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
    """A learnable subject/topic. Phase 1 has a small fixed demo catalog
    (see academy_seed.py) — no course-authoring UI yet."""

    __tablename__ = "academy_courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(150), nullable=False)
    slug = Column(String(150), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    # Category doubles as the "skill" name shown in Skill Mastery Breakdown /
    # Strengths vs Weaknesses / Time Spent by Topic on the analytics page.
    category = Column(String(100), nullable=False, index=True)
    total_lessons = Column(Integer, nullable=False, default=0)
    # Faculty who teaches this course, for the Faculty Dashboard (Phase 2).
    # Nullable — Phase 1's fixed demo catalog has no instructor assigned
    # until a faculty user first opens their dashboard (see
    # academy_seed.ensure_faculty_teaching_data).
    instructor_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(
        DateTime(timezone=True), default=_utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class Enrollment(Base):
    """One row per (user, course) the student has started."""

    __tablename__ = "academy_enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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


class StudyActivity(Base):
    """Row-level daily study time, the base data the analytics dashboard
    aggregates into the activity heatmap, time-by-topic donut, and the
    progress-over-time line."""

    __tablename__ = "academy_study_activity"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("academy_courses.id", ondelete="SET NULL"), nullable=True)
    activity_date = Column(Date, nullable=False)
    minutes_spent = Column(Integer, nullable=False, default=0)
    # "study" | "quiz" | "assignment"
    activity_type = Column(String(20), nullable=False, default="study")

    __table_args__ = (
        Index("ix_academy_activity_user_date", "user_id", "activity_date"),
    )


class QuizAttempt(Base):
    """A single scored quiz attempt — feeds Average Quiz Score and the
    quiz-performance-improving insight."""

    __tablename__ = "academy_quiz_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    """Per-user, per-skill (== Course.category) mastery percentage."""

    __tablename__ = "academy_skill_mastery"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
        """Beginner/Intermediate/Advanced, derived from mastery_percent —
        not stored, so it always stays consistent with the percent."""
        if self.mastery_percent >= 80:
            return "Advanced"
        if self.mastery_percent >= 60:
            return "Intermediate"
        return "Beginner"
