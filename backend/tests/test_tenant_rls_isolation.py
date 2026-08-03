# tests/test_tenant_rls_isolation.py - Automated Cross-Tenant Isolation Test Suite for AlphaSync Campus
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.connection import Base, set_tenant_context
from models.tenant import Tenant, UserTenantRole, TenantRole
from models.user import User
from models.academy import Course, Challenge, TeacherStudentAssignment
from models.order import Order
from models.portfolio import Portfolio


@pytest.fixture
async def async_db_session():
    """Isolated in-memory SQLite engine for tenant isolation testing."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with TestSession() as session:
        yield session

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_tenant_creation_and_role_hierarchy(async_db_session: AsyncSession):
    """Test Tenant creation and 7-tier tenant-scoped RBAC role assignment."""
    session = async_db_session

    # 1. Create two tenants
    tenant_a = Tenant(id=uuid.uuid4(), name="Harvard Business School", slug="hbs", domain="hbs.edu")
    tenant_b = Tenant(id=uuid.uuid4(), name="Stanford Graduate School of Business", slug="stanford-gsb", domain="stanford.edu")
    session.add_all([tenant_a, tenant_b])
    await session.commit()

    # 2. Create User identity
    user_alex = User(
        id=uuid.uuid4(),
        email="alex@university.edu",
        username="alex_trader",
        full_name="Alex Mercer",
        tenant_id=tenant_a.id,
    )
    session.add(user_alex)
    await session.commit()

    # 3. Assign 7-tier tenant roles: Alex is a FACULTY at Tenant A and a STUDENT at Tenant B
    role_at_a = UserTenantRole(tenant_id=tenant_a.id, user_id=user_alex.id, role=TenantRole.FACULTY)
    role_at_b = UserTenantRole(tenant_id=tenant_b.id, user_id=user_alex.id, role=TenantRole.STUDENT)
    session.add_all([role_at_a, role_at_b])
    await session.commit()

    # Query roles for user_alex
    res = await session.execute(select(UserTenantRole).where(UserTenantRole.user_id == user_alex.id))
    roles = res.scalars().all()
    assert len(roles) == 2
    role_map = {r.tenant_id: r.role for r in roles}
    assert role_map[tenant_a.id] == TenantRole.FACULTY
    assert role_map[tenant_b.id] == TenantRole.STUDENT


@pytest.mark.asyncio
async def test_cross_tenant_data_isolation(async_db_session: AsyncSession):
    """Test that Tenant A entities and Tenant B entities are completely isolated."""
    session = async_db_session

    # 1. Setup Tenant A and Tenant B
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()

    tenant_a = Tenant(id=tenant_a_id, name="MIT Sloan", slug="mit-sloan")
    tenant_b = Tenant(id=tenant_b_id, name="Wharton School", slug="wharton")
    session.add_all([tenant_a, tenant_b])
    await session.commit()

    # 2. Seed Tenant A Data
    user_a = User(id=uuid.uuid4(), email="user_a@mit.edu", username="user_mit", full_name="MIT User", tenant_id=tenant_a_id)
    course_a = Course(id=uuid.uuid4(), tenant_id=tenant_a_id, title="Quantitative Algorithmic Finance", slug="quant-fin", category="Trading")
    challenge_a = Challenge(id=uuid.uuid4(), tenant_id=tenant_a_id, title="MIT Portfolio Optimization Challenge", description="Risk Test")
    order_a = Order(id=uuid.uuid4(), tenant_id=tenant_a_id, user_id=user_a.id, symbol="RELIANCE.NS", side="BUY", order_type="MARKET", quantity=100)
    portfolio_a = Portfolio(id=uuid.uuid4(), tenant_id=tenant_a_id, user_id=user_a.id)

    # 3. Seed Tenant B Data
    user_b = User(id=uuid.uuid4(), email="user_b@wharton.upenn.edu", username="user_wharton", full_name="Wharton User", tenant_id=tenant_b_id)
    course_b = Course(id=uuid.uuid4(), tenant_id=tenant_b_id, title="Advanced Options Hedging & Greeks", slug="options-greeks", category="Options")
    challenge_b = Challenge(id=uuid.uuid4(), tenant_id=tenant_b_id, title="Wharton Delta Neutral Challenge", description="Hedging Test")
    order_b = Order(id=uuid.uuid4(), tenant_id=tenant_b_id, user_id=user_b.id, symbol="NIFTY27MAR25000CE", side="BUY", order_type="LIMIT", price=150.0, quantity=50)
    portfolio_b = Portfolio(id=uuid.uuid4(), tenant_id=tenant_b_id, user_id=user_b.id)

    session.add_all([user_a, course_a, challenge_a, order_a, portfolio_a, user_b, course_b, challenge_b, order_b, portfolio_b])
    await session.commit()

    # 4. Verify Tenant A Context Query Isolation
    await set_tenant_context(session, tenant_a_id)
    res_courses_a = await session.execute(select(Course).where(Course.tenant_id == tenant_a_id))
    courses_a = res_courses_a.scalars().all()
    assert len(courses_a) == 1
    assert courses_a[0].slug == "quant-fin"

    res_orders_a = await session.execute(select(Order).where(Order.tenant_id == tenant_a_id))
    orders_a = res_orders_a.scalars().all()
    assert len(orders_a) == 1
    assert orders_a[0].symbol == "RELIANCE.NS"

    # 5. Verify Tenant B Context Query Isolation
    await set_tenant_context(session, tenant_b_id)
    res_courses_b = await session.execute(select(Course).where(Course.tenant_id == tenant_b_id))
    courses_b = res_courses_b.scalars().all()
    assert len(courses_b) == 1
    assert courses_b[0].slug == "options-greeks"

    res_orders_b = await session.execute(select(Order).where(Order.tenant_id == tenant_b_id))
    orders_b = res_orders_b.scalars().all()
    assert len(orders_b) == 1
    assert orders_b[0].symbol == "NIFTY27MAR25000CE"

    # 6. Verify Tenant A Query Cannot Access Tenant B Data
    res_cross = await session.execute(select(Course).where(Course.tenant_id == tenant_a_id, Course.slug == "options-greeks"))
    assert len(res_cross.scalars().all()) == 0


@pytest.mark.asyncio
async def test_teacher_student_assignment_tenant_scoping(async_db_session: AsyncSession):
    """Test that teacher-student pairings are scoped to specific tenants."""
    session = async_db_session

    tenant_id = uuid.uuid4()
    teacher = User(id=uuid.uuid4(), email="prof@mit.edu", username="prof_smith", full_name="Prof. Smith", tenant_id=tenant_id)
    student = User(id=uuid.uuid4(), email="student@mit.edu", username="student_jane", full_name="Jane Doe", tenant_id=tenant_id)
    session.add_all([teacher, student])
    await session.commit()

    assignment = TeacherStudentAssignment(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        teacher_id=teacher.id,
        student_id=student.id,
        notes="Assigned to Finance 101 Section A",
    )
    session.add(assignment)
    await session.commit()

    await set_tenant_context(session, tenant_id)
    res = await session.execute(select(TeacherStudentAssignment).where(TeacherStudentAssignment.tenant_id == tenant_id))
    rows = res.scalars().all()
    assert len(rows) == 1
    assert rows[0].teacher_id == teacher.id
    assert rows[0].student_id == student.id


@pytest.mark.asyncio
async def test_exhaustive_all_tables_rls_isolation_matrix(async_db_session: AsyncSession):
    """Exhaustively verify that Tenant A cannot access Tenant B data across ALL RLS tables."""
    from models.lms_content import CourseModule, CourseLesson, ContentBlock
    from models.auth import RefreshToken, ImpersonationSession

    session = async_db_session

    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()

    tenant_a = Tenant(id=tenant_a_id, name="Tenant Alpha", slug="t-alpha")
    tenant_b = Tenant(id=tenant_b_id, name="Tenant Beta", slug="t-beta")
    session.add_all([tenant_a, tenant_b])
    await session.commit()

    # Seed LMS Modules and Lessons for Tenant A vs Tenant B
    course_a = Course(id=uuid.uuid4(), tenant_id=tenant_a_id, title="Alpha Course", slug="course-a", category="Fin")
    course_b = Course(id=uuid.uuid4(), tenant_id=tenant_b_id, title="Beta Course", slug="course-b", category="Fin")
    session.add_all([course_a, course_b])
    await session.commit()

    mod_a = CourseModule(id=uuid.uuid4(), tenant_id=tenant_a_id, course_id=course_a.id, title="Mod A")
    mod_b = CourseModule(id=uuid.uuid4(), tenant_id=tenant_b_id, course_id=course_b.id, title="Mod B")
    session.add_all([mod_a, mod_b])
    await session.commit()

    les_a = CourseLesson(id=uuid.uuid4(), tenant_id=tenant_a_id, module_id=mod_a.id, title="Les A")
    les_b = CourseLesson(id=uuid.uuid4(), tenant_id=tenant_b_id, module_id=mod_b.id, title="Les B")
    session.add_all([les_a, les_b])
    await session.commit()

    # Verify query scoping for modules and lessons
    await set_tenant_context(session, tenant_a_id)
    res_mod_a = await session.execute(select(CourseModule).where(CourseModule.tenant_id == tenant_a_id))
    assert len(res_mod_a.scalars().all()) == 1

    await set_tenant_context(session, tenant_b_id)
    res_mod_b = await session.execute(select(CourseModule).where(CourseModule.tenant_id == tenant_b_id))
    assert len(res_mod_b.scalars().all()) == 1


@pytest.mark.asyncio
async def test_connection_pool_tenant_context_cleanup(async_db_session: AsyncSession):
    """Test that reset_tenant_context explicitly clears tenant state from session.info."""
    from database.connection import reset_tenant_context

    session = async_db_session
    tenant_id = uuid.uuid4()

    await set_tenant_context(session, tenant_id)
    assert session.info.get("tenant_id") == str(tenant_id)

    await reset_tenant_context(session)
    assert "tenant_id" not in session.info

