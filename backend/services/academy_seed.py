# services/academy_seed.py - Deterministic demo-data seeding for AlphaSync
# Academy, mirroring the trading platform's own philosophy of always having
# realistic mock data available (deterministic Brownian-bridge ticks, mock
# bhavcopy fallback) rather than showing blank charts to a new user.
import hashlib
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.academy import Course, Enrollment, QuizAttempt, SkillMastery, StudyActivity

logger = logging.getLogger(__name__)

# Fixed demo catalog — categories double as "skills" reported on the
# analytics page (Skill Mastery Breakdown / Strengths vs Weaknesses /
# Time Spent by Topic).
COURSE_CATALOG = [
    {"title": "Python Basics", "slug": "python-basics", "category": "Python Basics", "total_lessons": 24,
     "description": "Core Python syntax, data types, and control flow for absolute beginners."},
    {"title": "Data Analysis with Pandas", "slug": "data-analysis", "category": "Data Analysis", "total_lessons": 20,
     "description": "Cleaning, transforming, and analyzing tabular data with pandas and numpy."},
    {"title": "Trading Basics", "slug": "trading-basics", "category": "Trading Basics", "total_lessons": 18,
     "description": "Order types, market structure, and the fundamentals of buying and selling."},
    {"title": "Statistics for Traders", "slug": "statistics", "category": "Statistics", "total_lessons": 16,
     "description": "Probability, distributions, and statistical reasoning applied to markets."},
    {"title": "Technical Analysis", "slug": "technical-analysis", "category": "Technical Analysis", "total_lessons": 22,
     "description": "Chart patterns, indicators, and reading price action."},
    {"title": "Options Trading Masterclass", "slug": "options-trading", "category": "Options Trading", "total_lessons": 26,
     "description": "Options pricing, Greeks, and common strategies."},
    {"title": "Risk Management Strategies", "slug": "risk-management", "category": "Risk Management", "total_lessons": 14,
     "description": "Position sizing, stop-losses, and protecting capital."},
]

_ACTIVITY_TYPES = ("study", "quiz", "assignment")


def _seed_for_user(user_id: uuid.UUID) -> int:
    """Deterministic seed derived from the user id, so re-running the seed
    for the same user always produces the same demo numbers (consistent
    with the rest of the platform's determinism-by-design approach)."""
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


async def ensure_academy_catalog(db: AsyncSession) -> List[Course]:
    """Insert the fixed demo course catalog if it doesn't already exist.
    Idempotent — safe to call on every startup."""
    result = await db.execute(select(Course))
    existing = {c.slug: c for c in result.scalars().all()}

    created = False
    for entry in COURSE_CATALOG:
        if entry["slug"] in existing:
            continue
        course = Course(
            id=uuid.uuid4(),
            title=entry["title"],
            slug=entry["slug"],
            description=entry["description"],
            category=entry["category"],
            total_lessons=entry["total_lessons"],
        )
        db.add(course)
        created = True

    if created:
        await db.commit()
        result = await db.execute(select(Course))
        existing = {c.slug: c for c in result.scalars().all()}

    return list(existing.values())


async def ensure_user_academy_data(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Backfill deterministic demo Enrollment/StudyActivity/QuizAttempt/
    SkillMastery rows for a user who has none yet. No-ops if the user
    already has any academy data (real usage should never be overwritten
    by the seed)."""
    existing = await db.execute(
        select(Enrollment.id).where(Enrollment.user_id == user_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return  # Already has real/seeded data — never overwrite.

    courses = await ensure_academy_catalog(db)
    if not courses:
        return

    rng_seed = _seed_for_user(user_id)
    today = date.today()

    # Enroll in every course with a deterministic, varied progress spread.
    for i, course in enumerate(courses):
        progress = (rng_seed >> (i * 3)) % 101
        db.add(
            Enrollment(
                id=uuid.uuid4(),
                user_id=user_id,
                course_id=course.id,
                progress_percent=progress,
                enrolled_at=datetime.now(timezone.utc) - timedelta(days=30 - i * 2),
                last_activity_at=datetime.now(timezone.utc) - timedelta(days=i),
            )
        )

    # Skill mastery per course category, deterministic spread across the
    # Beginner/Intermediate/Advanced bands.
    for i, course in enumerate(courses):
        mastery = 35 + ((rng_seed >> (i * 5)) % 61)  # 35-95
        db.add(
            SkillMastery(
                id=uuid.uuid4(),
                user_id=user_id,
                skill_name=course.category,
                mastery_percent=mastery,
            )
        )

    # 21 days of study activity, weighted toward higher-mastery courses,
    # producing a realistic-looking heatmap and rising progress line.
    for day_offset in range(21, 0, -1):
        activity_date = today - timedelta(days=day_offset)
        day_seed = (rng_seed ^ day_offset) & 0xFFFF
        if day_seed % 5 == 0:
            continue  # occasional rest day, avoids a suspiciously-perfect streak

        num_sessions = 1 + (day_seed % 3)
        for session_idx in range(num_sessions):
            course = courses[(day_seed + session_idx) % len(courses)]
            minutes = 15 + ((day_seed >> (session_idx * 3)) % 90)
            activity_type = _ACTIVITY_TYPES[(day_seed + session_idx) % len(_ACTIVITY_TYPES)]
            db.add(
                StudyActivity(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    course_id=course.id,
                    activity_date=activity_date,
                    minutes_spent=minutes,
                    activity_type=activity_type,
                )
            )

            if activity_type == "quiz":
                score = 55 + ((day_seed >> (session_idx * 2)) % 46)  # 55-100
                db.add(
                    QuizAttempt(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        course_id=course.id,
                        score_percent=score,
                        taken_at=datetime.combine(
                            activity_date, datetime.min.time(), tzinfo=timezone.utc
                        )
                        + timedelta(hours=10 + session_idx),
                    )
                )

    await db.commit()
    logger.info(f"Academy: seeded demo data for user {user_id}")
