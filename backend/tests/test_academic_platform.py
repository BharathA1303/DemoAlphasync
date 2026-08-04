# test_academic_platform.py - Unit tests for 3-Role Academic LLM Platform, Teacher-Student Assignment, and Challenges
import pytest
import uuid
from datetime import datetime, timezone
from models.user import User
from models.academy import TeacherStudentAssignment, Challenge, StudentChallengeProgress


@pytest.mark.asyncio
async def test_teacher_student_assignment_model():
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()

    assignment = TeacherStudentAssignment(
        id=uuid.uuid4(),
        teacher_id=teacher_id,
        student_id=student_id,
        notes="Test Batch 2026",
    )

    assert assignment.teacher_id == teacher_id
    assert assignment.student_id == student_id
    assert assignment.notes == "Test Batch 2026"


@pytest.mark.asyncio
async def test_challenge_model():
    challenge = Challenge(
        id=uuid.uuid4(),
        title="Risk Guard Challenge",
        description="Maintain drawdown < 5%",
        category="Risk Management",
        difficulty="Beginner",
        target_metric="max_drawdown",
        target_value=5.0,
        reward_points=150,
    )

    assert challenge.title == "Risk Guard Challenge"
    assert challenge.target_metric == "max_drawdown"
    assert float(challenge.target_value) == 5.0
    assert challenge.reward_points == 150


@pytest.mark.asyncio
async def test_student_challenge_progress_model():
    user_id = uuid.uuid4()
    challenge_id = uuid.uuid4()

    progress = StudentChallengeProgress(
        id=uuid.uuid4(),
        user_id=user_id,
        challenge_id=challenge_id,
        status="in_progress",
        current_value=2.5,
    )

    assert progress.user_id == user_id
    assert progress.status == "in_progress"
    assert float(progress.current_value) == 2.5


@pytest.mark.asyncio
async def test_ensure_user_academy_data_import():
    from services.academy_seed import ensure_user_academy_data, ensure_default_challenges
    from routes.academy import router
    assert ensure_user_academy_data is not None
    assert ensure_default_challenges is not None
    assert router is not None

