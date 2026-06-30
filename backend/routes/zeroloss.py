"""
AlphaSync ZeroLoss — REST API Routes.

Endpoints:
    GET  /api/zeroloss/status       — Strategy on/off state + live confidence
    POST /api/zeroloss/toggle       — Start / stop the strategy
    GET  /api/zeroloss/signal       — Latest signal per symbol
    GET  /api/zeroloss/signals      — Signal history (paginated)
    GET  /api/zeroloss/performance  — Daily performance summary
    GET  /api/zeroloss/positions    — Currently active positions
    PUT  /api/zeroloss/config       — Update symbols / threshold / RR

All endpoints require authentication via the existing get_current_user
dependency (Firebase ID token).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from routes.auth import get_current_user
from models.user import User
from strategies.zeroloss.manager import zeroloss_manager
from strategies.zeroloss.controller import (
    IST,
    MARKET_SETTLE_TIME,
    NO_NEW_ENTRY_TIME,
)
from core.event_bus import event_bus, Event, EventType
from services import market_data
from engines.market_session import market_session, MarketState

router = APIRouter(prefix="/api/zeroloss", tags=["Alpha AutoTrade"])


# ── Request / Response Models ──────────────────────────────────────────────────


class ConfigUpdate(BaseModel):
    """Request body for PUT /config."""

    symbols: Optional[list[str]] = None
    confidence_threshold: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    quantity: Optional[int] = None


def _controller_for_user(user: User):
    return zeroloss_manager.get_controller(user.id)


async def _runtime_controller_for_user(user: User):
    return await zeroloss_manager.ensure_user_runtime(user.id)


def _zeroloss_start_block_reason() -> Optional[dict]:
    """Return a reason dict when strategy start should be blocked, else None."""
    if not market_session.is_live_trading_session():
        state = market_session.get_current_state()
        if state == MarketState.HOLIDAY:
            return {
                "code": "MARKET_HOLIDAY",
                "message": "Market holiday today — Alpha AutoTrade cannot be started.",
            }
        if state == MarketState.WEEKEND:
            return {
                "code": "MARKET_WEEKEND",
                "message": "Market is closed for weekend — Alpha AutoTrade cannot be started.",
            }
        return {
            "code": "MARKET_CLOSED",
            "message": "Market is currently closed. Start during NSE trading hours only.",
        }

    now_ist = datetime.now(IST).time()

    if now_ist < MARKET_SETTLE_TIME:
        return {
            "code": "ENTRY_WINDOW_NOT_OPEN",
            "message": "Market just opened. Alpha AutoTrade starts after 09:30 IST.",
        }

    if now_ist >= NO_NEW_ENTRY_TIME:
        return {
            "code": "ENTRY_WINDOW_TIMES_UP",
            "message": "Entry window is over for today (after 14:45 IST).",
        }

    return None


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/status")
async def zeroloss_status(user: User = Depends(get_current_user)):
    """
    Return the current state of the Alpha AutoTrade strategy:
    enabled/disabled, tracked symbols, latest confidence per symbol,
    active positions, and today's performance.
    """
    # Safety net: never keep or report enabled runtime while market is closed.
    if (not market_session.is_live_trading_session()) and await zeroloss_manager.is_user_enabled(user.id):
        await zeroloss_manager.disable(user.id, close_positions=False)

    controller = await _runtime_controller_for_user(user)

    return {
        "enabled": controller.is_enabled(),
        "symbols": controller.get_symbols(),
        "confidence": controller.get_latest_confidence(),
        "active_positions": controller.get_active_positions(),
        "stats": controller.get_stats(),
    }


@router.post("/toggle")
async def zeroloss_toggle(user: User = Depends(get_current_user)):
    """
    Toggle the Alpha AutoTrade strategy on or off.

    Returns the new enabled state.
    """
    controller = await _runtime_controller_for_user(user)

    if await zeroloss_manager.is_user_enabled(user.id):
        # Close all active positions BEFORE disabling
        closed = await zeroloss_manager.disable(user.id, close_positions=True)
        return {
            "enabled": False,
            "message": f"Alpha AutoTrade stopped — closed {len(closed)} positions",
            "closed_positions": closed,
        }
    else:
        blocked = _zeroloss_start_block_reason()
        if blocked:
            raise HTTPException(status_code=400, detail=blocked)

        await zeroloss_manager.enable(user.id)
        return {
            "enabled": True,
            "message": "Alpha AutoTrade started",
        }


@router.get("/signal")
async def zeroloss_latest_signal(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    user: User = Depends(get_current_user),
):
    """
    Return the latest signal for a given symbol, or all symbols
    if no filter is provided.
    """
    controller = await _runtime_controller_for_user(user)
    confidence = controller.get_latest_confidence()

    if symbol:
        from services.market_data import _format_symbol

        formatted = _format_symbol(symbol)
        data = confidence.get(formatted)
        if not data:
            return {"signal": None, "message": f"No signal data for {symbol}"}
        return {"signal": data}

    return {"signals": confidence}


@router.get("/signals")
async def zeroloss_signal_history(
    limit: int = Query(50, ge=1, le=500),
    symbol: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """
    Paginated signal history from the database.
    """
    from services.market_data import _format_symbol

    formatted = _format_symbol(symbol) if symbol else None
    controller = await _runtime_controller_for_user(user)
    signals = await controller.get_signal_history(limit=limit, symbol=formatted)

    # Convert datetime objects to ISO strings for JSON serialisation
    for sig in signals:
        for key in ("timestamp", "created_at"):
            if key in sig and sig[key] is not None:
                sig[key] = (
                    sig[key].isoformat()
                    if hasattr(sig[key], "isoformat")
                    else str(sig[key])
                )

    return {"signals": signals, "count": len(signals)}


@router.get("/performance")
async def zeroloss_performance(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
):
    """
    Daily performance summary for the last N days.
    """
    controller = await _runtime_controller_for_user(user)
    records = await controller.get_performance_summary(days=days)

    # Convert dates
    for rec in records:
        for key in ("date", "created_at"):
            if key in rec and rec[key] is not None:
                rec[key] = (
                    rec[key].isoformat()
                    if hasattr(rec[key], "isoformat")
                    else str(rec[key])
                )

    # Aggregate totals
    total_trades = sum(r.get("total_trades", 0) for r in records)
    total_profit = sum(r.get("profit_trades", 0) for r in records)
    total_breakeven = sum(r.get("breakeven_trades", 0) for r in records)
    total_losses = sum(r.get("loss_trades", 0) for r in records)
    total_pnl = sum(r.get("net_pnl", 0) for r in records)

    return {
        "records": records,
        "summary": {
            "total_trades": total_trades,
            "profit_trades": total_profit,
            "breakeven_trades": total_breakeven,
            "loss_trades": total_losses,
            "net_pnl": round(total_pnl, 2),
            "win_rate": (
                round(total_profit / total_trades * 100, 1) if total_trades > 0 else 0
            ),
        },
    }


@router.get("/positions")
async def zeroloss_positions(user: User = Depends(get_current_user)):
    """
    Return currently active Alpha AutoTrade positions.
    """
    controller = await _runtime_controller_for_user(user)
    return {
        "positions": controller.get_active_positions(),
        "count": len(controller.get_active_positions()),
    }


@router.put("/config")
async def zeroloss_config(
    req: ConfigUpdate,
    user: User = Depends(get_current_user),
):
    """
    Update strategy configuration (symbols, threshold, RR, quantity).
    Changes take effect on the next scan cycle.
    """
    changes = []
    controller = await _runtime_controller_for_user(user)

    if req.symbols is not None:
        controller.set_symbols(req.symbols)
        changes.append(f"symbols={req.symbols}")

    if req.confidence_threshold is not None:
        if not (0 <= req.confidence_threshold <= 100):
            raise HTTPException(
                status_code=400,
                detail="confidence_threshold must be between 0 and 100",
            )
        controller.set_confidence_threshold(req.confidence_threshold)
        changes.append(f"threshold={req.confidence_threshold}")

    if req.risk_reward_ratio is not None:
        if req.risk_reward_ratio < 1:
            raise HTTPException(
                status_code=400,
                detail="risk_reward_ratio must be >= 1",
            )
        controller.set_risk_reward_ratio(req.risk_reward_ratio)
        changes.append(f"rr_ratio={req.risk_reward_ratio}")

    if req.quantity is not None:
        if req.quantity < 1:
            raise HTTPException(
                status_code=400,
                detail="quantity must be >= 1",
            )
        controller.set_quantity(req.quantity)
        changes.append(f"quantity={req.quantity}")

    stats = controller.get_stats()

    return {
        "message": f"Config updated: {', '.join(changes)}" if changes else "No changes",
        "config": {
            "symbols": controller.get_symbols(),
            "confidence_threshold": stats.get("confidence_threshold"),
            "risk_reward_ratio": stats.get("risk_reward_ratio"),
            "quantity": stats.get("quantity"),
        },
    }


@router.get("/debug/scan")
async def zeroloss_debug_scan(
    symbol: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """Run a single scan for `symbol` and return the confidence breakdown."""
    if not symbol:
        return {"error": "symbol query parameter required"}

    from services.market_data import _format_symbol

    controller = await _runtime_controller_for_user(user)

    formatted = _format_symbol(symbol)

    # Fetch historical data
    candles = await market_data.get_historical_data(
        formatted,
        controller.CANDLE_PERIOD,
        controller.CANDLE_INTERVAL,
    )
    if not candles or len(candles) < 55:
        return {
            "error": "insufficient candle data",
            "bars": len(candles) if candles else 0,
        }

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]

    quote = await market_data.get_system_quote_safe(formatted)
    price = quote.get("price") if quote else None

    confidence = controller._confidence.score(
        closes=closes, highs=highs, lows=lows, volumes=volumes, vix=None
    )

    return {
        "symbol": formatted,
        "price": price,
        "confidence": {
            "total": confidence.total,
            "direction": confidence.direction,
            "breakdown": {
                "ema": confidence.ema_score,
                "rsi": confidence.rsi_score,
                "macd": confidence.macd_score,
                "volume": confidence.volume_score,
                "volatility": confidence.volatility_score,
                "support_resistance": confidence.sr_score,
            },
            "reasons": confidence.reasons,
        },
    }


class ForceEntryRequest(BaseModel):
    symbol: str
    force: Optional[bool] = True
    quantity: Optional[int] = 1


@router.post("/debug/force_entry")
async def zeroloss_debug_force_entry(
    req: ForceEntryRequest,
    user: User = Depends(get_current_user),
):
    """Force-create an ENTRY for `symbol` for end-to-end testing.

    This bypasses the confidence threshold when `force` is true. It will
    persist the signal and emit an ALGO_TRADE ENTRY event so frontend
    clients receive the update.
    """
    from services.market_data import _format_symbol

    controller = await _runtime_controller_for_user(user)

    formatted = _format_symbol(req.symbol)

    # Fetch data
    candles = await market_data.get_historical_data(
        formatted,
        controller.CANDLE_PERIOD,
        controller.CANDLE_INTERVAL,
    )
    if not candles or len(candles) < 55:
        return {
            "error": "insufficient candle data",
            "bars": len(candles) if candles else 0,
        }

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]

    quote = await market_data.get_system_quote_safe(formatted)
    if not quote or not quote.get("price"):
        return {"error": "no quote available"}

    current_price = quote["price"]

    confidence = controller._confidence.score(
        closes=closes, highs=highs, lows=lows, volumes=volumes, vix=None
    )

    signal = controller._signal_gen.generate(
        confidence=confidence,
        symbol=formatted,
        current_price=current_price,
        quantity=req.quantity,
    )

    # Decide whether to persist/activate
    if req.force or signal.direction in ("LONG", "SHORT"):
        signal.status = "ACTIVE"
        controller._active_positions[formatted] = signal
        controller._total_trades += 1

        # Persist and emit
        await controller._persist_signal(signal)

        await event_bus.emit(
            Event(
                type=EventType.ALGO_TRADE,
                data={
                    "channel": "zeroloss",
                    "action": "ENTRY",
                    "signal": signal.to_dict(),
                    "stats": controller.get_stats(),
                },
                user_id=str(user.id),
                source="zeroloss_debug",
            )
        )

        return {"status": "entry_created", "signal": signal.to_dict()}

    return {
        "status": "no_entry",
        "confidence": confidence.total,
        "signal": signal.to_dict(),
    }
