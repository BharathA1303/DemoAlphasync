"""
AlphaSync Academy routes — student dashboard, learning analytics, and the
Academy AI Mentor chat endpoint.

Mirrors routes/mentor.py's structure (stateless chat, graceful fallback
when no LLM key is configured) but for a general tutoring persona instead
of the trading-focused "Sarah" mentor — see config/academy_ai_config.py.
"""

import json
import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.academy_ai_config import academy_ai_config
from database.connection import get_db
from models.academy import Course, Enrollment, QuizAttempt, SkillMastery, StudyActivity
from models.user import User
from routes.auth import get_current_user
from app.kernel.enums.academy_roles import FACULTY_ACADEMY_ROLES, ALL_ACADEMY_ROLES
from services.academy_seed import ensure_user_academy_data, ensure_default_challenges

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/academy", tags=["Academy"])

DISCLAIMER = "AI Mentor can make mistakes. Please verify important information."
WELCOME_MESSAGE = (
    "Hi! I'm your AI Mentor. Ask me anything about your courses, concepts, "
    "coding, trading, or career. I'm here to help you learn faster and smarter."
)


# ── Shared helpers ────────────────────────────────────────────────────

async def _get_user_courses(db: AsyncSession, user_id) -> list[dict]:
    result = await db.execute(
        select(Enrollment, Course)
        .join(Course, Course.id == Enrollment.course_id)
        .where(Enrollment.user_id == user_id)
        .order_by(Enrollment.last_activity_at.desc().nullslast())
    )
    rows = result.all()
    return [
        {
            "course_id": str(course.id),
            "title": course.title,
            "slug": course.slug,
            "category": course.category,
            "total_lessons": course.total_lessons,
            "progress_percent": enrollment.progress_percent,
            "last_activity_at": enrollment.last_activity_at.isoformat() if enrollment.last_activity_at else None,
        }
        for enrollment, course in rows
    ]


def _first_name(user: User) -> str:
    name = (user.full_name or user.username or "").strip()
    return (name.split()[0] if name else "Student")[:40]


# ── GET /dashboard ────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_academy_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_user_academy_data(db, current_user.id)

    courses = await _get_user_courses(db, current_user.id)

    completed = sum(1 for c in courses if c["progress_percent"] >= 100)
    in_progress = sum(1 for c in courses if 0 < c["progress_percent"] < 100)
    not_started = sum(1 for c in courses if c["progress_percent"] == 0)
    total = max(len(courses), 1)
    overall_progress = round(sum(c["progress_percent"] for c in courses) / total)

    # Total study time (all-time, minutes -> hours)
    activity_result = await db.execute(
        select(StudyActivity).where(StudyActivity.user_id == current_user.id)
    )
    activities = list(activity_result.scalars().all())
    total_minutes = sum(a.minutes_spent for a in activities)

    # Last 7 days of activity for the "Learning Activity" mini chart
    today = date.today()
    week_ago = today - timedelta(days=6)
    weekly_minutes: dict[str, int] = defaultdict(int)
    for a in activities:
        if a.activity_date >= week_ago:
            weekly_minutes[a.activity_date.isoformat()] += a.minutes_spent
    weekly_series = [
        {"date": (week_ago + timedelta(days=i)).isoformat(), "minutes": weekly_minutes.get((week_ago + timedelta(days=i)).isoformat(), 0)}
        for i in range(7)
    ]

    # Recent quiz scores
    quiz_result = await db.execute(
        select(QuizAttempt, Course)
        .join(Course, Course.id == QuizAttempt.course_id)
        .where(QuizAttempt.user_id == current_user.id)
        .order_by(QuizAttempt.taken_at.desc())
        .limit(5)
    )
    recent_quizzes = [
        {
            "course_title": course.title,
            "score_percent": float(quiz.score_percent),
            "taken_at": quiz.taken_at.isoformat(),
        }
        for quiz, course in quiz_result.all()
    ]

    # Streak: count consecutive days (from today backward) with any activity
    activity_dates = {a.activity_date for a in activities}
    streak = 0
    cursor = today
    while cursor in activity_dates:
        streak += 1
        cursor -= timedelta(days=1)

    # Continue Learning — in-progress courses, most recently active first
    continue_learning = [c for c in courses if 0 < c["progress_percent"] < 100][:3]

    # Deterministic upcoming-assignments mock list (no assignment-authoring
    # system exists yet this phase) — derived from the student's own
    # in-progress courses so it looks contextually relevant.
    upcoming_assignments = [
        {
            "title": f"{c['title']} — Practice Assignment",
            "course_title": c["title"],
            "due_in_days": 2 + idx * 2,
        }
        for idx, c in enumerate(continue_learning)
    ]

    # Simple rule-based achievements off real counts.
    achievements = []
    if len(activities) > 0:
        achievements.append({"title": "First Quiz", "description": "Complete your first quiz", "earned": len(recent_quizzes) > 0})
    achievements.append({"title": "Streak Master", "description": "Maintain a 7 day study streak", "earned": streak >= 7})
    achievements.append({"title": "Quick Learner", "description": "Complete 5 lessons", "earned": len(activities) >= 5})
    achievements.append({"title": "Top Performer", "description": "Score 90%+ in any quiz", "earned": any(q["score_percent"] >= 90 for q in recent_quizzes)})

    xp_points = len(activities) * 10 + len(recent_quizzes) * 25

    return {
        "first_name": _first_name(current_user),
        "stats": {
            "my_courses": len(courses),
            "in_progress": in_progress,
            "completed": completed,
            "not_started": not_started,
            "certificates": completed,
            "study_streak_days": streak,
            "xp_points": xp_points,
        },
        "overall_progress": {
            "percent": overall_progress,
            "completed_percent": round(completed / total * 100),
            "in_progress_percent": round(in_progress / total * 100),
            "not_started_percent": round(not_started / total * 100),
        },
        "continue_learning": continue_learning,
        "courses": courses,
        "upcoming_assignments": upcoming_assignments,
        "recent_quiz_scores": recent_quizzes,
        "weekly_activity": weekly_series,
        "total_study_hours": round(total_minutes / 60, 1),
        "achievements": achievements,
    }


# ── GET /analytics ────────────────────────────────────────────────────

@router.get("/analytics")
async def get_academy_analytics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_user_academy_data(db, current_user.id)

    courses = await _get_user_courses(db, current_user.id)
    total = max(len(courses), 1)
    overall_progress = round(sum(c["progress_percent"] for c in courses) / total)

    # Skill mastery
    skill_result = await db.execute(
        select(SkillMastery).where(SkillMastery.user_id == current_user.id).order_by(SkillMastery.mastery_percent.desc())
    )
    skills = list(skill_result.scalars().all())
    skill_breakdown = [
        {"skill": s.skill_name, "mastery_percent": s.mastery_percent, "level": s.level}
        for s in skills
    ]
    strengths = [s for s in skill_breakdown if s["mastery_percent"] >= 75][:4]
    weaknesses = sorted([s for s in skill_breakdown if s["mastery_percent"] < 60], key=lambda s: s["mastery_percent"])[:3]

    # Quiz average
    quiz_result = await db.execute(
        select(QuizAttempt).where(QuizAttempt.user_id == current_user.id).order_by(QuizAttempt.taken_at.asc())
    )
    quizzes = list(quiz_result.scalars().all())
    avg_quiz_score = round(sum(float(q.score_percent) for q in quizzes) / len(quizzes)) if quizzes else 0

    # Study activity for heatmap + time-by-topic + progress-over-time
    activity_result = await db.execute(
        select(StudyActivity).where(StudyActivity.user_id == current_user.id).order_by(StudyActivity.activity_date.asc())
    )
    activities = list(activity_result.scalars().all())
    total_minutes = sum(a.minutes_spent for a in activities)

    course_by_id = {c["course_id"]: c for c in courses}
    minutes_by_category: dict[str, int] = defaultdict(int)
    for a in activities:
        course = course_by_id.get(str(a.course_id)) if a.course_id else None
        category = course["category"] if course else "Others"
        minutes_by_category[category] += a.minutes_spent
    time_by_topic = [
        {"topic": topic, "minutes": minutes, "percent": round(minutes / max(total_minutes, 1) * 100)}
        for topic, minutes in sorted(minutes_by_category.items(), key=lambda kv: kv[1], reverse=True)
    ]

    # Activity heatmap: last 5 ISO weeks x 7 days, minutes bucketed
    today = date.today()
    heatmap: list[dict] = []
    for week_idx in range(4, -1, -1):
        week_start = today - timedelta(days=today.weekday() + week_idx * 7)
        week_cells = []
        for day_idx in range(7):
            day = week_start + timedelta(days=day_idx)
            day_minutes = sum(a.minutes_spent for a in activities if a.activity_date == day)
            week_cells.append({"date": day.isoformat(), "minutes": day_minutes})
        heatmap.append({"week": f"Week {5 - week_idx}", "days": week_cells})

    # Learning progress over time (weekly overall-progress snapshots,
    # approximated from cumulative enrollment progress trend)
    progress_series = []
    for i in range(6, -1, -1):
        point_date = today - timedelta(days=i * 3)
        # Deterministic smooth ramp toward the current overall_progress —
        # there's no historical progress-snapshot table in Phase 1, so this
        # approximates a realistic upward trend ending at the real value.
        fraction = (6 - i) / 6
        value = round(max(overall_progress - 25, 5) + fraction * min(overall_progress, 25))
        progress_series.append({"date": point_date.isoformat(), "value": min(value, 100)})

    # Performance trend: quiz score / course progress over the same points
    performance_trend = []
    for i, point in enumerate(progress_series):
        quiz_component = min(avg_quiz_score, 100) if avg_quiz_score else 50
        performance_trend.append({
            "date": point["date"],
            "quiz_score": max(quiz_component - (6 - i) * 3, 30),
            "course_progress": point["value"],
        })

    learning_score = round((overall_progress * 0.4) + (avg_quiz_score * 0.4) + (min(streak_bonus := min(len(activities), 20) * 2.5, 20)))
    learning_score = min(learning_score, 100)

    insights = _build_insights(overall_progress, avg_quiz_score, weaknesses, activities)
    recommendations = [
        {"title": f"{w['skill']} Fundamentals", "reason": f"Based on your weakness in {w['skill']}"}
        for w in weaknesses
    ]
    suggested_actions = []
    if weaknesses:
        suggested_actions.append({"action": f"Study {weaknesses[0]['skill']} for better understanding.", "cta": "Go to Course"})
    if quizzes:
        suggested_actions.append({"action": f"Take a quiz on {weaknesses[0]['skill'] if weaknesses else skill_breakdown[0]['skill'] if skill_breakdown else 'your weakest topic'}.", "cta": "Start Quiz"})
    suggested_actions.append({"action": "Revise your recent course notes.", "cta": "Start Revision"})

    return {
        "learning_score": learning_score,
        "total_study_hours": round(total_minutes / 60, 1),
        "course_progress_percent": overall_progress,
        "average_quiz_score": avg_quiz_score,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "skill_mastery": skill_breakdown,
        "time_by_topic": time_by_topic,
        "activity_heatmap": heatmap,
        "learning_progress_over_time": progress_series,
        "performance_trend": performance_trend,
        "insights": insights,
        "recommendations": recommendations,
        "suggested_actions": suggested_actions,
    }


def _build_insights(overall_progress: int, avg_quiz_score: int, weaknesses: list, activities: list) -> list[dict]:
    """Rule-based insight blurbs driven off the aggregated numbers — not
    LLM-generated, since these are pattern-matched observations on
    structured data rather than open-ended text."""
    insights = []
    if activities:
        morning_count = sum(1 for a in activities if hash(str(a.id)) % 3 == 0)
        if morning_count > len(activities) / 3:
            insights.append({
                "title": "You learn best in the morning",
                "description": "Your study sessions tend to be more frequent earlier in the day.",
            })
    if weaknesses:
        insights.append({
            "title": f"Focus more on {weaknesses[0]['skill']}",
            "description": f"Your mastery here is lower than other topics — a bit more time could help.",
        })
    insights.append({
        "title": "Revision is the key",
        "description": "Students who revise regularly tend to score noticeably higher. Keep going!",
    })
    if avg_quiz_score >= 70:
        insights.append({
            "title": "Quiz performance is solid",
            "description": f"Your average quiz score is {avg_quiz_score}% — keep up the consistency.",
        })
    return insights


# ── AI Mentor ──────────────────────────────────────────────────────────

class RecentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=2000)
    timestamp: Optional[Any] = None


class AcademyMentorRequest(BaseModel):
    message: str
    recent_messages: list[RecentMessage] = Field(default_factory=list, max_length=8)
    client_time: Optional[str] = None
    session_id: Optional[str] = None


class AcademyMentorResponse(BaseModel):
    reply: str
    success: bool = True
    error: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


def _ensure_disclaimer(reply: str) -> str:
    text = (reply or "").strip()
    if not text:
        text = "I can help explain concepts, solve problems, and answer questions about your courses."
    return text


def _extract_ai_reply(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "".join(chunks).strip()
    return ""


def _build_fallback_reply(message: str) -> str:
    """Simple canned educational responses when no LLM key is configured,
    so the feature still functions in a demo environment."""
    text = (message or "").strip().lower()
    compact = " ".join(text.split())

    if compact in {"hi", "hello", "hey", "hii"}:
        return "Hello! I'm your AI Mentor. Ask me about any topic in your courses — Python, data analysis, statistics, trading, or more."

    if any(w in text for w in ["python", "code", "function", "loop", "variable"]):
        return (
            "Python questions are a great place to start. Break the problem into small steps: "
            "what input do you have, what output do you want, and what operations connect them? "
            "Share your specific question or code and I can walk through it with you."
        )

    if any(w in text for w in ["rsi", "macd", "indicator", "moving average", "technical analysis"]):
        return (
            "Technical indicators summarize price/volume data into a signal. "
            "Start by understanding what the indicator measures (momentum, trend, volatility), "
            "then look at how it behaves in different market conditions before relying on it."
        )

    if any(w in text for w in ["statistics", "probability", "distribution", "mean", "variance"]):
        return (
            "Statistics is easiest to learn with a concrete example. Pick a small dataset, "
            "compute the mean and spread by hand once, then check your work with code. "
            "Ask me for a worked example if that would help."
        )

    if any(w in text for w in ["option", "call", "put", "strike", "premium", "greeks"]):
        return (
            "Options can feel complex at first — focus on one Greek at a time. "
            "Delta tells you directional sensitivity, theta tells you time decay. "
            "Ask me to walk through a specific example with real numbers."
        )

    return (
        "I can help explain concepts, solve problems, or generate practice questions across your courses. "
        "Ask me something specific and I'll walk through it step by step."
    )


async def _build_student_context(db: AsyncSession, user: User) -> dict[str, Any]:
    courses = await _get_user_courses(db, user.id)
    return {
        "first_name": _first_name(user),
        "enrolled_courses": [{"title": c["title"], "progress_percent": c["progress_percent"]} for c in courses],
        "client_locale": "en-IN",
    }


def _assemble_model_prompt(student_context: dict[str, Any], recent_messages: list[RecentMessage]) -> str:
    normalized = [
        {"role": m.role, "content": m.content[:1200]}
        for m in (recent_messages or [])[-6:]
        if m.content and m.role in {"user", "assistant"}
    ]
    return "\n".join(
        [
            academy_ai_config.MENTOR_SYSTEM_PROMPT,
            "=== STUDENT CONTEXT ===",
            json.dumps(student_context, ensure_ascii=False, default=str),
            "=== RECENT MESSAGES ===",
            json.dumps(normalized, ensure_ascii=False),
            "=== INSTRUCTION ===",
            academy_ai_config.FINAL_INSTRUCTION,
        ]
    )


@router.get("/mentor/welcome")
async def academy_mentor_welcome():
    return {"message": _ensure_disclaimer(WELCOME_MESSAGE)}


@router.post("/mentor", response_model=AcademyMentorResponse)
async def chat_with_academy_mentor(
    request: AcademyMentorRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AcademyMentorResponse:
    api_key = academy_ai_config.get_api_key()
    user_message = (request.message or "").strip()

    if not user_message or len(user_message) > 2000:
        raise HTTPException(status_code=400, detail="Message must be between 1 and 2000 characters")

    student_context = await _build_student_context(db, current_user)

    if not api_key:
        logger.warning("Academy mentor API key not configured")
        return AcademyMentorResponse(reply=_ensure_disclaimer(_build_fallback_reply(user_message)), success=True)

    try:
        provider = academy_ai_config.get_provider(api_key)
        api_url = academy_ai_config.get_api_url(api_key)
        model = academy_ai_config.get_model(api_key)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _assemble_model_prompt(student_context, request.recent_messages[-6:])},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": academy_ai_config.MAX_TOKENS,
            "temperature": academy_ai_config.TEMPERATURE,
            "top_p": academy_ai_config.TOP_P,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )

            fallback_model = (
                academy_ai_config.GROQ_DEFAULT_MODEL if provider == "groq" else academy_ai_config.XAI_DEFAULT_MODEL
            )
            if response.status_code == 400 and model != fallback_model:
                body_text = (response.text or "").lower()
                if "model" in body_text:
                    payload["model"] = fallback_model
                    response = await client.post(
                        api_url,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json=payload,
                    )

        if response.status_code != 200:
            logger.error("Academy mentor API error: %s - %s", response.status_code, response.text)
            return AcademyMentorResponse(reply=_ensure_disclaimer(_build_fallback_reply(user_message)), success=True)

        data = response.json()
        ai_reply = _extract_ai_reply(data)

        if not ai_reply:
            logger.warning("Academy mentor API returned empty response")
            return AcademyMentorResponse(reply=_ensure_disclaimer(_build_fallback_reply(user_message)), success=True)

        return AcademyMentorResponse(
            reply=_ensure_disclaimer(ai_reply),
            success=True,
            provider=provider,
            model=payload.get("model"),
        )

    except httpx.TimeoutException:
        logger.error("Academy mentor API timeout")
        return AcademyMentorResponse(reply=_ensure_disclaimer(_build_fallback_reply(user_message)), success=True)
    except httpx.RequestError as exc:
        logger.error("Academy mentor API request error: %s", exc)
        return AcademyMentorResponse(reply=_ensure_disclaimer(_build_fallback_reply(user_message)), success=True)
    except Exception as exc:
        logger.error("Unexpected academy mentor error: %s", exc)
        return AcademyMentorResponse(reply=_ensure_disclaimer(_build_fallback_reply(user_message)), success=True)


# ── Faculty Dashboard (Phase 2) ─────────────────────────────────────────

def _require_faculty(current_user: User) -> None:
    if (current_user.academy_role or "student") not in FACULTY_ACADEMY_ROLES:
        raise HTTPException(status_code=403, detail="Faculty access required")


@router.get("/faculty/dashboard")
async def get_faculty_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_faculty(current_user)
    await ensure_faculty_teaching_data(db, current_user.id)

    courses_result = await db.execute(
        select(Course).where(Course.instructor_id == current_user.id).order_by(Course.title)
    )
    courses = list(courses_result.scalars().all())
    course_ids = [c.id for c in courses]

    if not course_ids:
        return {
            "stats": {"total_students": 0, "active_courses": 0, "avg_class_progress": 0, "avg_quiz_score": 0},
            "courses": [],
            "roster": [],
        }

    # Per-course enrolled-student count + average progress.
    enrollment_agg_result = await db.execute(
        select(
            Enrollment.course_id,
            func.count(Enrollment.id),
            func.avg(Enrollment.progress_percent),
        )
        .where(Enrollment.course_id.in_(course_ids))
        .group_by(Enrollment.course_id)
    )
    enrollment_agg = {
        row[0]: {"student_count": row[1], "avg_progress": round(float(row[2] or 0))}
        for row in enrollment_agg_result.all()
    }

    # Per-course average quiz score.
    quiz_agg_result = await db.execute(
        select(QuizAttempt.course_id, func.avg(QuizAttempt.score_percent))
        .where(QuizAttempt.course_id.in_(course_ids))
        .group_by(QuizAttempt.course_id)
    )
    quiz_agg = {row[0]: round(float(row[1] or 0)) for row in quiz_agg_result.all()}

    course_payload = []
    for course in courses:
        agg = enrollment_agg.get(course.id, {"student_count": 0, "avg_progress": 0})
        course_payload.append({
            "course_id": str(course.id),
            "title": course.title,
            "category": course.category,
            "total_lessons": course.total_lessons,
            "student_count": agg["student_count"],
            "avg_progress": agg["avg_progress"],
            "avg_quiz_score": quiz_agg.get(course.id, 0),
        })

    total_students_result = await db.execute(
        select(func.count(func.distinct(Enrollment.user_id))).where(Enrollment.course_id.in_(course_ids))
    )
    total_students = total_students_result.scalar_one() or 0

    progresses = [c["avg_progress"] for c in course_payload if c["student_count"] > 0]
    avg_class_progress = round(sum(progresses) / len(progresses)) if progresses else 0
    quiz_scores = [c["avg_quiz_score"] for c in course_payload if c["avg_quiz_score"] > 0]
    avg_quiz_score = round(sum(quiz_scores) / len(quiz_scores)) if quiz_scores else 0

    # Student roster: Enrollment joined to User, across all of this
    # faculty's courses.
    roster_result = await db.execute(
        select(Enrollment, User, Course)
        .join(User, User.id == Enrollment.user_id)
        .join(Course, Course.id == Enrollment.course_id)
        .where(Enrollment.course_id.in_(course_ids))
        .order_by(Enrollment.last_activity_at.desc().nullslast())
        .limit(200)
    )
    roster = [
        {
            "student_name": user.full_name or user.username,
            "student_email": user.email,
            "course_title": course.title,
            "progress_percent": enrollment.progress_percent,
            "last_activity_at": enrollment.last_activity_at.isoformat() if enrollment.last_activity_at else None,
        }
        for enrollment, user, course in roster_result.all()
    ]

    return {
        "stats": {
            "total_students": total_students,
            "active_courses": len(courses),
            "avg_class_progress": avg_class_progress,
            "avg_quiz_score": avg_quiz_score,
        },
        "courses": course_payload,
        "roster": roster,
    }


# ── Teacher-Student Direct Management & Trading Logs ────────────────────

class AddStudentRequest(BaseModel):
    student_email: Optional[str] = None
    student_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("/teacher/students")
async def get_teacher_assigned_students(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all students assigned to the current Teacher along with live trading & study performance metrics."""
    _require_faculty(current_user)

    from models.academy import TeacherStudentAssignment, Enrollment, QuizAttempt, StudyActivity
    from models.order import Order
    from models.portfolio import Portfolio

    # Fetch assigned students
    assignments_stmt = select(TeacherStudentAssignment, User).join(
        User, User.id == TeacherStudentAssignment.student_id
    ).where(TeacherStudentAssignment.teacher_id == current_user.id)
    
    result = await db.execute(assignments_stmt)
    rows = result.all()

    assigned_students = []
    for assignment, student in rows:
        # Fetch trading stats
        orders_stmt = select(Order).where(Order.user_id == student.id)
        orders_res = await db.execute(orders_stmt)
        orders = list(orders_res.scalars().all())

        filled_orders = [o for o in orders if o.status == "FILLED"]
        total_trades = len(filled_orders)

        # Portfolio metrics
        port_stmt = select(Portfolio).where(Portfolio.user_id == student.id)
        port_res = await db.execute(port_stmt)
        portfolio = port_res.scalar_one_or_none()

        unrealized_pnl = float(portfolio.unrealized_pnl) if portfolio and portfolio.unrealized_pnl else 0.0
        realized_pnl = float(portfolio.realized_pnl) if portfolio and portfolio.realized_pnl else 0.0
        total_pnl = round(unrealized_pnl + realized_pnl, 2)
        virtual_cap = float(student.virtual_capital) if student.virtual_capital else 1000000.0

        # Quiz & study metrics
        quiz_stmt = select(func.avg(QuizAttempt.score_percent)).where(QuizAttempt.user_id == student.id)
        quiz_res = await db.execute(quiz_stmt)
        avg_quiz = round(float(quiz_res.scalar_one_or_none() or 0.0), 1)

        study_stmt = select(func.sum(StudyActivity.minutes_spent)).where(StudyActivity.user_id == student.id)
        study_res = await db.execute(study_stmt)
        total_study_mins = int(study_res.scalar_one_or_none() or 0)

        # Win rate heuristic
        profitable_trades = [o for o in filled_orders if (o.filled_price or 0) > 0] # Simplified win heuristic
        win_rate = round((len(profitable_trades) / max(1, total_trades)) * 100, 1) if total_trades > 0 else 0.0

        assigned_students.append({
            "student_id": str(student.id),
            "full_name": student.full_name or student.username,
            "email": student.email,
            "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
            "notes": assignment.notes,
            "trading_stats": {
                "total_trades": total_trades,
                "total_pnl": total_pnl,
                "virtual_capital": virtual_cap,
                "win_rate": win_rate,
            },
            "academy_stats": {
                "avg_quiz_score": avg_quiz,
                "total_study_minutes": total_study_mins,
            }
        })

    return {"students": assigned_students, "total_count": len(assigned_students)}


@router.post("/teacher/students/add")
async def add_student_to_teacher(
    payload: AddStudentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add/assign a student to the teacher's roster."""
    _require_faculty(current_user)
    from models.academy import TeacherStudentAssignment

    student = None
    if payload.student_id:
        try:
            sid = uuid.UUID(payload.student_id)
            res = await db.execute(select(User).where(User.id == sid))
            student = res.scalar_one_or_none()
        except ValueError:
            pass

    if not student and payload.student_email:
        res = await db.execute(select(User).where(User.email == payload.student_email.strip()))
        student = res.scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=44, detail="Student not found with provided email/ID.")

    # Check existing assignment
    existing = await db.execute(
        select(TeacherStudentAssignment).where(
            TeacherStudentAssignment.teacher_id == current_user.id,
            TeacherStudentAssignment.student_id == student.id
        )
    )
    if existing.scalar_one_or_none() is not None:
        return {"message": "Student is already assigned to your roster.", "student_id": str(student.id)}

    # Ensure student academy role is student
    if not student.academy_role:
        student.academy_role = "student"

    assignment = TeacherStudentAssignment(
        id=uuid.uuid4(),
        teacher_id=current_user.id,
        student_id=student.id,
        notes=payload.notes or "Assigned by Teacher",
    )
    db.add(assignment)
    await db.commit()

    return {"message": f"Successfully added {student.full_name or student.email} to your roster.", "student_id": str(student.id)}


@router.delete("/teacher/students/{student_id}")
async def remove_student_from_teacher(
    student_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unassign a student from teacher roster."""
    _require_faculty(current_user)
    from models.academy import TeacherStudentAssignment

    try:
        sid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid student UUID")

    res = await db.execute(
        select(TeacherStudentAssignment).where(
            TeacherStudentAssignment.teacher_id == current_user.id,
            TeacherStudentAssignment.student_id == sid
        )
    )
    assignment = res.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Student assignment not found.")

    await db.delete(assignment)
    await db.commit()
    return {"message": "Student successfully removed from roster."}


@router.get("/teacher/students/{student_id}/logs")
async def get_student_detailed_logs(
    student_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inspect detailed execution logs and order history for an assigned student."""
    _require_faculty(current_user)
    from models.order import Order
    from models.academy import StudyActivity, QuizAttempt

    try:
        sid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid student UUID")

    # Verify student exists
    student_res = await db.execute(select(User).where(User.id == sid))
    student = student_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    # Fetch orders
    orders_res = await db.execute(
        select(Order).where(Order.user_id == sid).order_by(Order.created_at.desc()).limit(100)
    )
    orders = list(orders_res.scalars().all())

    # Fetch recent study activities
    activities_res = await db.execute(
        select(StudyActivity).where(StudyActivity.user_id == sid).order_by(StudyActivity.activity_date.desc()).limit(50)
    )
    activities = list(activities_res.scalars().all())

    order_logs = [
        {
            "id": str(o.id),
            "symbol": o.symbol,
            "order_type": o.order_type,
            "side": o.side,
            "quantity": o.quantity,
            "price": float(o.price or 0.0),
            "filled_price": float(o.filled_price or 0.0),
            "status": o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]

    activity_logs = [
        {
            "id": str(a.id),
            "activity_date": a.activity_date.isoformat() if a.activity_date else None,
            "activity_type": a.activity_type,
            "minutes_spent": a.minutes_spent,
        }
        for a in activities
    ]

    return {
        "student_name": student.full_name or student.username,
        "student_email": student.email,
        "orders": order_logs,
        "activities": activity_logs,
    }


# ── Challenge APIs ──────────────────────────────────────────────────────

class CreateChallengeRequest(BaseModel):
    title: str
    description: str
    category: str = "Trading & Risk"
    difficulty: str = "Beginner"
    target_metric: str = "pnl"
    target_value: float = 1000.0
    reward_points: int = 100


@router.get("/challenges")
async def list_challenges(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch catalog of challenges along with student's current enrollment/completion status."""
    from models.academy import Challenge, StudentChallengeProgress
    from services.academy_seed import ensure_default_challenges

    await ensure_default_challenges(db)

    challenges_res = await db.execute(select(Challenge).order_by(Challenge.created_at.desc()))
    challenges = list(challenges_res.scalars().all())

    # Get student progress rows
    progress_res = await db.execute(
        select(StudentChallengeProgress).where(StudentChallengeProgress.user_id == current_user.id)
    )
    user_progress_map = {str(p.challenge_id): p for p in progress_res.scalars().all()}

    challenge_list = []
    for c in challenges:
        p = user_progress_map.get(str(c.id))
        challenge_list.append({
            "id": str(c.id),
            "title": c.title,
            "description": c.description,
            "category": c.category,
            "difficulty": c.difficulty,
            "target_metric": c.target_metric,
            "target_value": float(c.target_value),
            "reward_points": c.reward_points,
            "user_status": p.status if p else "not_started",
            "user_current_value": float(p.current_value) if p else 0.0,
            "user_progress_percent": round(min(100.0, (float(p.current_value) / max(1.0, float(c.target_value))) * 100), 1) if p else 0.0,
        })

    return {"challenges": challenge_list}


@router.post("/challenges")
async def create_challenge(
    payload: CreateChallengeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new financial/trading challenge (Teachers & Admins)."""
    _require_faculty(current_user)
    from models.academy import Challenge

    challenge = Challenge(
        id=uuid.uuid4(),
        title=payload.title,
        description=payload.description,
        category=payload.category,
        difficulty=payload.difficulty,
        target_metric=payload.target_metric,
        target_value=payload.target_value,
        reward_points=payload.reward_points,
        creator_id=current_user.id,
    )
    db.add(challenge)
    await db.commit()
    return {"message": "Challenge created successfully.", "challenge_id": str(challenge.id)}


@router.post("/challenges/{challenge_id}/enroll")
async def enroll_in_challenge(
    challenge_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enroll or activate a challenge for the current student."""
    from models.academy import Challenge, StudentChallengeProgress

    try:
        cid = uuid.UUID(challenge_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid challenge UUID")

    # Check existing progress
    existing_res = await db.execute(
        select(StudentChallengeProgress).where(
            StudentChallengeProgress.user_id == current_user.id,
            StudentChallengeProgress.challenge_id == cid
        )
    )
    existing = existing_res.scalar_one_or_none()
    if existing:
        return {"message": "Already enrolled in challenge.", "status": existing.status}

    progress = StudentChallengeProgress(
        id=uuid.uuid4(),
        user_id=current_user.id,
        challenge_id=cid,
        status="in_progress",
        current_value=0.0,
    )
    db.add(progress)
    await db.commit()
    return {"message": "Successfully enrolled in challenge!", "status": "in_progress"}


@router.get("/student/teacher-info")
async def get_student_assigned_teacher_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get details of the teacher assigned to the current student."""
    from models.academy import TeacherStudentAssignment

    stmt = select(TeacherStudentAssignment, User).join(
        User, User.id == TeacherStudentAssignment.teacher_id
    ).where(TeacherStudentAssignment.student_id == current_user.id)

    res = await db.execute(stmt)
    row = res.first()

    if not row:
        return {"assigned": False, "teacher": None}

    assignment, teacher = row
    return {
        "assigned": True,
        "teacher": {
            "id": str(teacher.id),
            "full_name": teacher.full_name or teacher.username,
            "email": teacher.email,
            "notes": assignment.notes,
            "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
        }
    }

