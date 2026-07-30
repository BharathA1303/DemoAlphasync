import math
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models.algo import AlgoStrategy, AlgoLog, AlgoTrade
from services import market_data
import logging

logger = logging.getLogger(__name__)


SUPPORTED_STRATEGY_TYPES = (
    "SMA_CROSSOVER",
    "RSI",
    "MACD",
    "BOLLINGER",
    "EMA_CROSSOVER",
    "VWAP_BOUNCE",
    "SUPERTREND",
    "ATR_BREAKOUT",
    "STOCHASTIC_REVERSION",
)


STRATEGY_PARAMETER_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
    "SMA_CROSSOVER": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "short_period": {"type": "int", "default": 10, "min": 2, "max": 100},
        "long_period": {"type": "int", "default": 20, "min": 5, "max": 200},
    },
    "RSI": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "period": {"type": "int", "default": 14, "min": 2, "max": 50},
        "oversold": {"type": "int", "default": 30, "min": 10, "max": 45},
        "overbought": {"type": "int", "default": 70, "min": 55, "max": 90},
    },
    "MACD": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "fast_period": {"type": "int", "default": 12, "min": 2, "max": 50},
        "slow_period": {"type": "int", "default": 26, "min": 10, "max": 100},
        "signal_period": {"type": "int", "default": 9, "min": 2, "max": 30},
    },
    "BOLLINGER": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "period": {"type": "int", "default": 20, "min": 5, "max": 50},
        "std_dev": {"type": "float", "default": 2.0, "min": 0.5, "max": 4.0},
    },
    "EMA_CROSSOVER": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "fast_period": {"type": "int", "default": 9, "min": 2, "max": 50},
        "slow_period": {"type": "int", "default": 21, "min": 5, "max": 100},
    },
    "VWAP_BOUNCE": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "bounce_threshold": {
            "type": "float",
            "default": 0.2,
            "min": 0.1,
            "max": 1.0,
        },
    },
    "SUPERTREND": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "atr_period": {"type": "int", "default": 10, "min": 5, "max": 50},
        "multiplier": {"type": "float", "default": 3.0, "min": 1.0, "max": 6.0},
    },
    "ATR_BREAKOUT": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "period": {"type": "int", "default": 14, "min": 5, "max": 50},
        "breakout_multiplier": {
            "type": "float",
            "default": 1.2,
            "min": 0.5,
            "max": 3.0,
        },
    },
    "STOCHASTIC_REVERSION": {
        "quantity": {"type": "int", "default": 1, "min": 1, "max": 1000},
        "k_period": {"type": "int", "default": 14, "min": 5, "max": 30},
        "d_period": {"type": "int", "default": 3, "min": 2, "max": 10},
        "oversold": {"type": "int", "default": 20, "min": 5, "max": 40},
        "overbought": {"type": "int", "default": 80, "min": 60, "max": 95},
    },
}

DEFAULT_STRATEGIES_SEED = [
    {
        "name": "Nifty Momentum Pro",
        "strategy_type": "EMA_CROSSOVER",
        "symbol": "RELIANCE",
        "description": "Fast/slow EMA crossover for momentum trading on Reliance Industries.",
        "max_position_size": 50,
        "stop_loss_percent": 1.5,
        "take_profit_percent": 3.0,
        "parameters": {"quantity": 1, "fast_period": 9, "slow_period": 21},
    },
    {
        "name": "BankNifty Scalper",
        "strategy_type": "RSI",
        "symbol": "HDFCBANK",
        "description": "RSI-based mean reversion scalper on HDFC Bank. Buys oversold dips, sells overbought peaks.",
        "max_position_size": 25,
        "stop_loss_percent": 1.0,
        "take_profit_percent": 2.0,
        "parameters": {"quantity": 1, "period": 14, "oversold": 30, "overbought": 70},
    },
    {
        "name": "Trend Following Swing",
        "strategy_type": "MACD",
        "symbol": "TCS",
        "description": "MACD signal crossover for multi-day swing trades on TCS. Follows strong directional trends.",
        "max_position_size": 100,
        "stop_loss_percent": 2.0,
        "take_profit_percent": 5.0,
        "parameters": {"quantity": 1, "fast_period": 12, "slow_period": 26, "signal_period": 9},
    },
]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _validate_strategy_type(strategy_type: str) -> str:
    normalized = str(strategy_type or "").strip().upper()
    if not normalized:
        raise ValueError("Strategy type is required")
    if normalized not in SUPPORTED_STRATEGY_TYPES:
        supported = ", ".join(SUPPORTED_STRATEGY_TYPES)
        raise ValueError(
            f"Unsupported strategy type: {normalized}. Supported: {supported}"
        )
    return normalized


def _sanitize_parameters(strategy_type: str, raw_parameters: Optional[dict]) -> dict:
    schema = STRATEGY_PARAMETER_SCHEMAS.get(strategy_type, {})
    incoming = raw_parameters if isinstance(raw_parameters, dict) else {}

    cleaned: dict[str, Any] = {}
    for key, spec in schema.items():
        default = spec["default"]
        value = incoming.get(key, default)

        if spec["type"] == "int":
            parsed = _to_int(value, int(default))
            parsed = int(_clamp(parsed, int(spec["min"]), int(spec["max"])))
        else:
            parsed = _to_float(value, float(default))
            parsed = round(
                _clamp(parsed, float(spec["min"]), float(spec["max"])),
                4,
            )
        cleaned[key] = parsed

    if (
        strategy_type == "SMA_CROSSOVER"
        and cleaned["short_period"] >= cleaned["long_period"]
    ):
        cleaned["short_period"] = max(2, cleaned["long_period"] - 1)

    if (
        strategy_type == "EMA_CROSSOVER"
        and cleaned["fast_period"] >= cleaned["slow_period"]
    ):
        cleaned["fast_period"] = max(2, cleaned["slow_period"] - 1)

    if strategy_type == "MACD" and cleaned["fast_period"] >= cleaned["slow_period"]:
        cleaned["fast_period"] = max(2, cleaned["slow_period"] - 1)

    if (
        strategy_type in {"RSI", "STOCHASTIC_REVERSION"}
        and cleaned["oversold"] >= cleaned["overbought"]
    ):
        cleaned["oversold"] = max(
            int(schema["oversold"]["min"]), cleaned["overbought"] - 1
        )

    return cleaned


def _serialize_strategy(
    s: AlgoStrategy,
    today_pnl: float = 0.0,
    sharpe_ratio: float = 0.0,
) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "strategy_type": s.strategy_type,
        "symbol": s.symbol,
        "is_active": s.is_active,
        "parameters": s.parameters,
        "max_position_size": s.max_position_size,
        "stop_loss_percent": float(s.stop_loss_percent),
        "take_profit_percent": float(s.take_profit_percent),
        "total_trades": s.total_trades,
        "total_pnl": float(round(s.total_pnl, 2)),
        "today_pnl": round(today_pnl, 2),
        "win_rate": float(round(s.win_rate, 2)),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _normalize_common_inputs(
    *,
    name: str,
    strategy_type: str,
    symbol: str,
    parameters: Optional[dict],
    max_position_size: int,
    stop_loss_percent: float,
    take_profit_percent: float,
) -> dict:
    name_clean = str(name or "").strip()
    if not name_clean:
        raise ValueError("Strategy name is required")

    symbol_raw = str(symbol or "").strip().upper()
    if not symbol_raw:
        raise ValueError("Symbol is required")

    stype = _validate_strategy_type(strategy_type)
    params_clean = _sanitize_parameters(stype, parameters)

    max_pos = int(_clamp(_to_int(max_position_size, 100), 1, 100000))
    stop_loss = round(_clamp(_to_float(stop_loss_percent, 2.0), 0.1, 50.0), 2)
    take_profit = round(_clamp(_to_float(take_profit_percent, 5.0), 0.1, 200.0), 2)

    return {
        "name": name_clean,
        "strategy_type": stype,
        "symbol": market_data._format_symbol(symbol_raw),
        "parameters": params_clean,
        "max_position_size": max_pos,
        "stop_loss_percent": stop_loss,
        "take_profit_percent": take_profit,
    }


def _coerce_uuid(value):
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _compute_sharpe_from_daily(daily_pnls: list) -> float:
    """Annualised Sharpe ratio from a series of daily P&L values."""
    if len(daily_pnls) < 2:
        return 0.0
    try:
        mean_pnl = sum(daily_pnls) / len(daily_pnls)
        variance = sum((x - mean_pnl) ** 2 for x in daily_pnls) / (len(daily_pnls) - 1)
        std_pnl = variance ** 0.5
        if std_pnl == 0:
            return 0.0
        return round(mean_pnl / std_pnl * math.sqrt(252), 2)
    except Exception:
        return 0.0


def _compute_max_drawdown(daily_pnls: list) -> float:
    """Peak-to-trough max drawdown as a percentage of peak cumulative P&L."""
    if len(daily_pnls) < 2:
        return 0.0
    try:
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in daily_pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            if peak > 0:
                drawdown = (peak - cumulative) / peak
                if drawdown > max_dd:
                    max_dd = drawdown
        return round(max_dd * 100, 2)
    except Exception:
        return 0.0


async def _fetch_daily_pnl_by_strategy(
    db: AsyncSession, strategy_ids: list
) -> dict:
    """
    Returns {strategy_id_str: [daily_pnl_float, ...]} ordered by date.
    Uses explicit select_from to ensure correct FROM/JOIN resolution.
    """
    if not strategy_ids:
        return {}
    try:
        result = await db.execute(
            select(
                AlgoTrade.strategy_id,
                func.date_trunc("day", AlgoTrade.created_at).label("trade_day"),
                func.sum(AlgoTrade.pnl).label("daily_pnl"),
            )
            .select_from(AlgoTrade)
            .where(AlgoTrade.strategy_id.in_(strategy_ids))
            .group_by(
                AlgoTrade.strategy_id,
                func.date_trunc("day", AlgoTrade.created_at),
            )
            .order_by(func.date_trunc("day", AlgoTrade.created_at))
        )
        rows = result.all()
        by_strategy: dict = {}
        for row in rows:
            sid = str(row.strategy_id)
            if sid not in by_strategy:
                by_strategy[sid] = []
            by_strategy[sid].append(float(row.daily_pnl or 0))
        return by_strategy
    except Exception:
        logger.exception("_fetch_daily_pnl_by_strategy failed")
        return {}


async def get_strategies(db: AsyncSession, user_id: str) -> list:
    """Get all algo strategies for a user, enriched with today_pnl and sharpe_ratio."""
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        return []

    result = await db.execute(
        select(AlgoStrategy)
        .where(AlgoStrategy.user_id == user_uuid)
        .order_by(AlgoStrategy.created_at.desc())
    )
    strategies = result.scalars().all()

    if not strategies:
        return []

    strategy_ids = [s.id for s in strategies]
    today_pnl_map: dict = {}
    sharpe_map: dict = {}

    # Today's P&L per strategy
    try:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_result = await db.execute(
            select(
                AlgoTrade.strategy_id,
                func.sum(AlgoTrade.pnl).label("today_pnl"),
            )
            .select_from(AlgoTrade)
            .where(AlgoTrade.strategy_id.in_(strategy_ids))
            .where(AlgoTrade.created_at >= today_start)
            .group_by(AlgoTrade.strategy_id)
        )
        for row in today_result.all():
            today_pnl_map[str(row.strategy_id)] = float(row.today_pnl or 0)
    except Exception:
        logger.exception("get_strategies: failed to fetch today_pnl")

    # Per-strategy sharpe ratio
    try:
        daily_map = await _fetch_daily_pnl_by_strategy(db, strategy_ids)
        for sid, pnls in daily_map.items():
            sharpe_map[sid] = _compute_sharpe_from_daily(pnls)
    except Exception:
        logger.exception("get_strategies: failed to compute sharpe_ratio")

    return [
        _serialize_strategy(
            s,
            today_pnl=today_pnl_map.get(str(s.id), 0.0),
            sharpe_ratio=sharpe_map.get(str(s.id), 0.0),
        )
        for s in strategies
    ]


async def create_strategy(
    db: AsyncSession,
    user_id: str,
    name: str,
    strategy_type: str,
    symbol: str,
    description: str = "",
    parameters: dict = None,
    max_position_size: int = 100,
    stop_loss_percent: float = 2.0,
    take_profit_percent: float = 5.0,
) -> dict:
    """Create a new algo strategy."""
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        raise ValueError("Invalid user context")

    normalized = _normalize_common_inputs(
        name=name,
        strategy_type=strategy_type,
        symbol=symbol,
        parameters=parameters,
        max_position_size=max_position_size,
        stop_loss_percent=stop_loss_percent,
        take_profit_percent=take_profit_percent,
    )

    strategy = AlgoStrategy(
        user_id=user_uuid,
        name=normalized["name"],
        description=str(description or "").strip(),
        strategy_type=normalized["strategy_type"],
        symbol=normalized["symbol"],
        parameters=normalized["parameters"],
        max_position_size=normalized["max_position_size"],
        stop_loss_percent=normalized["stop_loss_percent"],
        take_profit_percent=normalized["take_profit_percent"],
    )
    db.add(strategy)
    await db.flush()

    log = AlgoLog(
        strategy_id=strategy.id,
        level="INFO",
        message=f"Strategy '{strategy.name}' created for {strategy.symbol}",
    )
    db.add(log)

    return {
        "success": True,
        "strategy_id": str(strategy.id),
        "strategy": _serialize_strategy(strategy),
    }


async def toggle_strategy(db: AsyncSession, user_id: str, strategy_id: str) -> dict:
    """Enable or disable an algo strategy. Closes open positions on deactivate."""
    user_uuid = _coerce_uuid(user_id)
    strategy_uuid = _coerce_uuid(strategy_id)
    if user_uuid is None or strategy_uuid is None:
        return {"success": False, "error": "Invalid strategy ID"}

    result = await db.execute(
        select(AlgoStrategy).where(
            AlgoStrategy.id == strategy_uuid,
            AlgoStrategy.user_id == user_uuid,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return {"success": False, "error": "Strategy not found"}

    strategy.is_active = not strategy.is_active
    status = "activated" if strategy.is_active else "deactivated"

    closed_msg = ""
    if not strategy.is_active:
        try:
            from workers.algo_worker import algo_strategy_worker

            pnl = await algo_strategy_worker.close_strategy_position(str(strategy.id))
            if pnl is not None:
                closed_msg = f" — closed open position"
        except Exception:
            logger.exception(
                "Failed to close open algo position on deactivate for strategy_id=%s",
                strategy_id,
            )

    log = AlgoLog(
        strategy_id=strategy.id,
        level="INFO",
        message=f"Strategy '{strategy.name}' {status}{closed_msg}",
    )
    db.add(log)

    return {
        "success": True,
        "is_active": strategy.is_active,
        "message": f"Strategy {status}{closed_msg}",
    }


async def delete_strategy(db: AsyncSession, user_id: str, strategy_id: str) -> dict:
    """Delete an algo strategy (must be deactivated first)."""
    user_uuid = _coerce_uuid(user_id)
    strategy_uuid = _coerce_uuid(strategy_id)
    if user_uuid is None or strategy_uuid is None:
        return {"success": False, "error": "Invalid strategy ID"}

    result = await db.execute(
        select(AlgoStrategy).where(
            AlgoStrategy.id == strategy_uuid,
            AlgoStrategy.user_id == user_uuid,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return {"success": False, "error": "Strategy not found"}
    if strategy.is_active:
        return {"success": False, "error": "Deactivate the strategy before deleting"}
    await db.delete(strategy)
    return {"success": True}


async def update_strategy(
    db: AsyncSession,
    user_id: str,
    strategy_id: str,
    name: str = None,
    description: str = None,
    parameters: dict = None,
    max_position_size: int = None,
    stop_loss_percent: float = None,
    take_profit_percent: float = None,
) -> dict:
    """Update an algo strategy's configuration."""
    user_uuid = _coerce_uuid(user_id)
    strategy_uuid = _coerce_uuid(strategy_id)
    if user_uuid is None or strategy_uuid is None:
        return {"success": False, "error": "Invalid strategy ID"}

    result = await db.execute(
        select(AlgoStrategy).where(
            AlgoStrategy.id == strategy_uuid,
            AlgoStrategy.user_id == user_uuid,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return {"success": False, "error": "Strategy not found"}

    if name is not None:
        name_clean = str(name).strip()
        if not name_clean:
            raise ValueError("Strategy name cannot be empty")
        strategy.name = name_clean
    if description is not None:
        strategy.description = str(description).strip()
    if parameters is not None:
        strategy.parameters = _sanitize_parameters(strategy.strategy_type, parameters)
    if max_position_size is not None:
        strategy.max_position_size = int(
            _clamp(
                _to_int(max_position_size, strategy.max_position_size or 100), 1, 100000
            )
        )
    if stop_loss_percent is not None:
        strategy.stop_loss_percent = round(
            _clamp(
                _to_float(stop_loss_percent, float(strategy.stop_loss_percent or 2.0)),
                0.1,
                50.0,
            ),
            2,
        )
    if take_profit_percent is not None:
        strategy.take_profit_percent = round(
            _clamp(
                _to_float(
                    take_profit_percent,
                    float(strategy.take_profit_percent or 5.0),
                ),
                0.1,
                200.0,
            ),
            2,
        )

    strategy.updated_at = datetime.now(timezone.utc)

    log = AlgoLog(
        strategy_id=strategy.id,
        level="INFO",
        message=f"Strategy '{strategy.name}' parameters updated",
    )
    db.add(log)
    return {"success": True, "strategy": _serialize_strategy(strategy)}


async def get_strategy_logs(
    db: AsyncSession, strategy_id: str, limit: int = 50
) -> list:
    """Get logs for a specific strategy."""
    strategy_uuid = _coerce_uuid(strategy_id)
    if strategy_uuid is None:
        return []

    result = await db.execute(
        select(AlgoLog)
        .where(AlgoLog.strategy_id == strategy_uuid)
        .order_by(AlgoLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(l.id),
            "level": l.level,
            "message": l.message,
            "data": l.data,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


# ── New dashboard functions ───────────────────────────────────────────────────

async def ensure_default_strategies(db: AsyncSession, user_id: str) -> dict:
    """Seed 3 default strategies for new users who have no strategies yet."""
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        return {"created": 0, "total": 0}

    try:
        count_result = await db.execute(
            select(func.count(AlgoStrategy.id)).where(
                AlgoStrategy.user_id == user_uuid
            )
        )
        existing_count = count_result.scalar_one_or_none() or 0
    except Exception:
        logger.exception("ensure_default_strategies: failed to count existing strategies")
        return {"created": 0, "total": 0}

    if existing_count > 0:
        return {"created": 0, "total": existing_count}

    created = 0
    for seed in DEFAULT_STRATEGIES_SEED:
        try:
            await create_strategy(
                db=db,
                user_id=user_id,
                name=seed["name"],
                strategy_type=seed["strategy_type"],
                symbol=seed["symbol"],
                description=seed["description"],
                max_position_size=seed["max_position_size"],
                stop_loss_percent=seed["stop_loss_percent"],
                take_profit_percent=seed["take_profit_percent"],
                parameters=seed["parameters"],
            )
            created += 1
        except Exception:
            logger.exception("ensure_default_strategies: failed to seed '%s'", seed["name"])

    return {"created": created, "total": created}


async def get_overview_stats(db: AsyncSession, user_id: str) -> dict:
    """
    Aggregate stats across all strategies.
    Primary stats come from AlgoStrategy model (always available).
    Sharpe/drawdown are computed from trade history (non-critical, returns 0 on failure).
    """
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        return _empty_stats()

    try:
        result = await db.execute(
            select(AlgoStrategy).where(AlgoStrategy.user_id == user_uuid)
        )
        strategies = result.scalars().all()
    except Exception:
        logger.exception("get_overview_stats: failed to query strategies")
        return _empty_stats()

    if not strategies:
        return _empty_stats()

    active_count = sum(1 for s in strategies if s.is_active)
    total_count = len(strategies)
    total_pnl = sum(float(s.total_pnl or 0) for s in strategies)
    avg_win_rate = sum(float(s.win_rate or 0) for s in strategies) / total_count

    avg_sharpe = 0.0
    avg_max_drawdown = 0.0
    try:
        strategy_ids = [s.id for s in strategies]
        daily_map = await _fetch_daily_pnl_by_strategy(db, strategy_ids)
        if daily_map:
            sharpes = [_compute_sharpe_from_daily(pnls) for pnls in daily_map.values()]
            drawdowns = [_compute_max_drawdown(pnls) for pnls in daily_map.values()]
            avg_sharpe = sum(sharpes) / len(sharpes)
            avg_max_drawdown = sum(drawdowns) / len(drawdowns)
    except Exception:
        logger.exception("get_overview_stats: failed to compute sharpe/drawdown")

    return {
        "active_count": active_count,
        "total_count": total_count,
        "total_pnl": round(total_pnl, 2),
        "avg_win_rate": round(avg_win_rate, 2),
        "avg_max_drawdown": round(avg_max_drawdown, 2),
        "avg_sharpe_ratio": round(avg_sharpe, 2),
    }


def _empty_stats() -> dict:
    return {
        "active_count": 0,
        "total_count": 0,
        "total_pnl": 0.0,
        "avg_win_rate": 0.0,
        "avg_max_drawdown": 0.0,
        "avg_sharpe_ratio": 0.0,
    }


_RANGE_DAYS: dict = {
    "1D": 1,
    "1W": 7,
    "1M": 30,
    "3M": 90,
    "1Y": 365,
    "All": 3650,
}


async def get_performance_chart(
    db: AsyncSession, user_id: str, range_key: str = "1W"
) -> dict:
    """Return cumulative daily P&L series for the performance chart."""
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        return {"labels": [], "values": []}

    days = _RANGE_DAYS.get(range_key, 7)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        result = await db.execute(
            select(
                func.date_trunc("day", AlgoTrade.created_at).label("trade_day"),
                func.sum(AlgoTrade.pnl).label("daily_pnl"),
            )
            .select_from(AlgoTrade)
            .join(AlgoStrategy, AlgoTrade.strategy_id == AlgoStrategy.id)
            .where(AlgoStrategy.user_id == user_uuid)
            .where(AlgoTrade.created_at >= cutoff)
            .group_by(func.date_trunc("day", AlgoTrade.created_at))
            .order_by(func.date_trunc("day", AlgoTrade.created_at))
        )
        rows = result.all()
    except Exception:
        logger.exception("get_performance_chart: query failed")
        return {"labels": [], "values": []}

    labels: list = []
    values: list = []
    cumulative = 0.0
    for row in rows:
        day_pnl = float(row.daily_pnl or 0)
        cumulative += day_pnl
        labels.append(row.trade_day.strftime("%d %b"))
        values.append(round(cumulative, 2))

    return {"labels": labels, "values": values}


async def get_recent_signals(
    db: AsyncSession, user_id: str, limit: int = 5
) -> list:
    """Return the most recent algo trade signals across all user strategies."""
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        return []

    try:
        result = await db.execute(
            select(
                AlgoTrade.symbol,
                AlgoTrade.side,
                AlgoTrade.price,
                AlgoTrade.pnl,
                AlgoTrade.created_at,
                AlgoStrategy.name.label("strategy_name"),
            )
            .select_from(AlgoTrade)
            .join(AlgoStrategy, AlgoTrade.strategy_id == AlgoStrategy.id)
            .where(AlgoStrategy.user_id == user_uuid)
            .order_by(AlgoTrade.created_at.desc())
            .limit(limit)
        )
        rows = result.all()
    except Exception:
        logger.exception("get_recent_signals: query failed")
        return []

    return [
        {
            "strategy_name": row.strategy_name,
            "symbol": row.symbol,
            "side": row.side,
            "price": float(row.price),
            "pnl": float(row.pnl or 0),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
