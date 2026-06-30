"""
Broker Routes — OAuth connect / callback / disconnect / status.

Supported brokers: zebu, aliceblue, zerodha

Endpoints:
    GET    /api/broker/zebu/connect         → Zebu OAuth redirect URL
    POST   /api/broker/zebu/callback        → Exchange Zebu auth code
    POST   /api/broker/zebu/login           → Zebu direct QuickAuth login
    DELETE /api/broker/zebu/disconnect      → Revoke Zebu connection
    POST   /api/broker/zebu/manual-token    → Dev: inject Zebu token manually

    GET    /api/broker/aliceblue/connect    → Alice Blue OAuth redirect URL
    POST   /api/broker/aliceblue/callback   → Exchange Alice Blue auth code
    DELETE /api/broker/aliceblue/disconnect → Revoke Alice Blue connection

    GET    /api/broker/zerodha/connect      → Zerodha Kite OAuth redirect URL
    POST   /api/broker/zerodha/callback     → Exchange Zerodha request_token
    DELETE /api/broker/zerodha/disconnect   → Revoke Zerodha connection

    GET    /api/broker/status               → Connection status (any broker)
    GET    /api/broker/all-status           → Status for all 3 brokers
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
import logging

from database.connection import get_db
from routes.auth import get_current_user
from models.user import User
from services.broker_auth import broker_auth_service
from services.broker_session import broker_session_manager

router = APIRouter(prefix="/api/broker", tags=["Broker"])
logger = logging.getLogger(__name__)


# ── Schemas ─────────────────────────────────────────────────────────


class ZebuCallbackRequest(BaseModel):
    auth_code: str = ""
    state: Optional[str] = ""
    susertoken: Optional[str] = ""
    uid: Optional[str] = ""
    actid: Optional[str] = ""


class AliceBluCallbackRequest(BaseModel):
    auth_code: str
    state: Optional[str] = ""
    broker_user_id: Optional[str] = ""


class ZerodhaCallbackRequest(BaseModel):
    request_token: str
    state: str


class DirectLoginRequest(BaseModel):
    zebu_user_id: str
    password: str
    factor2: Optional[str] = ""
    api_key: Optional[str] = ""
    vendor_code: Optional[str] = ""


class ManualTokenRequest(BaseModel):
    session_token: str
    broker_user_id: Optional[str] = ""
    uid: Optional[str] = ""


class SaveCredentialsRequest(BaseModel):
    api_key: Optional[str] = ""
    api_secret: Optional[str] = ""
    vendor_code: Optional[str] = ""
    client_id: Optional[str] = ""
    display_name: Optional[str] = ""
    # Zebu: DOB (DD-MM-YYYY) or PAN, used as QuickAuth's factor2.
    factor2: Optional[str] = ""
    # Optional — when supplied together with factor2 (Zebu) or totp_secret
    # (Alice Blue), enables fully headless daily session refresh with zero
    # browser interaction. Left blank, Refresh falls back to a one-click
    # OAuth re-redirect.
    trading_password: Optional[str] = ""
    totp_secret: Optional[str] = ""
    # Alice Blue: not used by the ANT API for manual orders — stored for
    # parity/future use only.
    algo_id: Optional[str] = ""


# ── Zebu ─────────────────────────────────────────────────────────────


@router.get("/zebu/connect")
async def zebu_connect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate Zebu OAuth redirect URL."""
    try:
        return await broker_auth_service.generate_connect_url(db=db, user_id=user.id, broker="zebu")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/zebu/callback")
async def zebu_callback(
    body: ZebuCallbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Zebu auth code for access token and activate session."""
    try:
        result = await broker_auth_service.handle_callback(
            db=db,
            broker="zebu",
            auth_code=body.auth_code,
            state=body.state or "",
            susertoken=body.susertoken or "",
            uid=body.uid or "",
            actid=body.actid or "",
            fallback_user_id=str(user.id),
        )
        if result.get("success"):
            await db.commit()
            await broker_session_manager.create_session(user_id=user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/zebu/login")
async def zebu_direct_login(
    body: DirectLoginRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Direct Zebu login via QuickAuth API (no OAuth redirect needed)."""
    try:
        result = await broker_auth_service.direct_login(
            db=db,
            user_id=user.id,
            zebu_uid=body.zebu_user_id,
            password=body.password,
            totp=body.factor2 or "",
            api_key=body.api_key or "",
            vendor_code=body.vendor_code or "",
        )
        if result.get("success"):
            await db.commit()
            await broker_session_manager.create_session(user_id=user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/zebu/disconnect")
async def zebu_disconnect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Zebu broker account."""
    disconnected = await broker_auth_service.disconnect(db=db, user_id=user.id, broker="zebu")
    if not disconnected:
        raise HTTPException(status_code=404, detail="No Zebu connection found")
    await db.commit()
    await broker_session_manager.destroy_session(user_id=user.id)
    return {"success": True, "message": "Zebu disconnected"}


@router.post("/zebu/manual-token")
async def zebu_manual_token(
    body: ManualTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dev: manually inject a Zebu session token."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, and_
    from models.broker import BrokerAccount
    from services.broker_crypto import encrypt_token, encrypt_json

    extra = {"uid": body.uid or "", "actid": body.broker_user_id or "", "manual": True}
    result = await db.execute(
        select(BrokerAccount).where(
            and_(BrokerAccount.user_id == user.id, BrokerAccount.broker == "zebu")
        )
    )
    account = result.scalar_one_or_none()
    if account:
        account.access_token_enc = encrypt_token(body.session_token)
        account.broker_user_id = body.broker_user_id or account.broker_user_id
        account.extra_data_enc = encrypt_json(extra)
        account.is_active = True
        account.token_expiry = datetime.now(timezone.utc) + timedelta(hours=8)
        account.last_used_at = datetime.now(timezone.utc)
    else:
        account = BrokerAccount(
            user_id=user.id,
            broker="zebu",
            broker_user_id=body.broker_user_id or "",
            access_token_enc=encrypt_token(body.session_token),
            extra_data_enc=encrypt_json(extra),
            is_active=True,
            token_expiry=datetime.now(timezone.utc) + timedelta(hours=8),
            connected_at=datetime.now(timezone.utc),
            last_used_at=datetime.now(timezone.utc),
        )
        db.add(account)
    await db.flush()
    await db.commit()
    await broker_session_manager.create_session(user_id=user.id)
    return {"success": True, "message": "Session token stored (manual)", "broker_user_id": body.broker_user_id}


# ── Alice Blue ────────────────────────────────────────────────────────


@router.get("/aliceblue/connect")
async def aliceblue_connect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate Alice Blue OAuth redirect URL."""
    try:
        return await broker_auth_service.generate_connect_url(db=db, user_id=user.id, broker="aliceblue")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/aliceblue/callback")
async def aliceblue_callback(
    body: AliceBluCallbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Alice Blue OAuth auth code for access token and activate session."""
    try:
        result = await broker_auth_service.handle_callback(
            db=db,
            broker="aliceblue",
            auth_code=body.auth_code,
            state=body.state or "",
            broker_user_id=body.broker_user_id or "",
            fallback_user_id=str(user.id),
        )
        if result.get("success"):
            await db.commit()
            await broker_session_manager.create_session(user_id=user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/aliceblue/disconnect")
async def aliceblue_disconnect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Alice Blue broker account."""
    disconnected = await broker_auth_service.disconnect(db=db, user_id=user.id, broker="aliceblue")
    if not disconnected:
        raise HTTPException(status_code=404, detail="No Alice Blue connection found")
    await db.commit()
    await broker_session_manager.destroy_session(user_id=user.id)
    return {"success": True, "message": "Alice Blue disconnected"}


# ── Zerodha ───────────────────────────────────────────────────────────


@router.get("/zerodha/connect")
async def zerodha_connect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate Zerodha Kite OAuth redirect URL."""
    try:
        return await broker_auth_service.generate_connect_url(db=db, user_id=user.id, broker="zerodha")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/zerodha/callback")
async def zerodha_callback(
    body: ZerodhaCallbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange Zerodha request_token for access_token.

    Zerodha sends back a request_token (not OAuth auth_code) via redirect.
    We exchange it with api_key + api_secret to get the actual access_token.
    """
    try:
        result = await broker_auth_service.handle_callback(
            db=db,
            broker="zerodha",
            auth_code=body.request_token,
            state=body.state,
            request_token=body.request_token,
        )
        if result.get("success"):
            await db.commit()
            await broker_session_manager.create_session(user_id=user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/zerodha/disconnect")
async def zerodha_disconnect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Zerodha broker account."""
    disconnected = await broker_auth_service.disconnect(db=db, user_id=user.id, broker="zerodha")
    if not disconnected:
        raise HTTPException(status_code=404, detail="No Zerodha connection found")
    await db.commit()
    await broker_session_manager.destroy_session(user_id=user.id)
    return {"success": True, "message": "Zerodha disconnected"}


# ── App credentials (per-user API key/secret, encrypted) ──────────────


_VALID_BROKERS = ("zebu", "aliceblue", "zerodha")


def _validate_broker(broker: str) -> str:
    broker = (broker or "").lower().strip()
    if broker not in _VALID_BROKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported broker: {broker}")
    return broker


@router.post("/{broker}/credentials")
async def save_broker_credentials(
    broker: str,
    body: SaveCredentialsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save (or update) the user's own app credentials for a broker.

    Alice Blue / Zerodha: api_key + api_secret (their own registered app).
    Zebu: api_key (MYNT App Key) + trading_password + factor2 (DOB/PAN);
    api_secret is optional (OAuth secret for accounts with browser login access).
    """
    broker = _validate_broker(broker)
    fields = {
        "api_key": body.api_key or "",
        "api_secret": body.api_secret or "",
        "vendor_code": body.vendor_code or "",
        "client_id": body.client_id or "",
        "display_name": body.display_name or "",
        "factor2": body.factor2 or "",
        "trading_password": body.trading_password or "",
        "totp_secret": body.totp_secret or "",
        "algo_id": body.algo_id or "",
    }
    try:
        result = await broker_auth_service.save_credentials(
            db=db, user_id=user.id, broker=broker, fields=fields
        )
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{broker}/credentials")
async def get_broker_credentials_status(
    broker: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return whether app credentials are saved for a broker (masked preview only)."""
    broker = _validate_broker(broker)
    return await broker_auth_service.get_credentials_status(db=db, user_id=user.id, broker=broker)


@router.delete("/{broker}/credentials")
async def clear_broker_credentials(
    broker: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove saved broker app credentials (session tokens too). User accounts are untouched."""
    broker = _validate_broker(broker)
    cleared = await broker_auth_service.clear_saved_credentials(
        db=db, user_id=user.id, broker=broker
    )
    await db.commit()
    await broker_session_manager.destroy_session(user_id=user.id)
    return {
        "success": True,
        "cleared": cleared,
        "broker": broker,
        "message": "Saved broker credentials cleared. Enter fresh credentials to connect.",
    }


# ── Status ────────────────────────────────────────────────────────────


@router.get("/status")
async def broker_status(
    broker: str = Query(default="zebu"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return connection status for a specific broker (mocked for simulation mode)."""
    return {
        "connected": True,
        "broker_user_id": "simulation_user",
        "broker": broker,
        "display_name": f"Simulated {broker.capitalize()}",
        "expires_at": None,
    }


@router.get("/all-status")
async def broker_all_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return connection status for all 3 brokers (mocked for simulation mode)."""
    return {
        "any_connected": True,
        "brokers": {
            "zebu": {
                "connected": True,
                "broker_user_id": "simulation_user",
                "display_name": "Simulated Zebu",
            },
            "aliceblue": {
                "connected": False,
                "broker_user_id": None,
                "display_name": None,
            },
            "zerodha": {
                "connected": False,
                "broker_user_id": None,
                "display_name": None,
            },
        },
    }


@router.post("/{broker}/refresh")
async def refresh_broker_session(
    broker: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Refresh a broker session for the day.

    Zero-click when the user saved a trading password (+ DOB/PAN for Zebu,
    + TOTP secret for Alice Blue) at connect time — re-authenticates headlessly
    server-side. Otherwise returns a one-click OAuth redirect URL.
    """
    broker = _validate_broker(broker)
    try:
        result = await broker_auth_service.refresh_session(db=db, user_id=user.id, broker=broker)
        if result.get("success"):
            await db.commit()
            await broker_session_manager.create_session(user_id=user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Segment check (Zebu-specific dev helper) ──────────────────────────


@router.get("/zebu/segment-check")
async def broker_segment_check(user: User = Depends(get_current_user)):
    """Verify market-data accessibility per segment using active Zebu session."""
    provider = broker_session_manager.get_session(user.id)
    if provider is None:
        provider = broker_session_manager.get_any_session()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="No active broker session. Connect a broker first.",
        )

    async def _check_segment(exchange: str, search_text: str, matcher=None) -> dict:
        try:
            search = await provider._rest_post(
                "/SearchScrip", {"exch": exchange, "stext": search_text}
            )
            if not search or search.get("stat") != "Ok":
                return {"enabled": False, "exchange": exchange, "reason": "SearchScrip failed"}
            values = search.get("values", []) or []
            if not values:
                return {"enabled": False, "exchange": exchange, "reason": "No instruments returned"}
            picked = next((x for x in values if matcher and matcher(x)), values[0])
            token = str(picked.get("token", "")).strip()
            if not token:
                return {"enabled": False, "exchange": exchange, "reason": "Token missing"}
            quote = await provider._rest_post("/GetQuotes", {"exch": exchange, "token": token})
            if not quote or quote.get("stat") != "Ok":
                return {"enabled": False, "exchange": exchange, "reason": "GetQuotes failed"}
            return {"enabled": True, "exchange": exchange, "instrument": picked.get("tsym"), "ltp": quote.get("lp")}
        except Exception as e:
            return {"enabled": False, "exchange": exchange, "reason": str(e)}

    nse = await _check_segment("NSE", "RELIANCE", lambda x: "-EQ" in str(x.get("tsym", "")))
    nfo = await _check_segment("NFO", "NIFTY", lambda x: str(x.get("tsym", "")).upper().endswith(("FUT", "CE", "PE")))
    mcx = await _check_segment("MCX", "GOLD", lambda x: "GOLD" in str(x.get("tsym", "")).upper())

    return {
        "ok": bool(nse.get("enabled") and nfo.get("enabled") and mcx.get("enabled")),
        "segments": {"nse": nse, "nfo": nfo, "mcx": mcx},
    }


# ── Deprecated: master-status ─────────────────────────────────────────


@router.get("/master-status")
async def broker_master_status():
    """Deprecated — master session is disabled. Each user connects their own broker."""
    return {
        "connected": False,
        "error": "Master session disabled. Users must connect their own broker account.",
        "details": {"configured": False, "user_id": None, "missing": []},
    }
