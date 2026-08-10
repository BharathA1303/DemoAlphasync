"""
Authentication routes — local username/email/password.

Flow:
    1. Frontend calls POST /api/auth/register {username, email, password, full_name}
       or POST /api/auth/login {username, password} (username field accepts
       either username or email).
    2. Backend hashes/verifies the password locally and issues a JWT.
    3. All subsequent API calls send the JWT as Bearer token.
    4. get_current_user() verifies the token on every request.

No email verification and no 2FA/TOTP yet — planned for later.
"""

import logging
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, text
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime, timezone, timedelta
import hashlib
from sqlalchemy.exc import IntegrityError

from database.connection import get_db
from models.user import User, UserSession, AdminAuditLog
from models.tenant import Tenant, UserTenantRole, TenantRole
from models.portfolio import Portfolio
from services.auth_service import hash_password, verify_password, create_access_token, decode_access_token
from services import admin_group_service
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

    # Check root admin email fallback
    if getattr(settings, "ROOT_ADMIN_EMAIL", None):
        if normalized == _normalize_admin_email(settings.ROOT_ADMIN_EMAIL):
            return True

    # Parse settings.ADMIN_EMAIL_ALLOWLIST safely (handling string fallback)
    raw_allowlist = getattr(settings, "ADMIN_EMAIL_ALLOWLIST", None) or []
    if isinstance(raw_allowlist, str):
        raw_allowlist = [x.strip() for x in raw_allowlist.split(",") if x.strip()]

    allowlist = {
        _normalize_admin_email(e)
        for e in raw_allowlist
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
            # Concurrent requests can race on the same token fingerprint.
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


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    group_token: Optional[str] = None
    institution_token: Optional[str] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[a-zA-Z0-9_.]{3,50}", v):
            raise ValueError(
                "Username must be 3-50 characters (letters, numbers, underscore, dot)."
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters.")
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 characters.")
        return v


class LoginRequest(BaseModel):
    username: str  # accepts username OR email
    password: str
    institution_token: Optional[str] = None


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
    Verify the local JWT and return the local User.

    Every protected route depends on this. The frontend sends the JWT
    issued by /api/auth/login or /api/auth/register as a Bearer token.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    claims = decode_access_token(credentials.credentials)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
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

    # Reject tokens whose session was force-logged-out by an admin, even
    # though the JWT itself is still cryptographically valid/unexpired.
    session_key = _session_fingerprint(credentials.credentials)
    result = await db.execute(
        select(UserSession).where(UserSession.session_key == session_key)
    )
    existing_session = result.scalar_one_or_none()
    if existing_session and not existing_session.is_active:
        raise HTTPException(status_code=401, detail="Session revoked. Please sign in again.")

    await _upsert_user_session(db, user, request, credentials.credentials)

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Best-effort auth dependency for routes that can serve public-safe data.

    Returns a User when a valid token is present, otherwise None.
    Never raises auth errors.
    """
    if not credentials:
        return None

    claims = decode_access_token(credentials.credentials)
    if not claims:
        return None

    user_id = claims.get("sub")
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
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


def _user_profile(user: User) -> dict:
    vc = getattr(user, "virtual_capital", None)
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "virtual_capital": float(vc) if vc is not None else 1000000.0,
        "avatar_url": user.avatar_url,
        "is_verified": user.is_verified,
        "auth_provider": user.auth_provider,
        "account_status": getattr(user, "account_status", "active"),
        "academy_role": getattr(user, "academy_role", None) or "student",
    }



def _apply_admin_allowlist_promotion(user: User) -> None:
    """Keep allowlisted admin emails in admin state."""
    user.role = "admin"
    user.account_status = "active"
    user.is_active = True
    user.is_verified = True
    user.access_expires_at = None
    user.access_duration_days = None
    user.deactivation_reason = None


# --- Routes ---


@router.post("/register")
async def register(
    req: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new local account with username + email + password."""
    email = req.email.strip().lower()
    username = req.username.strip()

    existing = await db.execute(
        select(User).where(or_(User.email == email, User.username == username))
    )
    existing_user = existing.scalar_one_or_none()
    if existing_user:
        if existing_user.email == email:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        raise HTTPException(status_code=409, detail="This username is already taken.")

    # Check if this is the first user registering in the system
    user_count_result = await db.execute(select(func.count()).select_from(User))
    total_users = user_count_result.scalar_one() or 0
    is_first_user = (total_users == 0)

    admin_allowlisted = _is_admin_allowlisted(email) or is_first_user
    auto_approval_enabled = admin_runtime_flags.is_auto_approval_enabled()

    inst_token = (req.institution_token or "").strip()
    matched_institution = None
    if inst_token:
        try:
            import uuid as uuid_module
            try:
                inst_uuid = uuid_module.UUID(inst_token)
                t_stmt = select(Tenant).where(Tenant.id == inst_uuid, Tenant.is_active == True)
            except ValueError:
                t_stmt = select(Tenant).where(Tenant.slug == inst_token, Tenant.is_active == True)
            t_res = await db.execute(t_stmt)
            matched_institution = t_res.scalar_one_or_none()
        except Exception as inst_err:
            logger.warning(f"Failed resolving institution token {inst_token}: {inst_err}")

    group_token = (req.group_token or "").strip()
    matched_group = None
    if group_token:
        try:
            matched_group = await admin_group_service.resolve_group_by_token(group_token)
        except Exception:
            matched_group = None

    group_auto_approval_enabled = bool(matched_group and matched_group.get("auto_approval"))
    effective_auto_approval = auto_approval_enabled or group_auto_approval_enabled or bool(matched_institution) or is_first_user

    try:
        # Self-serve individual tenant provisioning
        ind_tenant = Tenant(
            name=f"{(req.full_name or username).strip()}'s Individual Workspace",
            slug=f"ind-{username.lower()}-{hashlib.md5(email.encode()).hexdigest()[:8]}",
            tenant_type="individual",
            is_active=True,
        )
        db.add(ind_tenant)
        await db.flush()

        active_tenant_id = matched_institution.id if matched_institution else ind_tenant.id
        assigned_acad_role = "student" if matched_institution else ("super_admin" if is_first_user else "trader")

        user_is_verified = admin_allowlisted or bool(matched_institution)

        user = User(
            email=email,
            username=username,
            password_hash=hash_password(req.password),
            full_name=(req.full_name or username).strip(),
            auth_provider="local",
            virtual_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
            is_verified=user_is_verified,
            role=("admin" if admin_allowlisted else "user"),
            academy_role=assigned_acad_role,
            tenant_id=active_tenant_id,
            admin_level=("root" if is_first_user else None),
            account_status=(
                "active"
                if (user_is_verified or effective_auto_approval)
                else "pending_approval"
            ),
            is_active=(user_is_verified or effective_auto_approval),
            approved_at=(
                datetime.now(timezone.utc)
                if (effective_auto_approval or user_is_verified)
                else None
            ),
            access_duration_days=365 if matched_institution else (_AUTO_APPROVAL_DURATION_DAYS if effective_auto_approval else None),
            access_expires_at=(
                datetime.now(timezone.utc) + timedelta(days=365)
                if matched_institution
                else (datetime.now(timezone.utc) + timedelta(days=_AUTO_APPROVAL_DURATION_DAYS) if effective_auto_approval else None)
            ),
        )
        db.add(user)
        await db.flush()

        # Tenant-scoped RBAC mapping
        if matched_institution:
            db.add(UserTenantRole(tenant_id=matched_institution.id, user_id=user.id, role="STUDENT"))
            db.add(UserTenantRole(tenant_id=ind_tenant.id, user_id=user.id, role="TRADER"))
        else:
            tenant_role_enum = TenantRole.SUPER_ADMIN if is_first_user else TenantRole.TRADER
            user_tenant_role = UserTenantRole(
                tenant_id=ind_tenant.id,
                user_id=user.id,
                role=tenant_role_enum.name,  # Store enum NAME as string e.g. "TRADER", "SUPER_ADMIN"
            )
            db.add(user_tenant_role)

        portfolio = Portfolio(
            user_id=user.id,
            available_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
        )
        db.add(portfolio)

        if admin_allowlisted:
            _apply_admin_allowlist_promotion(user)
            if is_first_user:
                user.admin_level = "root"

        token = create_access_token(str(user.id))
        await db.flush()
        await _upsert_user_session(db, user, request, token)
        await db.commit()
        await db.refresh(user)

        assigned_group = None
        if user.role != "admin" and matched_group:
            try:
                assign_result = await admin_group_service.assign_user_to_group(
                    str(user.id), matched_group["id"]
                )
                if assign_result.get("success"):
                    assigned_group = assign_result.get("group")
            except Exception:
                logger.exception(
                    "Failed group assignment from token during registration for user_id=%s",
                    user.id,
                )

        if not admin_allowlisted and not effective_auto_approval:
            send_registration_received_email(user)

    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already in use.")
    except Exception as e:
        logger.error(f"Registration failed for {email}: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {type(e).__name__}: {e}")

    uid = str(user.id)
    event_bus.emit_nowait(
        Event(
            type=EventType.USER_LOGIN,
            data={"user_id": uid, "email": email, "action": "register", "provider": "local"},
            user_id=uid,
            source="auth",
        )
    )

    profile = await _build_user_profile(user, db)
    return {
        "message": "Registration successful",
        "is_new_user": True,
        "token": token,
        "assigned_group": (
            {"id": assigned_group.get("id"), "name": assigned_group.get("name")}
            if assigned_group
            else None
        ),
        "user": profile,
    }


@router.post("/login")
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Log in with username or email + password."""
    identifier = req.username.strip()

    try:
        result = await db.execute(
            select(User).where(or_(User.username == identifier, User.email == identifier.lower()))
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(req.password, user.password_hash or ""):
            raise HTTPException(status_code=401, detail="Invalid username/email or password.")

        if _is_admin_allowlisted(user.email):
            _apply_admin_allowlist_promotion(user)

        inst_token = (req.institution_token or "").strip()
        if inst_token:
            try:
                import uuid as uuid_module
                try:
                    inst_uuid = uuid_module.UUID(inst_token)
                    t_stmt = select(Tenant).where(Tenant.id == inst_uuid, Tenant.is_active == True)
                except ValueError:
                    t_stmt = select(Tenant).where(Tenant.slug == inst_token, Tenant.is_active == True)
                t_res = await db.execute(t_stmt)
                matched_inst = t_res.scalar_one_or_none()
                if matched_inst:
                    utr_stmt = select(UserTenantRole).where(
                        UserTenantRole.tenant_id == matched_inst.id,
                        UserTenantRole.user_id == user.id
                    )
                    utr_res = await db.execute(utr_stmt)
                    existing_utr = utr_res.scalar_one_or_none()
                    if not existing_utr:
                        db.add(UserTenantRole(tenant_id=matched_inst.id, user_id=user.id, role="STUDENT"))
                    
                    user.tenant_id = matched_inst.id
                    user.is_verified = True
                    user.account_status = "active"
                    user.is_active = True
                    if not user.approved_at:
                        user.approved_at = datetime.now(timezone.utc)
                    if not existing_utr:
                        user.academy_role = "student"
            except Exception as inst_err:
                logger.warning(f"Failed linking institution on login: {inst_err}")

        user.updated_at = datetime.now(timezone.utc)

        token = create_access_token(str(user.id))
        try:
            await _upsert_user_session(db, user, request, token)
        except Exception as sess_err:
            logger.warning("UserSession upsert failed during login: %s", sess_err)

        await db.commit()
        await db.refresh(user)

        uid = str(user.id)
        try:
            event_bus.emit_nowait(
                Event(
                    type=EventType.USER_LOGIN,
                    data={"user_id": uid, "email": user.email, "action": "login", "provider": "local"},
                    user_id=uid,
                    source="auth",
                )
            )
        except Exception:
            pass

        profile = await _build_user_profile(user, db)
        return {
            "message": "Login successful",
            "is_new_user": False,
            "token": token,
            "user": profile,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during login for %s: %s", identifier, e)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Login failed: {type(e).__name__}: {str(e)}")



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


def _require_user_id(credentials) -> str:
    """Verify local JWT and return the user id; raises 401 on failure."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = decode_access_token(credentials.credentials)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return user_id


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
    user_id = _require_user_id(credentials)

    normalised = _normalise_phone(req.phone)
    if not normalised:
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid 10-digit Indian mobile number (starts with 6–9).",
        )

    result = await db.execute(select(User).where(User.id == user_id))
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
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current user profile with tenant roles."""
    profile = await _build_user_profile(user, db)
    return {
        **profile,
        "access_expires_at": (
            user.access_expires_at.isoformat()
            if getattr(user, "access_expires_at", None)
            else None
        ),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


class SwitchTenantRequest(BaseModel):
    tenant_id: str


@router.post("/switch-tenant")
async def switch_tenant(
    req: SwitchTenantRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch active tenant context for multi-tenant users."""
    try:
        t_id = uuid.UUID(req.tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")

    try:
        t_stmt = select(Tenant).where(Tenant.id == t_id)
        t_res = await db.execute(t_stmt)
        target_tenant = t_res.scalar_one_or_none()
    except Exception as t_err:
        logger.warning("Error fetching tenant %s: %s", req.tenant_id, t_err)
        target_tenant = None

    if not target_tenant:
        raise HTTPException(status_code=404, detail="Tenant workspace not found")

    utr = None
    try:
        utr_res = await db.execute(
            select(UserTenantRole).where(
                UserTenantRole.tenant_id == t_id,
                UserTenantRole.user_id == user.id
            )
        )
        utr = utr_res.scalar_one_or_none()
    except Exception as utr_err:
        logger.warning("Error checking UserTenantRole for user %s, tenant %s: %s", user.id, t_id, utr_err)

    is_admin = user.role == "admin" or bool(user.admin_level and user.admin_level != "none")

    if not utr:
        if not is_admin and str(user.tenant_id or "") != req.tenant_id:
            raise HTTPException(status_code=403, detail="You do not have access to this tenant workspace")
        active_role = getattr(user, "academy_role", "trader") or "trader"
        try:
            utr = UserTenantRole(tenant_id=t_id, user_id=user.id, role=active_role)
            db.add(utr)
        except Exception:
            pass
    else:
        active_role = utr.role.value if hasattr(utr.role, "value") else str(utr.role)

    user.tenant_id = target_tenant.id
    user.academy_role = active_role

    try:
        await db.commit()
        await db.refresh(user)
    except Exception as commit_err:
        logger.warning("Commit error in switch_tenant: %s", commit_err)
        await db.rollback()

    profile = await _build_user_profile(user, db)
    return {
        "message": "Workspace switched successfully",
        "active_tenant": {
            "tenant_id": str(target_tenant.id),
            "tenant_name": target_tenant.name,
            "tenant_type": getattr(target_tenant, "tenant_type", "institution"),
            "role": active_role,
        },
        "user": profile,
    }


async def _build_user_profile(user: User, db: AsyncSession) -> dict:
    """Enrich user profile with all tenant roles for workspace switching."""
    base = _user_profile(user)
    tenant_roles = []
    if db:
        try:
            stmt = (
                select(UserTenantRole, Tenant)
                .join(Tenant, UserTenantRole.tenant_id == Tenant.id)
                .where(UserTenantRole.user_id == user.id)
            )
            res = await db.execute(stmt)
            rows = res.all()
            for utr, t in rows:
                tenant_roles.append({
                    "tenant_id": str(t.id),
                    "tenant_name": t.name,
                    "tenant_type": getattr(t, "tenant_type", "institution"),
                    "role": utr.role.value if hasattr(utr.role, "value") else str(utr.role),
                })
        except Exception as query_err:
            logger.warning(f"Tenant join query error in _build_user_profile: {query_err}")
            try:
                utr_stmt = select(UserTenantRole).where(UserTenantRole.user_id == user.id)
                utr_res = await db.execute(utr_stmt)
                for utr in utr_res.scalars().all():
                    tenant_roles.append({
                        "tenant_id": str(utr.tenant_id),
                        "tenant_name": "Workspace",
                        "tenant_type": "institution",
                        "role": utr.role.value if hasattr(utr.role, "value") else str(utr.role),
                    })
            except Exception:
                pass

    if not tenant_roles and user.tenant_id and db:
        try:
            t_res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
            t = t_res.scalar_one_or_none()
            if t:
                tenant_roles.append({
                    "tenant_id": str(t.id),
                    "tenant_name": t.name,
                    "tenant_type": getattr(t, "tenant_type", "institution"),
                    "role": getattr(user, "academy_role", "trader") or "trader",
                })
        except Exception as t_err:
            logger.warning(f"Tenant direct query error in _build_user_profile: {t_err}")

    if not tenant_roles and user.tenant_id:
        tenant_roles.append({
            "tenant_id": str(user.tenant_id),
            "tenant_name": "Individual Workspace",
            "tenant_type": "individual",
            "role": getattr(user, "academy_role", "trader") or "trader",
        })

    base["tenant_roles"] = tenant_roles
    return base



@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate the current session and acknowledge logout."""
    user_id = None
    if credentials:
        claims = decode_access_token(credentials.credentials)
        if claims:
            user_id = claims.get("sub")
            session_key = _session_fingerprint(credentials.credentials)
            result = await db.execute(
                select(UserSession).where(UserSession.session_key == session_key)
            )
            session = result.scalar_one_or_none()
            if session:
                session.is_active = False
                await db.commit()

    if user_id:
        event_bus.emit_nowait(
            Event(
                type=EventType.USER_LOGOUT,
                data={"user_id": user_id},
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

    The user is immediately blocked from access.
    Admin can still see and permanently delete later if needed.
    """
    snapshot = {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "auth_provider": user.auth_provider,
        "deleted_by_user": True,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }

    user.account_status = "deleted"
    user.is_active = False
    user.deactivation_reason = "Self-deleted by user"
    user.updated_at = datetime.now(timezone.utc)

    db.add(
        AdminAuditLog(
            admin_user_id=None,
            action="self_delete_account",
            target_user_id=user.id,
            details=snapshot,
            ip_address=None,
        )
    )

    await db.commit()

    try:
        event_bus.emit_nowait(
            Event(
                type=EventType.USER_LOGOUT,
                data={
                    "user_id": str(user.id),
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
    }
