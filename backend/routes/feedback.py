import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from dependencies.admin import get_admin_user
from models.feedback import UserFeedback
from models.user import User
from routes.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("rating")
    @classmethod
    def _validate_rating(cls, value: int):
        if value < 1 or value > 5:
            raise ValueError("rating must be between 1 and 5")
        return value


@router.post("")
async def submit_feedback(
    payload: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(UserFeedback.id).where(UserFeedback.user_id == current_user.id).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Feedback already submitted")

    feedback = UserFeedback(
        user_id=current_user.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(feedback)
    await db.commit()

    return {"success": True, "message": "Thank you for your feedback!"}


@router.get("/check")
async def check_feedback_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserFeedback.id).where(UserFeedback.user_id == current_user.id).limit(1)
    )
    return {"has_submitted": result.scalar_one_or_none() is not None}


@router.get("/admin/summary")
async def get_feedback_summary(
    _admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    total_result = await db.execute(select(func.count(UserFeedback.id)))
    total_responses = int(total_result.scalar_one() or 0)

    avg_result = await db.execute(select(func.avg(UserFeedback.rating)))
    average_rating = float(avg_result.scalar_one() or 0.0)

    distribution_rows = await db.execute(
        select(UserFeedback.rating, func.count(UserFeedback.id)).group_by(
            UserFeedback.rating
        )
    )
    distribution = {str(i): 0 for i in range(1, 6)}
    for rating, count in distribution_rows.all():
        distribution[str(int(rating))] = int(count)

    recent_rows = await db.execute(
        select(UserFeedback)
        .order_by(UserFeedback.submitted_at.desc())
        .limit(50)
    )
    recent_feedback = [
        {
            "user_id": str(row.user_id),
            "rating": int(row.rating),
            "comment": row.comment,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        }
        for row in recent_rows.scalars().all()
    ]

    return {
        "total_responses": total_responses,
        "average_rating": average_rating,
        "distribution": distribution,
        "recent_feedback": recent_feedback,
    }