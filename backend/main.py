# main.py - Entry point for AlphaSync backend API server
import asyncio
import uuid
import logging
from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config.settings import settings
from database.connection import init_db, async_session_factory
from websocket.manager import manager

# ── New Architecture Imports ────────────────────────────────────────
from core.event_bus import event_bus, EventType, Event
from engines.market_session import market_session
from workers.market_worker import market_data_worker
from workers.order_worker import order_execution_worker
from workers.futures_order_worker import futures_order_worker
from workers.futures_expiry_worker import futures_expiry_worker
from workers.algo_worker import algo_strategy_worker
from workers.portfolio_worker import portfolio_recalc_worker
from workers.squareoff_worker import auto_squareoff_worker
from core.rate_limiter import RateLimitMiddleware
from websocket.futures_stream import futures_stream_manager
from strategies.zeroloss.manager import zeroloss_manager
from workers.access_expiry_worker import access_expiry_worker

# ── Broker Session Manager (per-user providers) ────────────────────
from services.broker_session import broker_session_manager

# ── Master Zebu Session (shared market data for all users) ──────────
from services.master_session import master_session_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ─────────────────────────────────────────────────────
    logger.info("Starting AlphaSync...")

    # ── Initialize Firebase Admin SDK ───────────────────────────────
    from config.firebase import init_firebase

    try:
        init_firebase()
        logger.info("Firebase Admin SDK initialized")
    except Exception as e:
        logger.error(f"Firebase init failed: {e} — auth will not work!")

    await init_db()

    # ── Initialize Redis (for price cache, shared across sessions) ──
    try:
        from cache.redis_client import get_redis

        await get_redis(settings.REDIS_URL)
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis initialization failed: {e}")

    # ── Load Zebu master contracts (NSE and BSE equities via live Zebu CDN) ──
    try:
        from services.contract_loader import get_nse_contracts_cached
        from providers.symbol_mapper import load_zebu_contracts

        # Fetch NSE contracts (cached for on-demand symbol registration)
        nse_contracts = await get_nse_contracts_cached()
        if nse_contracts:
            nse_count = load_zebu_contracts(nse_contracts)
            logger.info(f"Zebu NSE master contracts loaded: {nse_count} equity symbols")
        else:
            logger.warning("Zebu NSE contracts CDN unavailable")

        # Fetch BSE contracts for SENSEX constituents and other BSE stocks
        bse_contracts = await fetch_zebu_contracts("BSE")
        if bse_contracts:
            bse_count = load_zebu_contracts(bse_contracts)
            logger.info(f"Zebu BSE master contracts loaded: {bse_count} equity symbols")
        else:
            logger.warning("Zebu BSE contracts CDN unavailable")

        if not (nse_contracts or bse_contracts):
            logger.warning(
                "Zebu master contracts CDN unavailable — "
                "symbols will be resolved on-demand via SearchScrip API"
            )
    except Exception as e:
        logger.warning(
            f"Zebu contract load failed — on-demand SearchScrip will handle resolution: {e}"
        )

    # ── Load MCX/NCDEX commodity contracts (near-expiry FUT tokens for GOLD, SILVER, etc.) ──
    try:
        from services.contract_loader import fetch_commodity_contracts
        from providers.symbol_mapper import (
            load_zebu_contracts as _load_commodity_contracts,
        )

        commodity_contracts = await fetch_commodity_contracts()
        if commodity_contracts:
            count = _load_commodity_contracts(commodity_contracts)
            logger.info(
                f"MCX/NCDEX commodity contracts loaded: {count} symbols pre-registered"
            )

            # Dump full commodity token map for live debugging
            try:
                from providers.symbol_mapper import dump_commodity_token_map
                dump_commodity_token_map()
            except Exception:
                pass

            # Commodity symbols will be subscribed to each user's WS on demand
            # when they connect their broker account.
        else:
            logger.warning(
                "MCX/NCDEX commodity contracts CDN unavailable — "
                "commodity quotes will fall back to SearchScrip on first access"
            )
    except Exception as e:
        logger.warning(f"MCX/NCDEX commodity contract load failed: {e}")

    # ── Load Zebu futures contracts (NSE equities and indices) ──────────────
    try:
        from services.futures_service import initialize_futures

        await initialize_futures()
        logger.info("Zebu NSE futures contracts loaded")

        # Initialize the centralized contract registry from loaded data
        from services.futures_contract_registry import futures_contract_registry
        await futures_contract_registry.initialize()
    except Exception as e:
        logger.warning(f"Futures contracts load failed: {e}")

    # ── Restore broker sessions from DB ─────────────────────────────
    # No global provider. Sessions are per-user, created after OAuth.
    # At startup, restore any previously active sessions.
    restored = await broker_session_manager.restore_sessions()
    logger.info(
        f"Broker sessions: {restored} restored | "
        f"No global provider — market data flows after broker auth"
    )

    # ── Startup diagnostics ────────────────────────────────────────────
    logger.info("=" * 70)
    logger.info("ALPHASYNC STARTUP DIAGNOSTICS")
    logger.info("=" * 70)
    logger.info("Broker model: per-user (Zebu / Alice Blue / Zerodha — connect own account)")

    # Check broker sessions
    active_session_count = broker_session_manager.session_count()
    logger.info(f"Active Broker Sessions: {active_session_count}")

    # Check futures contracts
    from services.futures_service import _futures_contracts_loaded

    total_futures = (
        sum(
            len(v)
            for v in __import__(
                "services.futures_service", fromlist=["_futures_contracts"]
            )._futures_contracts.values()
        )
        if _futures_contracts_loaded
        else 0
    )
    logger.info(f"Futures Contracts Available: {total_futures} total")

    # Check NSE API accessibility
    try:
        from services.nse_options_service import _fetch_nse

        test_nse = await _fetch_nse("option-chain-indices?symbol=NIFTY")
        nse_status = "ACCESSIBLE" if test_nse else "UNAVAILABLE"
    except Exception as e:
        nse_status = f"ERROR: {str(e)[:50]}"
    logger.info(f"NSE Options API: {nse_status}")

    logger.info("=" * 70)
    logger.info("DATA AVAILABILITY SUMMARY:")
    logger.info(
        f"- Futures data: {'ENABLED' if total_futures > 0 else 'LIMITED - live provider unavailable'}"
    )
    logger.info(f"- Options data: ENABLED (NSE API)")
    logger.info("- Commodities: ENABLED (Zebu live with cache fallback, broker optional)")
    logger.info("=" * 70)

    # Start the Event Bus dispatcher (must be first)
    background_tasks = [
        asyncio.create_task(event_bus.run()),
    ]

    # Wire event-driven workers (subscribe BEFORE starting emitters)
    event_bus.subscribe(EventType.ORDER_FILLED, portfolio_recalc_worker.on_order_filled)

    # Wire WebSocket manager as event listener for real-time updates
    event_bus.subscribe(EventType.PRICE_UPDATED, manager.on_price_event)
    event_bus.subscribe(EventType.PRICE_UPDATED, order_execution_worker.on_price_event)
    event_bus.subscribe(EventType.FUTURES_QUOTE, manager.on_futures_quote_event)
    event_bus.subscribe(EventType.FUTURES_QUOTE, futures_order_worker.on_futures_tick)
    event_bus.subscribe(EventType.ORDER_PLACED, manager.on_order_event)
    event_bus.subscribe(EventType.ORDER_FILLED, manager.on_order_event)
    event_bus.subscribe(EventType.ORDER_CANCELLED, manager.on_order_event)
    event_bus.subscribe(EventType.ORDER_EXPIRED, manager.on_order_event)
    event_bus.subscribe(EventType.FUTURES_ORDER_PLACED, manager.on_futures_order_event)
    event_bus.subscribe(EventType.FUTURES_ORDER_FILLED, manager.on_futures_order_event)
    event_bus.subscribe(
        EventType.FUTURES_ORDER_CANCELLED, manager.on_futures_order_event
    )
    event_bus.subscribe(EventType.FUTURES_ORDER_EXPIRED, manager.on_futures_order_event)
    event_bus.subscribe(EventType.PORTFOLIO_UPDATED, manager.on_portfolio_event)
    event_bus.subscribe(EventType.ALGO_TRADE, manager.on_algo_event)
    event_bus.subscribe(EventType.ALGO_SIGNAL, manager.on_algo_event)
    event_bus.subscribe(EventType.ALGO_ERROR, manager.on_algo_event)

    # Start FuturesStreamManager (cleanup loop, contract lifecycle)
    futures_stream_manager.start()

    # Phase 2 — central quote coordination (stale recovery + live snapshots)
    try:
        from market.quote_coordinator import quote_coordinator
        from market.stale_symbol_detector import stale_symbol_detector
        from market.quote_snapshot_engine import quote_snapshot_engine
        from engines.market_session import market_session, MarketState

        async def _provider_resubscribe(sym: str, _reason: str) -> None:
            await manager._provider_subscribe([sym])

        quote_coordinator.register_recovery_handler(_provider_resubscribe)
        stale_symbol_detector.configure(
            recovery_callback=quote_coordinator.recover_symbol,
            get_last_tick_at=quote_coordinator.get_last_tick_at,
            is_market_open=lambda: market_session.get_current_state() == MarketState.OPEN,
        )
        quote_snapshot_engine.configure(
            get_authority_quotes=quote_coordinator.get_authority_quotes,
        )
        background_tasks.append(asyncio.create_task(stale_symbol_detector.run()))
        background_tasks.append(asyncio.create_task(quote_snapshot_engine.run()))
        logger.info("Quote coordinator + stale detector + snapshot engine started")
    except Exception as e:
        logger.warning(f"Phase 2 quote infrastructure skipped: {e}")

    # Start background workers
    # Restore users who had ZeroLoss enabled before process restart.
    # Never restore strategy workers when session is not live OPEN.
    from engines.market_session import market_session, MarketState
    if market_session.get_current_state() == MarketState.OPEN:
        restored_users = await zeroloss_manager.restore_enabled_users()
        if restored_users:
            logger.info(
                "ZeroLoss manager restored %d users from persisted state", restored_users
            )
        else:
            logger.info("ZeroLoss manager ready — waiting for users to start via UI")
    else:
        logger.info(
            "ZeroLoss restore skipped — market session is %s",
            market_session.get_current_state().value,
        )
    background_tasks.extend(
        [
            asyncio.create_task(market_data_worker.run()),
            asyncio.create_task(order_execution_worker.run()),
            asyncio.create_task(futures_order_worker.run()),
            asyncio.create_task(futures_expiry_worker.run()),
            asyncio.create_task(algo_strategy_worker.run()),
            asyncio.create_task(auto_squareoff_worker.run()),
            asyncio.create_task(access_expiry_worker.run()),
        ]
    )

    try:
        from services.market_eod_reconciliation import (
            market_session_transition,
            schedule_reconcile_market_close,
        )
        from engines.market_session import MarketState

        background_tasks.append(asyncio.create_task(market_session_transition.run()))
        if market_session.get_current_state() != MarketState.OPEN:
            schedule_reconcile_market_close(reason="startup_closed")
        logger.info("Market EOD reconciliation + session transition engine started")
    except Exception as e:
        logger.warning(f"EOD reconciliation engine skipped: {e}")

    # Start broker session health check (monitors token expiry)
    await broker_session_manager.start_health_check(interval=300.0)

    # Emit system startup event
    await event_bus.emit(
        Event(
            type=EventType.SYSTEM_STARTUP,
            data={
                "workers": [
                    "event_bus",
                    "market_data",
                    "order_execution",
                    "algo_strategy",
                    "zeroloss_manager",
                ],
                "architecture": "per-user-provider",
            },
            source="main",
        )
    )

    logger.info(
        f"AlphaSync started | Workers: 5 | "
        f"Market Session: {market_session.get_current_state().value} | "
        f"Simulation Mode: {market_session.simulation_mode} | "
        f"Architecture: per-user-provider"
    )
    yield

    # ── Shutdown ────────────────────────────────────────────────────
    logger.info("Shutting down AlphaSync...")
    await event_bus.emit(Event(type=EventType.SYSTEM_SHUTDOWN, source="main"))

    try:
        from market.stale_symbol_detector import stale_symbol_detector
        from market.quote_snapshot_engine import quote_snapshot_engine

        await stale_symbol_detector.stop()
        await quote_snapshot_engine.stop()
    except Exception:
        pass

    # Stop workers gracefully
    await market_data_worker.stop()
    await order_execution_worker.stop()
    await algo_strategy_worker.stop()
    await zeroloss_manager.stop_all()
    await auto_squareoff_worker.stop()
    await broker_session_manager.stop()
    await event_bus.stop()

    # Close Redis
    try:
        from cache.redis_client import close_redis

        await close_redis()
    except Exception:
        pass

    # Cancel all background tasks
    for task in background_tasks:
        task.cancel()

    logger.info("AlphaSync shut down")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Professional Indian Stock Market Simulation Trading Platform",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (added after CORS so rate limit responses also get CORS headers)
app.add_middleware(RateLimitMiddleware)

# Import and include routers
from routes.auth import router as auth_router
from routes.market import router as market_router
from routes.orders import router as orders_router
from routes.portfolio import router as portfolio_router
from routes.watchlist import router as watchlist_router
from routes.futures_watchlist import router as futures_watchlist_router
from routes.algo import router as algo_router
from routes.user import router as user_router
from routes.zeroloss import router as zeroloss_router
from routes.broker import router as broker_router
from routes.admin import router as admin_router
from routes.futures import router as futures_router
from routes.options import router as options_router
from routes.mentor import router as mentor_router
from routes.bug_reports import router as bug_reports_router
from routes.feedback import router as feedback_router

app.include_router(auth_router)
app.include_router(market_router)
app.include_router(orders_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)
app.include_router(futures_watchlist_router)
app.include_router(algo_router)
app.include_router(user_router)
app.include_router(zeroloss_router)
app.include_router(broker_router)
app.include_router(admin_router)
app.include_router(futures_router)
app.include_router(options_router)
app.include_router(mentor_router)
app.include_router(bug_reports_router)
app.include_router(feedback_router)

# ── Serve uploaded files (avatars etc.) ───────────────────────────────────────
os.makedirs("uploads/avatars", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }


@app.get("/api/health")
async def health():
    """Enhanced health endpoint with worker, engine, and session status."""
    import config.firebase as fb_mod
    import os

    creds_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "")
    creds_json_set = bool(os.environ.get("FIREBASE_CREDENTIALS_JSON", ""))
    creds_file_exists = os.path.isfile(creds_path) if creds_path else False
    creds_file_size = os.path.getsize(creds_path) if creds_file_exists else 0
    creds_readable = os.access(creds_path, os.R_OK) if creds_file_exists else False

    # Try to diagnose Firebase init failure
    firebase_error = None
    if not fb_mod._initialized:
        try:
            fb_mod.init_firebase()
        except Exception as e:
            firebase_error = f"{type(e).__name__}: {e}"

    return {
        "status": "healthy",
        "firebase": {
            "initialized": fb_mod._initialized,
            "init_error": firebase_error,
            "credentials_path": creds_path,
            "credentials_file_exists": creds_file_exists,
            "credentials_file_readable": creds_readable,
            "credentials_file_size": creds_file_size,
            "credentials_json_env_set": creds_json_set,
            "process_uid": os.getuid() if hasattr(os, "getuid") else "N/A",
        },
        "market_session": market_session.get_session_info(),
        "event_bus": event_bus.get_stats(),
        "broker_sessions": broker_session_manager.get_status(),
        "master_session": {
            "active": master_session_service.is_active(),
            "user_id": settings.ZEBU_MASTER_USER_ID or "not_configured",
        },
        "workers": {
            "market_data": market_data_worker.get_stats(),
            "order_execution": order_execution_worker.get_stats(),
            "algo_strategy": algo_strategy_worker.get_stats(),
            "portfolio_recalc": portfolio_recalc_worker.get_stats(),
            "zeroloss": zeroloss_manager.get_stats(),
            "auto_squareoff": auto_squareoff_worker.get_stats(),
        },
        "caches": _get_cache_stats(),
    }


def _get_cache_stats() -> dict:
    try:
        from cache.smart_cache import get_all_cache_stats

        return get_all_cache_stats()
    except Exception:
        return {}


@app.get("/api/debug/db")
async def debug_db():
    """Temporary diagnostic endpoint — test DB connectivity and schema."""
    import traceback
    from database.connection import async_session
    from sqlalchemy import text as sa_text, inspect as sa_inspect

    results = {}

    try:
        async with async_session() as session:
            # Test basic connectivity
            row = await session.execute(sa_text("SELECT 1"))
            results["db_connected"] = True

            # Check if users table exists and its columns
            cols = await session.execute(
                sa_text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'users' ORDER BY ordinal_position"
                )
            )
            columns = [{"name": r[0], "type": r[1]} for r in cols.fetchall()]
            results["users_table_columns"] = columns
            results["has_firebase_uid"] = any(
                c["name"] == "firebase_uid" for c in columns
            )
            results["has_auth_provider"] = any(
                c["name"] == "auth_provider" for c in columns
            )

            # Check portfolios table
            pcols = await session.execute(
                sa_text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'portfolios' ORDER BY ordinal_position"
                )
            )
            results["portfolios_columns"] = [r[0] for r in pcols.fetchall()]

            # Check alembic version
            try:
                ver = await session.execute(
                    sa_text("SELECT version_num FROM alembic_version")
                )
                results["alembic_version"] = [r[0] for r in ver.fetchall()]
            except Exception:
                results["alembic_version"] = "alembic_version table not found"

            # Count users
            cnt = await session.execute(sa_text("SELECT count(*) FROM users"))
            results["user_count"] = cnt.scalar()

    except Exception as e:
        results["error"] = f"{type(e).__name__}: {e}"
        results["traceback"] = traceback.format_exc()

    return results


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str = None):
    connection_id = client_id or str(uuid.uuid4())

    # Extract user_id from Firebase ID token (query param)
    user_id = None
    token = websocket.query_params.get("token")
    if token:
        try:
            from services.auth_service import verify_id_token
            from sqlalchemy import select as sa_select
            from models.user import User as UserModel
            from database.connection import async_session_factory

            claims = verify_id_token(token)
            if claims:
                firebase_uid = claims.get("uid")
                if firebase_uid:
                    async with async_session_factory() as db:
                        result = await db.execute(
                            sa_select(UserModel).where(
                                UserModel.firebase_uid == firebase_uid
                            )
                        )
                        ws_user = result.scalar_one_or_none()
                        if ws_user:
                            user_id = str(ws_user.id)
        except Exception as e:
            logger.warning(
                f"WebSocket token verification failed for {connection_id}: {e}"
            )

    try:
        await manager.connect(websocket, connection_id, user_id=user_id)
    except Exception as e:
        logger.error(f"WebSocket connect failed ({connection_id}): {e}", exc_info=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return

    try:
        while True:
            data = await websocket.receive_text()
            await manager.handle_message(connection_id, data)
    except WebSocketDisconnect:
        manager.disconnect(connection_id)
    except Exception as e:
        logger.warning(f"WebSocket loop error ({connection_id}): {e}")
        manager.disconnect(connection_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["*.db", "*.db-journal", "*.db-wal", "__pycache__"],
    )
