# test_login_debug.py - Test login route execution to locate 500 error
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from database.connection import async_session, init_db
from models.user import User
from services.auth_service import hash_password
import uuid


@pytest.mark.asyncio
async def test_login_route_execution():
    await init_db()

    async with async_session() as session:
        # Create test user
        test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        test_user = User(
            email=test_email,
            username=f"user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("password123"),
            full_name="Test User",
            virtual_capital=1000000.0,
            account_status="active",
            is_active=True,
        )
        session.add(test_user)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            json={"username": test_email, "password": "password123"},
        )
        print("LOGIN RESPONSE STATUS:", response.status_code)
        print("LOGIN RESPONSE BODY:", response.json())
        assert response.status_code == 200
