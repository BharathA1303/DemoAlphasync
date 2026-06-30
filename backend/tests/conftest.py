import pytest
import pytest_asyncio
import asyncio
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.connection import Base
from models.user import User
from models.portfolio import Portfolio
from models.watchlist import Watchlist, WatchlistItem
from models.order import Order
from models.broker import BrokerAccount
from models.algo import AlgoStrategy, AlgoTrade, AlgoLog
from models.futures_watchlist import FuturesWatchlist, FuturesWatchlistItem
from models.futures_order import FuturesOrder, FuturesPosition
from models.bug_report import BugReport
from models.feedback import UserFeedback
from engines.market_session import market_session
from config.settings import settings

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest_asyncio.fixture
async def db(test_engine):
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Enable after hours trading override so we can place orders in tests at any time
        market_session.set_after_hours_trading(True)
        yield session
        await session.rollback()

@pytest_asyncio.fixture
async def test_user(db):
    user = User(
        username="test_trader",
        email="test_trader@alphasync.com",
        full_name="Test Trader",
        virtual_capital=1000000.0,
    )
    db.add(user)
    await db.flush()
    
    portfolio = Portfolio(
        user_id=user.id,
        available_capital=1000000.0,
        total_invested=0.0,
        current_value=0.0,
        total_pnl=0.0,
        total_pnl_percent=0.0,
    )
    db.add(portfolio)
    await db.flush()
    return user

@pytest.fixture
def mock_market_data():
    from services.market_data import _format_symbol
    with patch("services.trading_engine.market_data") as mock:
        # Ensure get_quote_safe returns an AsyncMock
        mock.get_quote_safe = AsyncMock()
        mock._format_symbol.side_effect = _format_symbol
        yield mock
