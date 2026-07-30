"""
Internal Simulation Engine — direct in-process access to the simulated
tick-by-tick data layer (backend/data_layer/*).

This replaces the old design where the main backend acted as an HTTP+JWT+
WebSocket *client* of "TickAlpha", even though TickAlpha is this same
codebase's own simulator running in the same process. There is no network
hop, no auth token, and no external service here: this module calls the
data_layer functions directly.

Session/subscribe/price lookups below reuse the exact same underlying
functions the data_layer HTTP routes call (data_layer/api/routes_*.py) —
just without the FastAPI request/response/JWT plumbing, which only makes
sense for genuinely external API clients (see data_layer/api/routes_admin.py
"API key" management, still used for that purpose).
"""

import json
import logging
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _resolve_wildcard_specs(spec_upper: str, eod_by_spec: Dict[tuple, Any]) -> List[str]:
    """Expands 'ALL' / 'EXCHANGE:SEGMENT:ALL' wildcards against known EOD rows
    for the target date. Mirrors data_layer/api/routes_sessions.py's wildcard
    resolution."""
    if spec_upper == "ALL":
        return [f"{ex}:{seg}:{sym}" for ex, seg, sym in eod_by_spec.keys()]
    if spec_upper.endswith(":ALL"):
        parts = spec_upper.split(":")
        if len(parts) == 3:
            ex_filter, seg_filter = parts[0], parts[1]
            return [
                f"{ex}:{seg}:{sym}"
                for ex, seg, sym in eod_by_spec.keys()
                if ex == ex_filter and seg == seg_filter
            ]
        return []
    return [spec_upper]


async def create_replay_session(replay_date: date, replay_speed: int = 1) -> Dict[str, Any]:
    """Creates a new virtual replay session pinned to a compliance-eligible date.
    Direct equivalent of POST /v1/sessions."""
    from data_layer.core.delay_gate import get_delay_cutoff
    from data_layer.api.routes_sessions import save_session_state

    cutoff = get_delay_cutoff()
    if replay_date > cutoff:
        raise ValueError(
            f"Requested date {replay_date} is restricted. Maximum allowed date is {cutoff} (3-day delay)."
        )

    session_id = f"sess_{uuid.uuid4().hex[:16]}"
    session_state = {
        "session_id": session_id,
        "date": replay_date.isoformat(),
        "replay_speed": replay_speed,
        "virtual_time": "09:15:00",
        "status": "paused",
        "subscriptions": [],
        "created_by": "internal",
    }
    await save_session_state(session_id, session_state)
    logger.info(f"Internal sim engine: created session {session_id} for {replay_date} at {replay_speed}x")
    return session_state


async def subscribe_session_symbols(db, session_id: str, symbols: List[str]) -> Dict[str, Any]:
    """Subscribes a session to symbols (supports 'ALL' / 'EXCHANGE:SEGMENT:ALL'
    wildcards), pre-generating and caching their simulated tick paths.
    Direct equivalent of POST /v1/sessions/{id}/subscribe (minus the
    scope/allowlist checks, which only apply to external API keys)."""
    from sqlalchemy import select
    from data_layer.db.models import PriceData
    from data_layer.core.delay_gate import get_delay_cutoff
    from data_layer.simulator.brownian_bridge import ensure_ticks_cached
    from data_layer.api.routes_sessions import get_session_state, save_session_state

    state = await get_session_state(session_id)
    if not state:
        raise LookupError(f"Session {session_id} not found")

    target_date = date.fromisoformat(state["date"])

    cutoff = get_delay_cutoff()
    if target_date > cutoff:
        raise ValueError(
            f"Session date {target_date} is now within the restricted 3-day compliance window "
            f"(cutoff: {cutoff}). Create a new session for an eligible date."
        )

    current_subs = set(state["subscriptions"])
    subscription_versions = dict(state.get("subscription_versions", {}))

    stmt = select(PriceData).where(
        PriceData.market_timestamp == target_date,
        PriceData.superseded_at.is_(None),
    )
    res = await db.execute(stmt)
    all_eod_rows = res.scalars().all()
    eod_by_spec: Dict[tuple, PriceData] = {}
    for row in all_eod_rows:
        key = (row.exchange.upper(), row.segment.upper(), row.symbol.upper())
        eod_by_spec.setdefault(key, row)

    for spec in symbols:
        spec_upper = spec.strip().upper()
        resolved_specs = _resolve_wildcard_specs(spec_upper, eod_by_spec)
        if not resolved_specs and (spec_upper == "ALL" or spec_upper.endswith(":ALL")):
            continue

        for resolved_spec in resolved_specs:
            parts = resolved_spec.split(":")
            if len(parts) != 3:
                continue
            exchange, segment, symbol = parts[0].upper(), parts[1].upper(), parts[2].upper()

            eod_obj = eod_by_spec.get((exchange, segment, symbol))
            resolved_eod = await ensure_ticks_cached(
                db=db,
                exchange=exchange,
                segment=segment,
                symbol=symbol,
                target_date=target_date,
                eod_data=eod_obj,
            )
            if resolved_eod is None:
                continue

            current_subs.add(resolved_spec)
            subscription_versions[resolved_spec] = resolved_eod.version

    state["subscriptions"] = list(current_subs)
    state["subscription_versions"] = subscription_versions
    await save_session_state(session_id, state)
    logger.info(
        f"Internal sim engine: session {session_id} subscribed to {symbols} -> {len(current_subs)} resolved"
    )
    return state


async def start_session_clock(session_id: str) -> Dict[str, Any]:
    """Marks a session active so SimulatorManager's clock loop starts
    advancing and publishing ticks for it. Direct equivalent of
    POST /v1/sessions/{id}/start."""
    from data_layer.api.routes_sessions import get_session_state, save_session_state

    state = await get_session_state(session_id)
    if not state:
        raise LookupError(f"Session {session_id} not found")
    state["status"] = "active"
    await save_session_state(session_id, state)
    logger.info(f"Internal sim engine: started session {session_id}")
    return state


def register_local_listener(session_id: str, queue) -> None:
    """Registers a bounded asyncio.Queue directly on SimulatorManager's
    in-process listener registry, so this process receives tick_update /
    day_rollover messages for the session without any WebSocket hop (it IS
    the process publishing them). Caller is responsible for later calling
    unregister_local_listener on disconnect."""
    from data_layer.simulator.simulator_manager import simulator_manager

    if session_id not in simulator_manager.listeners:
        simulator_manager.listeners[session_id] = set()
    simulator_manager.listeners[session_id].add(queue)


def unregister_local_listener(session_id: str, queue) -> None:
    from data_layer.simulator.simulator_manager import simulator_manager

    listeners = simulator_manager.listeners.get(session_id)
    if listeners:
        listeners.discard(queue)
        if not listeners:
            del simulator_manager.listeners[session_id]


async def get_latest_eligible_price(
    db,
    exchange: str,
    symbol: str,
    segment: str = "EQ",
    expiry: Optional[date] = None,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
) -> Optional[dict]:
    """Direct equivalent of GET /v1/price/{exchange}/{symbol} (minus the
    scope/allowlist checks and the response cache, which are HTTP-layer
    concerns for external callers)."""
    from data_layer.core.delay_gate import get_eligible_data

    record = await get_eligible_data(
        db=db,
        symbol=symbol.upper(),
        exchange=exchange.upper(),
        segment=segment.upper(),
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )
    return record.to_dict() if record else None


async def get_eligible_price_range(
    db,
    exchange: str,
    symbol: str,
    start: date,
    end: date,
    segment: str = "EQ",
    expiry: Optional[date] = None,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
) -> List[dict]:
    """Direct equivalent of GET /v1/price/{exchange}/{symbol}/range."""
    from data_layer.core.delay_gate import get_eligible_range

    records = await get_eligible_range(
        db=db,
        symbol=symbol.upper(),
        exchange=exchange.upper(),
        start_date=start,
        end_date=end,
        segment=segment.upper(),
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )
    return [r.to_dict() for r in records]


async def get_eligible_symbols_list(db, exchange: str, segment: str = "EQ") -> List[str]:
    """Direct equivalent of GET /v1/symbols."""
    from data_layer.core.delay_gate import get_eligible_symbols

    return await get_eligible_symbols(db, exchange.upper(), segment.upper())
