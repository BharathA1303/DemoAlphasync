from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Any, Optional
import logging
from database.connection import get_db
from models.user import User
from routes.auth import get_current_user
from services.algo_engine import (
    get_strategies,
    create_strategy,
    toggle_strategy,
    get_strategy_logs,
    delete_strategy,
    update_strategy,
    ensure_default_strategies,
    get_overview_stats,
    get_performance_chart,
    get_recent_signals,
    SUPPORTED_STRATEGY_TYPES,
    STRATEGY_PARAMETER_SCHEMAS,
)

router = APIRouter(prefix="/api/algo", tags=["Algo Trading"])
logger = logging.getLogger(__name__)


class CreateStrategyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    strategy_type: str = Field(..., min_length=2, max_length=50)
    symbol: str = Field(..., min_length=1, max_length=30)
    description: str = ""
    parameters: Optional[dict[str, Any]] = None
    max_position_size: int = Field(default=100, ge=1, le=100000)
    stop_loss_percent: float = Field(default=2.0, gt=0)
    take_profit_percent: float = Field(default=5.0, gt=0)


@router.get("/strategy-types")
async def list_strategy_types(
    _user: User = Depends(get_current_user),
):
    strategy_types = []
    for strategy_type in SUPPORTED_STRATEGY_TYPES:
        schema = STRATEGY_PARAMETER_SCHEMAS.get(strategy_type, {})
        strategy_types.append(
            {
                "value": strategy_type,
                "default_parameters": {
                    key: rule.get("default") for key, rule in schema.items()
                },
            }
        )
    return {"strategy_types": strategy_types}


@router.get("/strategies")
async def list_strategies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    strategies = await get_strategies(db, user.id)
    return {"strategies": strategies}


@router.post("/strategies")
async def new_strategy(
    req: CreateStrategyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await create_strategy(
            db=db,
            user_id=user.id,
            name=req.name,
            strategy_type=req.strategy_type,
            symbol=req.symbol,
            description=req.description,
            parameters=req.parameters,
            max_position_size=req.max_position_size,
            stop_loss_percent=req.stop_loss_percent,
            take_profit_percent=req.take_profit_percent,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        logger.exception("Failed to create strategy for user_id=%s", user.id)
        raise HTTPException(status_code=500, detail="Failed to create strategy")


@router.put("/strategies/{strategy_id}/toggle")
async def toggle(
    strategy_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await toggle_strategy(db, user.id, strategy_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class UpdateStrategyRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None
    parameters: Optional[dict[str, Any]] = None
    max_position_size: Optional[int] = Field(default=None, ge=1, le=100000)
    stop_loss_percent: Optional[float] = Field(default=None, gt=0)
    take_profit_percent: Optional[float] = Field(default=None, gt=0)


@router.put("/strategies/{strategy_id}")
async def update(
    strategy_id: str,
    req: UpdateStrategyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await update_strategy(
            db=db,
            user_id=user.id,
            strategy_id=strategy_id,
            name=req.name,
            description=req.description,
            parameters=req.parameters,
            max_position_size=req.max_position_size,
            stop_loss_percent=req.stop_loss_percent,
            take_profit_percent=req.take_profit_percent,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/strategies/{strategy_id}")
async def delete(
    strategy_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await delete_strategy(db, user.id, strategy_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/strategies/{strategy_id}/logs")
async def strategy_logs(
    strategy_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logs = await get_strategy_logs(db, strategy_id, limit)
    return {"logs": logs}


# ── New dashboard endpoints ───────────────────────────────────────────────────

@router.post("/ensure-defaults")
async def seed_default_strategies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Seed 3 default strategies for new users. Safe to call repeatedly."""
    result = await ensure_default_strategies(db, user.id)
    return result


@router.get("/overview-stats")
async def overview_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate stats across all strategies for the dashboard header cards."""
    stats = await get_overview_stats(db, user.id)
    return stats


@router.get("/performance-chart")
async def performance_chart(
    range: str = Query("1W", regex="^(1D|1W|1M|3M|1Y|All)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cumulative daily P&L series for the performance chart."""
    data = await get_performance_chart(db, user.id, range_key=range)
    return data


@router.get("/recent-signals")
async def recent_signals(
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Most recent algo trade signals across all user strategies."""
    signals = await get_recent_signals(db, user.id, limit=limit)
    return {"signals": signals}
