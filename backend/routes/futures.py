"""
Futures Router — Read-only derivatives analytics endpoints.

Provides contract metadata, quotes, and history for NSE futures (stocks and indices).
No order entry, no buy/sell, no paper trading integration.

Endpoints:
    GET /api/futures/contracts/{symbol} — List futures contracts for a symbol
    GET /api/futures/quote/{contract_symbol} — Live quote for a contract
    GET /api/futures/history/{contract_symbol} — OHLCV history for sparkline
    GET /api/futures/spot/{symbol} — Underlying spot price (for basis calculation)
"""

import logging
from datetime import datetime
from typing import Optional

try:
    from fastapi import APIRouter, Query, HTTPException, Depends
except ImportError:
    raise ImportError("FastAPI is required. Install with: pip install fastapi")

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from database.connection import get_db
from routes.auth import get_current_user_optional, get_current_user
from models.user import User
from engines.market_session import market_session
from services import futures_service
from services.market_data import get_system_quote_live_only
from services.futures_trading_service import (
    place_futures_order,
    cancel_futures_order,
    get_futures_positions,
    close_all_futures_positions,
)
from config.settings import settings

router = APIRouter(prefix="/api/futures", tags=["Futures"])
logger = logging.getLogger(__name__)


def _change_fields(quote: dict) -> dict:
    """Normalize futures day change fields for UI headers/watchlists."""
    if not quote:
        return {"change": None, "change_pct": None, "change_percent": None, "prev_close": None}

    change = quote.get("change") or quote.get("net_change")
    change_pct = (
        quote.get("change_pct")
        if quote.get("change_pct") is not None
        else quote.get("change_percent")
    )
    if change_pct is None:
        change_pct = quote.get("pc") or quote.get("pct_change") or quote.get("pChange")
    prev_close = quote.get("prev_close") or quote.get("previous_close") or quote.get("close") or quote.get("c")
    ltp = quote.get("ltp") or quote.get("price") or quote.get("lp")

    try:
        ltp_num = float(ltp)
        prev_num = float(prev_close)
    except (TypeError, ValueError):
        prev_num = None
    else:
        if prev_num > 0:
            if change is None:
                change = round(ltp_num - prev_num, 2)
            if change_pct is None:
                change_pct = round((float(change) / prev_num) * 100.0, 2)

    try:
        change = round(float(change), 2) if change is not None else None
    except (TypeError, ValueError):
        change = None
    try:
        change_pct = round(float(change_pct), 2) if change_pct is not None else None
    except (TypeError, ValueError):
        change_pct = None

    return {
        "change": change,
        "change_pct": change_pct,
        "change_percent": change_pct,
        "prev_close": prev_num if prev_num and prev_num > 0 else None,
    }


def _snapshot_epoch_ms(value) -> int:
    now_ms = int(datetime.now().timestamp() * 1000)
    if value is None:
        return now_ms
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1_000_000_000_000:
            return int(v)
        if v > 1_000_000_000:
            return int(v * 1000)
        return int(v * 1000)
    if isinstance(value, str):
        try:
            return int(
                datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                * 1000
            )
        except Exception:
            return now_ms
    return now_ms


def _snapshot_envelope(data: dict, stream_symbols: list, snapshot_ts, snapshot: bool) -> dict:
    ts_ms = _snapshot_epoch_ms(snapshot_ts)
    now_ms = int(datetime.now().timestamp() * 1000)
    return {
        "snapshot": snapshot,
        "snapshot_ts": ts_ms,
        "stale_ms": max(0, now_ms - ts_ms),
        "stream_symbols": stream_symbols or [],
        "data": data or {},
    }


def _format_contracts(symbol: str, contracts: list[dict]) -> list[dict]:
    results = []
    labels = ["Near", "Mid", "Far"]

    for idx, contract in enumerate(contracts or []):
        label = labels[min(idx, len(labels) - 1)]

        try:
            expiry_dt = datetime.strptime(contract.get("expiry_date", ""), "%Y-%m-%d")
            days_to_expiry = max(0, (expiry_dt.date() - datetime.now().date()).days)
        except (ValueError, TypeError, AttributeError):
            days_to_expiry = 0

        results.append(
            {
                "contract_symbol": contract.get("contract_symbol", ""),
                "token": contract.get("token", ""),
                "exchange": contract.get("exchange", "NSE"),
                "expiry_date": contract.get("expiry_date", ""),
                "expiry_label": label,
                "days_to_expiry": days_to_expiry,
                "lot_size": int(contract.get("lot_size", 1)),
                "tick_size": float(contract.get("tick_size", 0.05)),
                "instrument_type": contract.get("instrument_type", "FUTSTK"),
            }
        )

    return results


def _to_unix_timestamp(value) -> int:
    """Convert mixed timestamp formats to Unix seconds safely."""
    if value is None:
        return int(datetime.now().timestamp())

    try:
        numeric = float(value)
        if numeric > 1_000_000_000_000:
            numeric /= 1000.0
        return int(numeric)
    except (TypeError, ValueError):
        pass

    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except Exception:
            pass

    return int(datetime.now().timestamp())


@router.get("/contracts/{symbol}")
async def list_contracts(
    symbol: str,
    user: Optional[User] = Depends(get_current_user_optional),
    snapshot: int = Query(0, ge=0, le=1, description="Return cached snapshot only"),
    reconcile: int = Query(0, ge=0, le=1, description="Return full live data for background reconcile"),
):
    """
    List all active futures contracts for a symbol.

    Query Parameters:
        symbol: Canonical symbol (e.g., RELIANCE, NIFTY)

    Response:
        List of contracts sorted by expiry date (nearest first).
        Each contract includes:
            - contract_symbol: Zebu trading symbol (e.g., RELIANCE25MAR2026FUT)
            - expiry_date: ISO format (2026-03-25)
            - expiry_label: Near / Mid / Far
            - lot_size: Minimum order quantity
            - tick_size: Minimum price movement
            - instrument_type: FUTIDX or FUTSTK
            - exchange: NSE

    Example:
        GET /api/futures/contracts/RELIANCE
        Returns:
            [
                {
                    "contract_symbol": "RELIANCE25MAR2026FUT",
                    "expiry_date": "2026-03-25",
                    "expiry_label": "Near",
                    "lot_size": 250,
                    "tick_size": 0.05,
                    "instrument_type": "FUTSTK"
                },
                ...
            ]
    """
    try:
        symbol = symbol.upper().strip().replace(".NS", "").replace(".BO", "")
    except Exception:
        return {"contracts": [], "symbol": symbol, "found": False}

    snapshot_enabled = bool(snapshot) and settings.ENABLE_PROGRESSIVE_FUTURES
    reconcile_enabled = bool(reconcile) and settings.ENABLE_PROGRESSIVE_FUTURES

    if snapshot_enabled:
        cached_contracts = await futures_service.get_cached_contracts_snapshot(symbol)
        results = _format_contracts(symbol, cached_contracts)
        stream_symbols = [c.get("contract_symbol") for c in results if c.get("contract_symbol")]
        payload = {
            "contracts": results,
            "symbol": symbol,
            "found": bool(results),
            "market_open": market_session.is_trading_hours(),
        }
        return _snapshot_envelope(payload, stream_symbols, datetime.now(), snapshot=True)

    # Get live contracts from service (SearchScrip) and fall back to cache only if needed
    try:
        contracts = await futures_service.get_contracts_live(symbol)
    except Exception as e:
        logger.error(f"Error fetching contracts for {symbol}: {e}")
        return {"contracts": [], "symbol": symbol, "found": False, "error": str(e)}

    if not contracts:
        payload = {
            "contracts": [],
            "symbol": symbol,
            "found": False,
            "market_open": market_session.is_trading_hours(),
        }
        if reconcile_enabled:
            return _snapshot_envelope(payload, [], datetime.now(), snapshot=False)
        return payload

    results = _format_contracts(symbol, contracts)
    payload = {
        "contracts": results,
        "symbol": symbol,
        "found": True,
        "market_open": market_session.is_trading_hours(),
    }
    if reconcile_enabled:
        stream_symbols = [c.get("contract_symbol") for c in results if c.get("contract_symbol")]
        return _snapshot_envelope(payload, stream_symbols, datetime.now(), snapshot=False)
    return payload


@router.get("/quote/{contract_symbol}")
async def get_contract_quote(
    contract_symbol: str,
    token: Optional[str] = Query(None, description="Optional Noren token"),
    exchange: Optional[str] = Query(None, description="Optional exchange (NFO/BFO)"),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get live quote for a futures contract.

    Sources (in order):
        1. Redis cache (if fresh)
        2. Existing market_data service (Zebu)

    Parameters:
        contract_symbol: Zebu futures symbol (e.g., RELIANCE25MAR2026FUT)

    Response:
        {
            "contract_symbol": str,
            "ltp": float,              # Last traded price
            "open": float,
            "high": float,
            "low": float,
            "close": float,
            "volume": int,             # Total trades volume
            "oi": int,                 # Open interest
            "oi_change": int | null,   # OI change since yesterday
            "bid": float | null,
            "ask": float | null,
            "vwap": float | null,
            "timestamp": int,          # Unix timestamp (seconds)
            "market_open": bool,
            "bid_depth": int | null,   # Bid side depth (volume)
            "ask_depth": int | null,   # Ask side depth (volume)
        }
    """
    contract_symbol = contract_symbol.upper().strip()

    # Fast path: if token is provided by contracts list, query GetQuotes directly.
    token_value = str(token or "").strip()
    exchange_value = str(exchange or "").upper().strip() or "NFO"
    if token_value:
        try:
            from services.broker_session import broker_session_manager

            provider = broker_session_manager.get_any_session()
            if provider is None:
                from services.master_session import master_session_service

                if await master_session_service.initialize():
                    provider = broker_session_manager.get_any_session()

            if provider is not None:
                raw = await provider._rest_post(
                    "/GetQuotes",
                    {"exch": exchange_value, "token": token_value},
                )
                if raw and isinstance(raw, dict) and raw.get("stat") == "Ok":
                    return {
                        "contract_symbol": contract_symbol,
                        "ltp": raw.get("lp") or raw.get("ltp") or raw.get("price"),
                        "open": raw.get("o") or raw.get("open"),
                        "high": raw.get("h") or raw.get("high"),
                        "low": raw.get("l") or raw.get("low"),
                        "close": raw.get("c") or raw.get("close"),
                        **_change_fields(raw),
                        "volume": raw.get("v") or raw.get("volume") or 0,
                        "oi": raw.get("oi") or 0,
                        "oi_change": raw.get("oi_change"),
                        "bid": raw.get("bp1") or raw.get("bid") or raw.get("b"),
                        "ask": raw.get("sp1") or raw.get("ask") or raw.get("a"),
                        "vwap": raw.get("ap") or raw.get("vwap"),
                        "timestamp": _to_unix_timestamp(
                            raw.get("ft") or raw.get("ltt") or raw.get("timestamp")
                        ),
                        "market_open": market_session.is_trading_hours(),
                        "bid_depth": raw.get("tbq") or raw.get("bid_depth"),
                        "ask_depth": raw.get("tsq") or raw.get("ask_depth"),
                        "available": True,
                    }
        except Exception as e:
            logger.debug(f"Direct token quote failed for {contract_symbol}: {e}")

    # Try cache first
    cached = await futures_service.get_cache_quote(contract_symbol)
    if cached:
        return {
            "contract_symbol": contract_symbol,
            "ltp": cached.get("ltp") or cached.get("price") or cached.get("lp"),
            "open": cached.get("open") or cached.get("o"),
            "high": cached.get("high") or cached.get("h"),
            "low": cached.get("low") or cached.get("l"),
            "close": cached.get("close") or cached.get("c"),
            **_change_fields(cached),
            "volume": cached.get("volume") or cached.get("v") or 0,
            "oi": cached.get("oi") or 0,
            "oi_change": cached.get("oi_change"),
            "bid": cached.get("bid") or cached.get("b"),
            "ask": cached.get("ask") or cached.get("a"),
            "vwap": cached.get("vwap"),
            "timestamp": _to_unix_timestamp(
                cached.get("timestamp")
                or cached.get("last_trade_time")
                or cached.get("ft")
            ),
            "market_open": market_session.is_trading_hours(),
            "bid_depth": cached.get("bid_depth"),
            "ask_depth": cached.get("ask_depth"),
            "available": True,
        }

    # Fetch from market data service
    quote = await futures_service.get_quote(contract_symbol)

    if not quote:
        # Return unavailable response with proper structure
        return {
            "contract_symbol": contract_symbol,
            "ltp": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "change": None,
            "change_pct": None,
            "change_percent": None,
            "prev_close": None,
            "volume": 0,
            "oi": 0,
            "oi_change": None,
            "bid": None,
            "ask": None,
            "vwap": None,
            "timestamp": int(datetime.now().timestamp()),
            "market_open": market_session.is_trading_hours(),
            "bid_depth": None,
            "ask_depth": None,
            "available": False,
        }

    # Cache the retrieved quote
    await futures_service.set_cache_quote(contract_symbol, quote)

    # Normalize quote response
    return {
        "contract_symbol": contract_symbol,
        "ltp": quote.get("ltp") or quote.get("price") or quote.get("lp"),
        "open": quote.get("open") or quote.get("o"),
        "high": quote.get("high") or quote.get("h"),
        "low": quote.get("low") or quote.get("l"),
        "close": quote.get("close") or quote.get("c"),
        **_change_fields(quote),
        "volume": quote.get("volume") or quote.get("v") or 0,
        "oi": quote.get("oi") or 0,
        "oi_change": quote.get("oi_change"),
        "bid": quote.get("bid") or quote.get("b"),
        "ask": quote.get("ask") or quote.get("a"),
        "vwap": quote.get("vwap"),
        "timestamp": _to_unix_timestamp(
            quote.get("timestamp") or quote.get("last_trade_time") or quote.get("ft")
        ),
        "market_open": market_session.is_trading_hours(),
        "bid_depth": quote.get("bid_depth"),
        "ask_depth": quote.get("ask_depth"),
        "available": True,
    }


@router.get("/history/{contract_symbol}")
async def get_contract_history(
    contract_symbol: str,
    interval: str = Query("5m", regex="^(1m|5m|15m|1h|1d)$"),
    limit: int = Query(30, ge=1, le=500),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get OHLCV candles for a futures contract (for sparkline visualization).

    Parameters:
        contract_symbol: Zebu futures symbol
        interval: Candle interval (1m, 5m, 15m, 1h, 1d)
        limit: Number of candles (1–500, default 30)

    Response:
        List of OHLCV candles: [
            {
                "timestamp": "2026-04-02T10:00:00Z",
                "open": float,
                "high": float,
                "low": float,
                "close": float,
                "volume": int,
            },
            ...
        ]
    """
    contract_symbol = contract_symbol.upper().strip()

    history = await futures_service.get_history(
        contract_symbol, interval=interval, limit=limit
    )

    return {
        "contract_symbol": contract_symbol,
        "interval": interval,
        "candles": history,
        "market_open": market_session.is_trading_hours(),
    }


@router.get("/spot/{symbol}")
async def get_underlying_spot(
    symbol: str,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get spot price for an underlying equity or index.

    Used for basis calculation (futures LTP - spot LTP) and cost of carry.

    Parameters:
        symbol: Canonical symbol (e.g., RELIANCE, ^NSEI)

    Response:
        {
            "symbol": str,
            "ltp": float,
            "change": float,              # Rs change
            "change_pct": float,          # % change
            "timestamp": int,             # Unix timestamp
            "market_open": bool,
        }
    """
    symbol = symbol.upper().strip()

    # Map NSE index aliases to canonical symbols
    _INDEX_MAP = {
        "NIFTY": "^NSEI",
        "NIFTY50": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "NIFTYBANK": "^NSEBANK",
        "FINNIFTY": "^CNXFIN",
        "MIDCPNIFTY": "^CNXMIDCAP",
        "SENSEX": "^BSESN",
        "NIFTYNXT50": "^CNXJUNIOR",
    }
    if symbol in _INDEX_MAP:
        symbol = _INDEX_MAP[symbol]
    elif not symbol.startswith("^"):
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

    quote = await get_system_quote_live_only(symbol, allow_recover=True)

    if not quote:
        return {
            "symbol": symbol,
            "ltp": None,
            "change": 0,
            "change_pct": 0,
            "timestamp": int(datetime.now().timestamp()),
            "market_open": market_session.is_trading_hours(),
            "available": False,
        }

    return {
        "symbol": symbol,
        "ltp": quote.get("ltp") or quote.get("price") or quote.get("lp"),
        "open": quote.get("open") or quote.get("o"),
        "high": quote.get("high") or quote.get("h"),
        "low": quote.get("low") or quote.get("l"),
        "close": quote.get("close") or quote.get("c"),
        "change": quote.get("change") or 0,
        "change_pct": quote.get("change_pct") or 0,
        "volume": quote.get("volume") or 0,
        "timestamp": _to_unix_timestamp(
            quote.get("timestamp") or quote.get("last_trade_time") or quote.get("ft")
        ),
        "market_open": market_session.is_trading_hours(),
        "available": True,
    }


# ━━━ TRADING ENDPOINTS (Simulated, Local DB Only) ━━━


class PlaceFuturesOrderRequest(BaseModel):
    """Place a simulated futures order (NEVER sent to broker)."""

    contract_symbol: str  # e.g., "RELIANCE25MAR2026FUT"
    side: str  # BUY or SELL
    order_type: str = "MARKET"  # MARKET, LIMIT, STOP_LOSS, STOP_LOSS_LIMIT
    quantity: int
    price: Optional[float] = None  # For LIMIT orders
    trigger_price: Optional[float] = None  # For STOP_LOSS orders
    client_price: Optional[float] = None  # Fallback price from client
    tag: Optional[str] = None  # Optional label


@router.post("/orders/place")
async def place_order(
    req: PlaceFuturesOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Place a simulated futures order (stored in local DB only, NEVER sent to broker).

    Request body:
        {
            "contract_symbol": "RELIANCE25MAR2026FUT",
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": 1,
            "price": null,
            "trigger_price": null,
            "tag": "My trade"
        }

    Response:
        {
            "success": true,
            "order_id": "uuid",
            "status": "FILLED" | "OPEN"
        }
    """
    req.side = str(req.side or "").upper().strip()
    req.order_type = str(req.order_type or "MARKET").upper().strip()

    if req.side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Side must be BUY or SELL")

    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    if not market_session.can_place_orders():
        session_info = market_session.get_session_info()
        state = session_info["state"]
        state_label = {
            "weekend": "Weekend",
            "holiday": "Holiday",
            "closed": "Market Closed",
            "after_market": "After Market Hours",
        }.get(state, "Market Closed")
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot place futures orders - {state_label}. "
                "Trading is available Mon-Fri 9:15 AM - 3:30 PM IST."
            ),
        )

    try:
        result = await place_futures_order(
            db=db,
            user_id=user.id,
            contract_symbol=req.contract_symbol,
            side=req.side,
            order_type=req.order_type,
            quantity=req.quantity,
            price=req.price,
            trigger_price=req.trigger_price,
            client_price=req.client_price,
            tag=req.tag,
        )
    except Exception as e:
        logger.error(f"Futures order placement failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Order placement failed")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Order failed"))

    return result


@router.get("/orders")
async def get_orders(
    status_filter: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get simulated futures orders for the user."""
    from sqlalchemy import select
    from models.futures_order import FuturesOrder

    query = select(FuturesOrder).where(FuturesOrder.user_id == user.id)

    if status_filter:
        query = query.where(FuturesOrder.status == status_filter)

    query = query.order_by(FuturesOrder.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    orders = result.scalars().all()

    return {
        "orders": [
            {
                "id": str(o.id),
                "contract_symbol": o.contract_symbol,
                "order_type": o.order_type,
                "side": o.side,
                "quantity": o.quantity,
                "price": float(o.price) if o.price else None,
                "trigger_price": float(o.trigger_price) if o.trigger_price else None,
                "filled_quantity": o.filled_quantity,
                "filled_price": float(o.filled_price) if o.filled_price else None,
                "status": o.status,
                "tag": o.tag,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "executed_at": o.executed_at.isoformat() if o.executed_at else None,
            }
            for o in orders
        ],
        "pagination": {"limit": limit, "offset": offset, "count": len(orders)},
    }


@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an open simulated futures order."""
    result = await cancel_futures_order(db=db, user_id=user.id, order_id=order_id)

    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "Cancel failed")
        )

    return result


@router.get("/positions")
async def get_positions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all open positions in simulated futures contracts."""
    positions = await get_futures_positions(db=db, user_id=user.id)
    return {"positions": positions}


@router.post("/positions/close-all")
async def close_all_positions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kill switch — cancel open futures orders and close all positions."""
    try:
        result = await close_all_futures_positions(db=db, user_id=user.id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Futures kill switch failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to close futures positions")


@router.post("/quotes/batch")
async def get_batch_quotes(
    request: dict,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Fetch quotes for multiple futures contracts in a single request.
    Replaces N individual /quote/ calls with one batch call.

    Request body:
        { "contracts": ["NIFTY24APR26F", "BANKNIFTY24APR26F", ...] }

    Response:
        { "quotes": { "NIFTY24APR26F": { ltp, bid, ask, ... }, ... } }
    """
    contracts = request.get("contracts", [])
    if not contracts or not isinstance(contracts, list):
        return {"quotes": {}, "error": "contracts list required"}

    contracts = [str(c).upper().strip() for c in contracts[:50]]
    quotes = {}

    import asyncio

    async def _fetch_one(csym: str):
        if not market_session.is_trading_hours():
            q = await futures_service.get_quote(csym)
            return csym, q
        cached = await futures_service.get_cache_quote(csym)
        if cached:
            return csym, cached
        q = await futures_service.get_quote(csym)
        return csym, q

    results = await asyncio.gather(
        *[_fetch_one(c) for c in contracts], return_exceptions=True
    )

    for result in results:
        if isinstance(result, Exception):
            continue
        csym, q = result
        if q:
            quotes[csym] = {
                "contract_symbol": csym,
                "ltp": q.get("ltp") or q.get("price") or q.get("lp"),
                "open": q.get("open") or q.get("o"),
                "high": q.get("high") or q.get("h"),
                "low": q.get("low") or q.get("l"),
                "close": q.get("close") or q.get("c"),
                **_change_fields(q),
                "volume": q.get("volume") or q.get("v") or 0,
                "oi": q.get("oi") or 0,
                "oi_change": q.get("oi_change"),
                "bid": q.get("bid") or q.get("bp1"),
                "ask": q.get("ask") or q.get("sp1"),
                "timestamp": _to_unix_timestamp(
                    q.get("timestamp") or q.get("last_trade_time")
                ),
                "market_open": market_session.is_trading_hours(),
                "available": True,
            }

    return {"quotes": quotes, "count": len(quotes)}


@router.get("/margin")
async def get_margin_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current futures margin status for the user.
    Syncs frontend margin display with backend portfolio state.
    """
    from sqlalchemy import select
    from models.futures_order import FuturesPosition
    from models.portfolio import Portfolio
    from decimal import Decimal

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    portfolio = result.scalar_one_or_none()

    if not portfolio:
        return {
            "totalFunds": 1000000,
            "usedMargin": 0,
            "availableMargin": 1000000,
            "unrealizedPnl": 0,
            "realizedPnl": 0,
        }

    from workers.futures_margin_engine import get_margin_fraction

    # Calculate used margin from open positions using SPAN-like rates
    pos_result = await db.execute(
        select(FuturesPosition).where(
            FuturesPosition.user_id == user.id,
            FuturesPosition.quantity != 0,
        )
    )
    positions = pos_result.scalars().all()

    used_margin = Decimal("0")
    unrealized_pnl = Decimal("0")
    realized_pnl = Decimal("0")

    for pos in positions:
        qty = abs(pos.quantity or 0)
        avg = pos.avg_entry_price or Decimal("0")
        margin_rate = get_margin_fraction(pos.contract_symbol)
        used_margin += (avg * qty) * margin_rate
        unrealized_pnl += pos.unrealized_pnl or Decimal("0")
        realized_pnl += pos.realized_pnl or Decimal("0")

    total_funds = float(portfolio.available_capital or 0) + float(used_margin)

    return {
        "totalFunds": round(total_funds, 2),
        "usedMargin": round(float(used_margin), 2),
        "availableMargin": round(float(portfolio.available_capital or 0), 2),
        "unrealizedPnl": round(float(unrealized_pnl), 2),
        "realizedPnl": round(float(realized_pnl), 2),
    }


@router.get("/margin/calculate/{contract_symbol}")
async def calculate_contract_margin(
    contract_symbol: str,
    quantity: int = Query(1, ge=1),
    price: Optional[float] = Query(None),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Calculate SPAN-like margin for a specific contract and quantity.
    Shows breakdown: SPAN margin + exposure margin + surcharges.
    """
    from workers.futures_margin_engine import calculate_margin_required, get_margin_rates
    from decimal import Decimal

    contract_symbol = contract_symbol.upper().strip()
    rates = get_margin_rates(contract_symbol)

    # If price not provided, fetch live
    if price is None or price <= 0:
        quote = await futures_service.get_quote(contract_symbol)
        if quote:
            price = float(
                quote.get("ltp") or quote.get("price") or quote.get("lp") or 0
            )
        if not price or price <= 0:
            return {
                "contract_symbol": contract_symbol,
                "error": "Unable to fetch price for margin calculation",
                "rates": {
                    "span_rate": float(rates["span_rate"]) * 100,
                    "exposure_rate": float(rates["exposure_rate"]) * 100,
                    "total_rate": float(rates["total_rate"]) * 100,
                    "category": rates["category"],
                    "underlying": rates["underlying"],
                },
            }

    margin = calculate_margin_required(contract_symbol, Decimal(str(price)), quantity)

    return {
        "contract_symbol": contract_symbol,
        "quantity": quantity,
        "price": price,
        "contract_value": float(margin["contract_value"]),
        "span_margin": float(margin["span_margin"]),
        "exposure_margin": float(margin["exposure_margin"]),
        "far_expiry_surcharge": float(margin["far_expiry_surcharge"]),
        "total_margin": float(margin["total_margin"]),
        "margin_percent": float(margin["margin_percent"]),
        "category": rates["category"],
        "underlying": rates["underlying"],
        "volatility_group": rates.get("volatility_group"),
    }


@router.get("/settlement/status")
async def get_settlement_status(
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Get expiry settlement worker status and stats."""
    from workers.futures_expiry_worker import futures_expiry_worker

    return {
        "worker_active": futures_expiry_worker._running,
        "stats": futures_expiry_worker.get_stats(),
    }


@router.get("/registry/status")
async def get_registry_status(
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Get futures contract registry status and health info."""
    try:
        from websocket.futures_stream import futures_stream_manager

        stream_status = futures_stream_manager.get_stream_status()
    except Exception:
        stream_status = {}

    from services.futures_service import _futures_contracts, _futures_contracts_loaded

    total_contracts = sum(len(v) for v in _futures_contracts.values())
    return {
        "loaded": _futures_contracts_loaded,
        "underlyings": len(_futures_contracts),
        "total_contracts": total_contracts,
        "stream": stream_status,
        "market_open": market_session.is_trading_hours(),
    }
