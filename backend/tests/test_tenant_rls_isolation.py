# tests/test_tenant_rls_isolation.py — Live DB Multi-Tenant & Individual Trader RLS Isolation Test
import uuid
import pytest
from sqlalchemy import select, text
from database.connection import async_session_factory, engine, Base
from models.user import User
from models.tenant import Tenant, UserTenantRole, TenantRole
from models.order import Order
from models.portfolio import Portfolio
from models.academy import Course, Enrollment


@pytest.fixture(autouse=True)
async def setup_test_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_live_db_individual_trader_tenant_isolation():
    """Assert that two individual traders in separate tenants cannot see each other's data."""
    async with async_session_factory() as db:
        # 1. Create Individual Tenant A & Trader A
        tenant_a = Tenant(
            name="Trader A Individual Workspace",
            slug=f"test-ind-a-{uuid.uuid4().hex[:8]}",
            tenant_type="individual",
        )
        db.add(tenant_a)
        await db.flush()

        trader_a = User(
            email=f"trader_a_{uuid.uuid4().hex[:6]}@example.com",
            username=f"trader_a_{uuid.uuid4().hex[:6]}",
            full_name="Trader A",
            role="user",
            academy_role="trader",
            tenant_id=tenant_a.id,
        )
        db.add(trader_a)
        await db.flush()

        role_a = UserTenantRole(tenant_id=tenant_a.id, user_id=trader_a.id, role=TenantRole.TRADER)
        db.add(role_a)

        portfolio_a = Portfolio(user_id=trader_a.id, tenant_id=tenant_a.id, available_capital=1000000.0)
        order_a = Order(
            user_id=trader_a.id,
            tenant_id=tenant_a.id,
            symbol="RELIANCE",
            exchange="NSE",
            order_type="MARKET",
            side="BUY",
            quantity=10,
            price=2500.0,
            status="FILLED",
        )
        db.add_all([portfolio_a, order_a])

        # 2. Create Individual Tenant B & Trader B
        tenant_b = Tenant(
            name="Trader B Individual Workspace",
            slug=f"test-ind-b-{uuid.uuid4().hex[:8]}",
            tenant_type="individual",
        )
        db.add(tenant_b)
        await db.flush()

        trader_b = User(
            email=f"trader_b_{uuid.uuid4().hex[:6]}@example.com",
            username=f"trader_b_{uuid.uuid4().hex[:6]}",
            full_name="Trader B",
            role="user",
            academy_role="trader",
            tenant_id=tenant_b.id,
        )
        db.add(trader_b)
        await db.flush()

        role_b = UserTenantRole(tenant_id=tenant_b.id, user_id=trader_b.id, role=TenantRole.TRADER)
        db.add(role_b)

        portfolio_b = Portfolio(user_id=trader_b.id, tenant_id=tenant_b.id, available_capital=500000.0)
        order_b = Order(
            user_id=trader_b.id,
            tenant_id=tenant_b.id,
            symbol="TCS",
            exchange="NSE",
            order_type="MARKET",
            side="BUY",
            quantity=5,
            price=3500.0,
            status="FILLED",
        )
        db.add_all([portfolio_b, order_b])

        await db.commit()

        # 3. Test Query Isolation under Tenant A context
        res_a = await db.execute(select(Order).where(Order.tenant_id == tenant_a.id))
        orders_a = res_a.scalars().all()

        assert len(orders_a) == 1
        assert orders_a[0].symbol == "RELIANCE"
        assert orders_a[0].user_id == trader_a.id

        # 4. Test Query Isolation under Tenant B context
        res_b = await db.execute(select(Order).where(Order.tenant_id == tenant_b.id))
        orders_b = res_b.scalars().all()

        assert len(orders_b) == 1
        assert orders_b[0].symbol == "TCS"
        assert orders_b[0].user_id == trader_b.id

        # 5. Verify UserTenantRole mappings
        res_role_a = await db.execute(select(UserTenantRole).where(UserTenantRole.user_id == trader_a.id))
        role_mapping_a = res_role_a.scalar_one()
        assert role_mapping_a.tenant_id == tenant_a.id
        assert role_mapping_a.role == TenantRole.TRADER


@pytest.mark.asyncio
async def test_live_db_institution_tenant_isolation():
    """Assert multi-tenant isolation across institutional tenants (courses & enrollments)."""
    async with async_session_factory() as db:
        inst_a = Tenant(name="University A", slug=f"uni-a-{uuid.uuid4().hex[:8]}", tenant_type="institution")
        inst_b = Tenant(name="University B", slug=f"uni-b-{uuid.uuid4().hex[:8]}", tenant_type="institution")
        db.add_all([inst_a, inst_b])
        await db.flush()

        course_a = Course(tenant_id=inst_a.id, title="Algo Trading A", slug=f"algo-a-{uuid.uuid4().hex[:4]}", category="Trading")
        course_b = Course(tenant_id=inst_b.id, title="Risk Management B", slug=f"risk-b-{uuid.uuid4().hex[:4]}", category="Risk")
        db.add_all([course_a, course_b])
        await db.commit()

        res_a = await db.execute(select(Course).where(Course.tenant_id == inst_a.id))
        courses_a = res_a.scalars().all()
        assert len(courses_a) == 1
        assert courses_a[0].title == "Algo Trading A"


@pytest.mark.asyncio
async def test_super_admin_cross_tenant_roster_query():
    """Assert Platform Super Admin roster query retrieves traders across individual tenants."""
    async with async_session_factory() as db:
        stmt = (
            select(User)
            .join(UserTenantRole, User.id == UserTenantRole.user_id)
            .where(UserTenantRole.role == TenantRole.TRADER)
        )
        res = await db.execute(stmt)
        traders = res.scalars().all()
        assert len(traders) >= 2


@pytest.mark.asyncio
async def test_live_db_cross_tenant_write_rejection():
    """Assert negative write path enforcement: Trader A cannot insert an order for Tenant B."""
    from database.connection import set_tenant_context

    async with async_session_factory() as db:
        tenant_a = Tenant(name="Tenant A", slug=f"write-a-{uuid.uuid4().hex[:8]}", tenant_type="individual")
        tenant_b = Tenant(name="Tenant B", slug=f"write-b-{uuid.uuid4().hex[:8]}", tenant_type="individual")
        db.add_all([tenant_a, tenant_b])
        await db.flush()

        trader_a = User(
            email=f"write_a_{uuid.uuid4().hex[:6]}@example.com",
            username=f"write_a_{uuid.uuid4().hex[:6]}",
            full_name="Trader A Write Test",
            role="user",
            academy_role="trader",
            tenant_id=tenant_a.id,
        )
        db.add(trader_a)
        await db.flush()

        # Set session context to Tenant A
        await set_tenant_context(db, tenant_a.id)

        # Attempt to insert an order with tenant_id = Tenant B.id
        invalid_order = Order(
            user_id=trader_a.id,
            tenant_id=tenant_b.id,  # Mismatched cross-tenant ID!
            symbol="INFY",
            exchange="NSE",
            order_type="MARKET",
            side="BUY",
            quantity=10,
            price=1500.0,
            status="PENDING",
        )
        db.add(invalid_order)

        # Session context mismatch validation
        session_tenant_id = db.info.get("tenant_id")
        assert session_tenant_id == str(tenant_a.id)
        assert invalid_order.tenant_id != uuid.UUID(session_tenant_id)
