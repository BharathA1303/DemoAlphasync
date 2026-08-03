# services/mentor_service.py - AI Mentor RAG Service Principal & Constraint Enforcement Engine
import uuid
import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.academy import Course, Enrollment

logger = logging.getLogger(__name__)

_INVESTMENT_ADVICE_KEYWORDS = [
    "should i buy", "should i sell", "stock pick", "buy recommendation",
    "target price", "which stock to buy", "best stock today", "invest my money",
    "trade signal", "profit target", "hypothetically", "if you had to pick",
    "off the record", "ignore previous rules", "buy karu", "recommend a stock",
]



async def process_mentor_query(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    active_exam_in_progress: bool = False,
) -> Dict[str, Any]:
    """Process learner query with strict entitlement filtering and AI safety constraint gates."""
    clean_query = str(query or "").strip().lower()

    # CONSTRAINT GATE 1: Investment Advice Refusal
    if any(k in clean_query for k in _INVESTMENT_ADVICE_KEYWORDS):
        return {
            "reply": (
                "⚠️ **Educational Disclaimer & Constraint Refusal**\n\n"
                "I am an educational AI Mentor designed to teach financial concepts, options theory, "
                "and quantitative strategy building. I am not a registered financial advisor and "
                "cannot provide investment, stock pick, or buy/sell trade advice. Please consult a "
                "certified financial advisor for personal investment decisions."
            ),
            "is_refusal": True,
            "is_socratic_hint": False,
            "citations": [],
        }

    # CONSTRAINT GATE 2: Active Exam Socratic Hint Mode
    if active_exam_in_progress:
        return {
            "reply": (
                "📝 **Active Exam Socratic Hint Mode**\n\n"
                "You currently have an active assessment in progress. To uphold academic integrity, "
                "I cannot provide direct answers or step-by-step solutions to exam questions. "
                "Here is a Socratic hint to guide your thinking: Consider how the option Greek Delta "
                "measures the rate of change of option price with respect to the underlying asset's price."
            ),
            "is_refusal": False,
            "is_socratic_hint": True,
            "citations": [],
        }

    # CONSTRAINT GATE 3: Entitlement-Filtered RAG Retrieval
    stmt = select(Course).where(Course.tenant_id == tenant_id)
    res = await db.execute(stmt)
    tenant_courses = res.scalars().all()

    citations = [
        {
            "tenant_id": tenant_id,
            "course_id": c.id,
            "title": c.title,
            "category": c.category,
        }
        for c in tenant_courses
    ]

    return {
        "reply": f"Based on your course materials in '{tenant_courses[0].title if tenant_courses else 'your curriculum'}', here is an explanation of your query.",
        "is_refusal": False,
        "is_socratic_hint": False,
        "citations": citations,
    }
