"""
Authentication routes — Firebase-based.

Flow:
    1. Frontend signs user in via Firebase JS SDK (Google, Email/Password, etc.)
    2. Frontend gets a Firebase ID token and sends it to POST /api/auth/sync
    3. Backend verifies the token via Firebase Admin SDK
    4. Backend finds-or-creates a local User row (linked by firebase_uid)
    5. Backend returns the local user profile
    6. All subsequent API calls send the Firebase ID token as Bearer token
    7. get_current_user() verifies the token on every request
"""

import logging
import hashlib
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta

from database.connection import get_db
from models.user import User, UserSession, AdminAuditLog
from models.portfolio import Portfolio
from services.auth_service import verify_id_token
from services import admin_group_service
from services.account_deletion_service import (
    try_delete_firebase_account,
)
from core.event_bus import event_bus, Event, EventType
from core.admin_runtime_flags import admin_runtime_flags
from config.settings import settings
from services.email_service import send_registration_received_email

logger = logging.getLogger(__name__)

_AUTO_APPROVAL_DURATION_DAYS = 30

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
security = HTTPBearer(auto_error=False)


def _coerce_utc_datetime(value):
    """Normalize DB datetime values across SQLite/Postgres to UTC-aware."""
    if value is None:
        return None

    dt = value
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None

    if not isinstance(dt, datetime):
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _normalize_admin_email(email: str) -> str:
    """Normalize email for allowlist comparisons.

    For Gmail/Googlemail, treat dot/plus aliases as the same mailbox.
    """
    if not email:
        return ""

    normalized = email.strip().lower()
    if "@" not in normalized:
        return normalized

    local, domain = normalized.split("@", 1)
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"

    return f"{local}@{domain}"


def _is_admin_allowlisted(email: str) -> bool:
    normalized = _normalize_admin_email(email)
    if not normalized:
        return False

    allowlist = {
        _normalize_admin_email(e)
        for e in (settings.ADMIN_EMAIL_ALLOWLIST or [])
        if isinstance(e, str) and e.strip()
    }
    return normalized in allowlist


def _session_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _upsert_user_session(
    db: AsyncSession,
    user: User,
    request: Request,
    token: str,
) -> None:
    """Create/update a user session row keyed by token fingerprint."""
    if not user or not token:
        return

    session_key = _session_fingerprint(token)
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent", "")[:500] if request else ""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(UserSession).where(UserSession.session_key == session_key)
    )
    session = result.scalar_one_or_none()

    if session:
        session.last_seen_at = now
        session.is_active = True
        session.ip_address = ip_address
        session.user_agent = user_agent
    else:
        try:
            async with db.begin_nested():
                db.add(
                    UserSession(
                        user_id=user.id,
                        session_key=session_key,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        first_seen_at=now,
                        last_seen_at=now,
                        is_active=True,
                    )
                )
                await db.flush()
            return
        except IntegrityError:
            # Concurrent sync requests can race on the same token fingerprint.
            # Fall through to a read+update path instead of failing login.
            pass

        result = await db.execute(
            select(UserSession).where(UserSession.session_key == session_key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.last_seen_at = now
            existing.is_active = True
            existing.ip_address = ip_address
            existing.user_agent = user_agent


# --- Schemas ---


class SyncRequest(BaseModel):
    """Sent by frontend after Firebase sign-in to sync with backend."""

    username: Optional[str] = None
    auth_intent: Optional[str] = None
    group_token: Optional[str] = None


class PhoneSubmitRequest(BaseModel):
    """Phone number submission — validated and saved as contact info."""

    phone: str  # 10-digit Indian mobile or +91XXXXXXXXXX


# --- Core Dependency: get_current_user ---


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Verify Firebase ID token and return the local User.

    Every protected route depends on this. The frontend sends the
    Firebase ID token as a Bearer token in the Authorization header.

    In DEBUG mode without Firebase credentials, a demo user is
    auto-created so the app works out of the box.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Verify Firebase ID token
    claims = verify_id_token(credentials.credentials)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    firebase_uid = claims.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Look up local user by firebase_uid
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalar_one_or_none()

    if not user:
        # In DEBUG mode, auto-create the demo user so the app works
        # without any Firebase setup
        if settings.DEBUG:
            email = claims.get("email", "demo@alphasync.app")
            user = User(
                firebase_uid=firebase_uid,
                email=email,
                username=claims.get("name", "demo_trader").lower().replace(" ", "_"),
                full_name=claims.get("name", "Demo Trader"),
                auth_provider="demo",
                virtual_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
                is_verified=True,
                is_active=True,
                account_status="active",
            )
            db.add(user)
            await db.flush()

            # Create portfolio for the demo user
            portfolio = Portfolio(
                user_id=user.id,
                available_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
            )
            db.add(portfolio)
            await db.commit()
            await db.refresh(user)
            logger.info(f"Auto-created demo user: {user.email} (uid={firebase_uid})")
        else:
            raise HTTPException(
                status_code=401,
                detail="User not found. Please sign in again.",
            )

    account_status = (getattr(user, "account_status", None) or "active").strip().lower()

    # account_status is the authoritative access gate.
    # Even if is_active drifts to True by mistake, non-active statuses stay blocked.
    if account_status != "active":
        if account_status == "pending_approval":
            raise HTTPException(
                status_code=403,
                detail="PENDING_APPROVAL: Your account is under review. You will receive an email once approved.",
            )
        if account_status == "expired":
            raise HTTPException(
                status_code=403,
                detail="ACCESS_EXPIRED: Your demo trading access has expired. Contact support for extension.",
            )
        if account_status == "deactivated":
            raise HTTPException(
                status_code=403,
                detail="DEACTIVATED: Your account has been deactivated. Contact support for assistance.",
            )
        raise HTTPException(
            status_code=403,
            detail="ACCOUNT_RESTRICTED: Your account access is restricted. Contact support.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="DEACTIVATED: Your account has been deactivated. Contact support for assistance.",
        )

    # Check if access has expired (active user but past expiry date)
    if hasattr(user, "access_expires_at") and user.access_expires_at:
        expires_at = _coerce_utc_datetime(user.access_expires_at)
        if expires_at and datetime.now(timezone.utc) > expires_at:
            user.account_status = "expired"
            user.is_active = False
            # Persist the state transition immediately so expiry is consistent
            # even if a background worker has not run yet.
            await db.commit()
            raise HTTPException(
                status_code=403,
                detail="ACCESS_EXPIRED: Your demo trading access has expired. Contact support for extension.",
            )

    await _upsert_user_session(db, user, request, credentials.credentials)

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Best-effort auth dependency for routes that can serve public-safe data.

    Returns a User when a valid Firebase token is present, otherwise None.
    Never raises auth errors.
    """
    if not credentials:
        return None

    claims = verify_id_token(credentials.credentials)
    if not claims:
        return None

    firebase_uid = claims.get("uid")
    if not firebase_uid:
        return None

    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalar_one_or_none()
    if not user:
        return None

    account_status = (getattr(user, "account_status", None) or "active").strip().lower()
    if account_status != "active" or not user.is_active:
        return None

    if hasattr(user, "access_expires_at") and user.access_expires_at:
        expires_at = _coerce_utc_datetime(user.access_expires_at)
        if expires_at and datetime.now(timezone.utc) > expires_at:
            return None

    return user


# --- Routes ---


@router.post("/sync")
async def sync_user(
    req: SyncRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync Firebase user with local database.

    Called by the frontend after every Firebase sign-in (login or register).
    Finds existing user by firebase_uid or creates a new one.
    Returns the local user profile for the frontend store.
    """
    if not credentials:
        logger.warning("Sync called without credentials")
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials
    logger.info(
        f"Sync request — token length: {len(token)}, first 20 chars: {token[:20]}..."
    )

    claims = verify_id_token(token)
    if not claims:
        logger.error(
            "Firebase token verification failed — is FIREBASE_CREDENTIALS_JSON set?"
        )
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    firebase_uid = claims.get("uid")
    email = claims.get("email", "")
    name = claims.get("name", "")
    picture = claims.get("picture")
    email_verified = claims.get("email_verified", False)
    provider = claims.get("firebase", {}).get("sign_in_provider", "unknown")
    auth_intent = (req.auth_intent or "login").strip().lower()
    group_token = (req.group_token or "").strip()
    admin_allowlisted = _is_admin_allowlisted(email)
    auto_approval_enabled = admin_runtime_flags.is_auto_approval_enabled()

    matched_group = None
    if group_token:
        try:
            matched_group = await admin_group_service.resolve_group_by_token(group_token)
        except Exception:
            matched_group = None

    group_auto_approval_enabled = bool(
        matched_group and matched_group.get("auto_approval")
    )
    effective_auto_approval = auto_approval_enabled or group_auto_approval_enabled

    logger.info(
        "Auth sync identity: email=%s provider=%s intent=%s allowlisted_admin=%s auto_approval_global=%s auto_approval_group=%s grouped=%s",
        email,
        provider,
        auth_intent,
        admin_allowlisted,
        auto_approval_enabled,
        group_auto_approval_enabled,
        bool(group_token),
    )

    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # Try to find existing user by firebase_uid
        result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
        user = result.scalar_one_or_none()

        is_new = False

        if not user:
            # Also check if email already exists (edge case: migrated user)
            if email:
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()

            if user:
                # Link existing email-based user to Firebase
                user.firebase_uid = firebase_uid
                user.auth_provider = provider
                if picture and not user.avatar_url:
                    user.avatar_url = picture
                if email_verified:
                    user.is_verified = True

                # Auto-promote allowlisted admin emails.
                if admin_allowlisted:
                    user.role = "admin"
                    user.account_status = "active"
                    user.is_active = True
                    user.is_verified = True
                    user.access_expires_at = None
                    user.access_duration_days = None
                    user.deactivation_reason = None
            else:
                if (
                    auth_intent == "login"
                    and not admin_allowlisted
                    and not effective_auto_approval
                ):
                    raise HTTPException(
                        status_code=404,
                        detail="Account not found. Please create an account first.",
                    )

                # Create brand-new user
                is_new = True

                # Generate username from email or name
                username = req.username
                if not username:
                    username = (
                        email.split("@")[0] if email else f"user_{firebase_uid[:8]}"
                    )

                # Ensure username uniqueness
                base_username = username
                counter = 1
                while True:
                    result = await db.execute(
                        select(User).where(User.username == username)
                    )
                    if not result.scalar_one_or_none():
                        break
                    username = f"{base_username}{counter}"
                    counter += 1

                user = User(
                    firebase_uid=firebase_uid,
                    email=email,
                    username=username,
                    full_name=name or username,
                    auth_provider=provider,
                    avatar_url=picture,
                    virtual_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
                    is_verified=(email_verified or admin_allowlisted),
                    role=("admin" if admin_allowlisted else "user"),
                    account_status=(
                        "active"
                        if (admin_allowlisted or effective_auto_approval)
                        else "pending_approval"
                    ),
                    is_active=(admin_allowlisted or effective_auto_approval),
                    approved_at=(
                        datetime.now(timezone.utc)
                        if effective_auto_approval and not admin_allowlisted
                        else None
                    ),
                    access_duration_days=(
                        _AUTO_APPROVAL_DURATION_DAYS
                        if effective_auto_approval and not admin_allowlisted
                        else None
                    ),
                    access_expires_at=(
                        datetime.now(timezone.utc)
                        + timedelta(days=_AUTO_APPROVAL_DURATION_DAYS)
                        if effective_auto_approval and not admin_allowlisted
                        else None
                    ),
                )
                db.add(user)
                await db.flush()

                # Create portfolio for new user
                portfolio = Portfolio(
                    user_id=user.id,
                    available_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
                )
                db.add(portfolio)

        # Keep allowlisted admin emails in admin state on each sync.
        if user and admin_allowlisted:
            user.role = "admin"
            user.account_status = "active"
            user.is_active = True
            user.is_verified = True
            user.access_expires_at = None
            user.access_duration_days = None
            user.deactivation_reason = None

        # Update last login info
        user.updated_at = datetime.now(timezone.utc)

        await db.flush()  # assign IDs for new rows before session upsert
        await _upsert_user_session(db, user, request, token)
        await db.commit()  # single commit for user + portfolio + session
        await db.refresh(user)

        assigned_group = None
        if user.role != "admin" and matched_group:
            try:
                assign_result = await admin_group_service.assign_user_to_group(
                    str(user.id),
                    matched_group["id"],
                )
                if assign_result.get("success"):
                    assigned_group = assign_result.get("group")
            except Exception:
                logger.exception(
                    "Failed group assignment from token during auth sync for user_id=%s",
                    user.id,
                )

        # Send registration confirmation email for new non-admin users
        if is_new and not admin_allowlisted and not effective_auto_approval:
            send_registration_received_email(user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Sync database error for {email} (firebase_uid={firebase_uid}): {e}",
            exc_info=True,
        )
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Account sync failed: {type(e).__name__}: {e}",
        )

    uid = str(user.id)

    # Emit event
    event_bus.emit_nowait(
        Event(
            type=EventType.USER_LOGIN,
            data={
                "user_id": uid,
                "email": email,
                "action": "register" if is_new else "login",
                "provider": provider,
            },
            user_id=uid,
            source="auth",
        )
    )

    return {
        "message": "Registration successful" if is_new else "Login successful",
        "is_new_user": is_new,
        "assigned_group": {
            "id": assigned_group.get("id"),
            "name": assigned_group.get("name"),
        }
        if assigned_group
        else None,
        "user": {
            "id": uid,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role,
            "virtual_capital": float(user.virtual_capital),
            "avatar_url": user.avatar_url,
            "is_verified": user.is_verified,
            "auth_provider": user.auth_provider,
            "account_status": getattr(user, "account_status", "active"),
        },
    }


def _normalise_phone(raw: str):
    """Validate and normalise Indian mobile number → '+91XXXXXXXXXX' or None."""
    digits = re.sub(r"[\s\-\(\)]", "", raw.strip())
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return None
    return f"+91{digits}"


def _require_firebase_uid(credentials) -> str:
    """Verify Firebase token and return firebase_uid; raises 401 on failure."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = verify_id_token(credentials.credentials)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    uid = claims.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return uid


@router.post("/set-phone")
async def set_phone(
    req: PhoneSubmitRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """
    Save the user's Indian mobile number as contact info.

    Validates the number format (10-digit, starts with 6-9) and persists it.
    Does NOT enforce account_status so pending_approval users can complete
    their profile. No OTP required — number is for contact purposes only.
    """
    firebase_uid = _require_firebase_uid(credentials)

    normalised = _normalise_phone(req.phone)
    if not normalised:
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid 10-digit Indian mobile number (starts with 6–9).",
        )

    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.phone = normalised
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    logger.info("Phone saved for %s → %s", user.email, normalised)
    return {"message": "Mobile number saved.", "phone": user.phone}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Return current user profile."""
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "virtual_capital": float(user.virtual_capital),
        "avatar_url": user.avatar_url,
        "is_verified": user.is_verified,
        "auth_provider": user.auth_provider,
        "account_status": getattr(user, "account_status", "active"),
        "access_expires_at": (
            user.access_expires_at.isoformat()
            if getattr(user, "access_expires_at", None)
            else None
        ),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Server-side logout acknowledgment.

    The actual sign-out happens on the client (Firebase signOut).
    This endpoint is for event tracking and any server-side cleanup.
    """
    user_id = None
    if credentials:
        claims = verify_id_token(credentials.credentials)
        if claims:
            user_id = claims.get("uid")

    if user_id:
        event_bus.emit_nowait(
            Event(
                type=EventType.USER_LOGOUT,
                data={"firebase_uid": user_id},
                user_id=user_id,
                source="auth",
            )
        )

    return {"message": "Logged out successfully"}


@router.delete("/delete-account")
async def delete_own_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-delete the authenticated user account (keep DB row/data for admin review).

    The user is immediately blocked from access and Firebase auth is revoked/deleted
    best-effort, while admin can still see and permanently delete later if needed.
    """
    snapshot = {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "auth_provider": user.auth_provider,
        "deleted_by_user": True,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }

    firebase_delete = try_delete_firebase_account(user.firebase_uid)

    user.account_status = "deleted"
    user.is_active = False
    user.deactivation_reason = "Self-deleted by user"
    user.updated_at = datetime.now(timezone.utc)

    db.add(
        AdminAuditLog(
            admin_user_id=None,
            action="self_delete_account",
            target_user_id=user.id,
            details={
                **snapshot,
                "firebase_delete": firebase_delete,
            },
            ip_address=None,
        )
    )

    try:
        event_bus.emit_nowait(
            Event(
                type=EventType.USER_LOGOUT,
                data={
                    "firebase_uid": user.firebase_uid,
                    "self_deleted": True,
                    "email": user.email,
                },
                user_id=str(user.id),
                source="auth",
            )
        )
    except Exception:
        logger.exception("Failed to emit logout event for self-deleted account: %s", user.email)

    logger.info("User self-deleted account: %s", user.email)
    return {
        "success": True,
        "message": "Your account has been deleted and access is blocked.",
        "firebase_deleted": firebase_delete.get("deleted", False),
    }
