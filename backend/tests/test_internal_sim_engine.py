"""
Verification test for the internal simulation engine rewrite: confirms the
direct in-process session create/subscribe/start/listen path (replacing the
old TickAlphaProvider's HTTP/JWT/WebSocket self-call) actually works end to
end against a real database, using the project's existing test_engine/db
fixtures (see conftest.py) which correctly share one SQLite connection.
"""
import asyncio
from datetime import date

import pytest

from data_layer.db.models import PriceData


@pytest.fixture(autouse=True)
def _patch_data_layer_db_session(test_engine, monkeypatch):
    """Point data_layer's session factory (used by simulator_manager,
    routes_sessions, brownian_bridge, delay_gate) at the shared test engine,
    same as the app's real config wires data_layer to the main app's DB."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    import data_layer.db.session as dl_session

    test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dl_session, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(dl_session, "async_engine", test_engine)

    import data_layer.core.cache as dl_cache
    monkeypatch.setattr(dl_cache, "redis_client", None)

    return test_session_factory


@pytest.mark.asyncio
async def test_create_subscribe_start_and_receive_ticks(db, _patch_data_layer_db_session):
    """Full path: seed EOD data, create a session, subscribe, start the
    clock, register a direct listener queue, advance one tick, and confirm
    the listener receives real simulated tick data — with no HTTP/JWT/
    WebSocket hop anywhere in this path."""
    row = PriceData(
        symbol="RELIANCE", exchange="NSE", segment="EQ",
        expiry=date(1970, 1, 1), strike=0.0, option_type="XX",
        open_interest=0, market_timestamp=date(2026, 6, 25),
        open=2500.0, high=2550.0, low=2480.0, close=2530.0, volume=1000000,
        version=1,
    )
    db.add(row)
    await db.flush()

    from services.internal_sim_engine import (
        create_replay_session,
        subscribe_session_symbols,
        start_session_clock,
        register_local_listener,
        unregister_local_listener,
    )

    session_state = await create_replay_session(date(2026, 6, 25), replay_speed=60)
    session_id = session_state["session_id"]
    assert session_state["status"] == "paused"

    state = await subscribe_session_symbols(db, session_id, ["NSE:EQ:RELIANCE"])
    assert "NSE:EQ:RELIANCE" in state["subscriptions"]

    started = await start_session_clock(session_id)
    assert started["status"] == "active"

    q = asyncio.Queue(maxsize=256)
    register_local_listener(session_id, q)
    try:
        from data_layer.simulator.simulator_manager import simulator_manager
        await simulator_manager.process_active_session(session_id)

        message = await asyncio.wait_for(q.get(), timeout=5.0)
        assert message["type"] == "tick_update"
        ticks = message.get("ticks", {})
        assert "NSE:EQ:RELIANCE" in ticks
        assert len(ticks["NSE:EQ:RELIANCE"]) > 0
        first_tick = ticks["NSE:EQ:RELIANCE"][0]
        assert "p" in first_tick and "v" in first_tick
        assert 2480.0 <= first_tick["p"] <= 2550.0
    finally:
        unregister_local_listener(session_id, q)


@pytest.mark.asyncio
async def test_compliance_delay_gate_rejects_recent_date(db, _patch_data_layer_db_session):
    """The 3-day compliance delay gate must still reject too-recent dates
    through the new direct-call path, exactly as it did through the old
    HTTP route."""
    from datetime import timedelta
    from data_layer.core.delay_gate import get_delay_cutoff
    from services.internal_sim_engine import create_replay_session

    cutoff = get_delay_cutoff()
    too_recent = cutoff + timedelta(days=1)

    with pytest.raises(ValueError, match="restricted"):
        await create_replay_session(too_recent, replay_speed=1)


@pytest.mark.asyncio
async def test_get_latest_eligible_price_direct(db, _patch_data_layer_db_session):
    """Direct equivalent of GET /v1/price/{exchange}/{symbol} returns the
    same shape of data without any HTTP round-trip."""
    row = PriceData(
        symbol="TCS", exchange="NSE", segment="EQ",
        expiry=date(1970, 1, 1), strike=0.0, option_type="XX",
        open_interest=0, market_timestamp=date(2026, 6, 25),
        open=3800.0, high=3850.0, low=3780.0, close=3820.0, volume=500000,
        version=1,
    )
    db.add(row)
    await db.flush()

    from services.internal_sim_engine import get_latest_eligible_price

    result = await get_latest_eligible_price(db, "NSE", "TCS", "EQ")
    assert result is not None
    assert result["close"] == 3820.0
