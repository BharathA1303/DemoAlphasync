"""
Admin 2FA Service — TOTP generation, verification, and session management.

Uses pyotp for TOTP and the existing AES-256-GCM encryption from broker_crypto
to encrypt TOTP secrets at rest in the database.
"""

import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pyotp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from models.user import TwoFactorAuth, AdminSession, User
from services.broker_crypto import encrypt_token, decrypt_token
from config.settings import settings

logger = logging.getLogger(__name__)

# Failed attempt tracking (in-memory — resets on restart, which is acceptable)
_failed_attempts: dict[str, list[datetime]] = {}
_LOCKOUT_MAX = 5
_LOCKOUT_WINDOW = timedelta(minutes=15)


def _coerce_utc_datetime(value) -> Optional[datetime]:
    """Best-effort conversion for DB datetime values across dialects.

    SQLite may return naive datetimes (or strings in some edge cases), while
    Postgres returns tz-aware values. Normalize to UTC-aware datetimes.
    """
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


def _check_lockout(user_id: str) -> bool:
    """Return True if the user is locked out from too many failed 2FA attempts."""
    now = datetime.now(timezone.utc)
    attempts = _failed_attempts.get(user_id, [])
    # Prune old attempts
    attempts = [t for t in attempts if now - t < _LOCKOUT_WINDOW]
    _failed_attempts[user_id] = attempts
    return len(attempts) >= _LOCKOUT_MAX


def _record_failure(user_id: str):
    """Record a failed 2FA attempt."""
    now = datetime.now(timezone.utc)
    _failed_attempts.setdefault(user_id, []).append(now)


def _clear_failures(user_id: str):
    """Clear failed attempts after a successful verification."""
    _failed_attempts.pop(user_id, None)


def _safe_decrypt_totp_secret(secret_enc: str) -> Optional[str]:
    """Decrypt a stored TOTP secret; return None instead of raising."""
    if not secret_enc:
        return None
    try:
        secret = decrypt_token(secret_enc)
        return secret or None
    except Exception as exc:
        logger.error("Failed to decrypt admin TOTP secret: %s", exc.__class__.__name__)
        return None


async def generate_totp_secret(db: AsyncSession, user: User) -> dict:
    """Generate a new TOTP secret for an admin user. Returns the URI for QR code."""
    secret = pyotp.random_base32()

    # Encrypt the secret before storing
    secret_enc = encrypt_token(secret)

    # Upsert: delete existing if any
    await db.execute(delete(TwoFactorAuth).where(TwoFactorAuth.user_id == user.id))

    totp_record = TwoFactorAuth(
        user_id=user.id,
        secret_enc=secret_enc,
        is_enabled=False,  # Not enabled until verified
    )
    db.add(totp_record)
    await db.flush()

    # Generate the provisioning URI for QR code
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(
        name=user.email,
        issuer_name=settings.TOTP_ISSUER_NAME,
    )

    return {
        "secret": secret,  # Show once for manual entry
        "uri": uri,  # For QR code
    }


async def enable_2fa(db: AsyncSession, user: User, code: str) -> bool:
    """Verify a TOTP code and enable 2FA for the user."""
    uid = str(user.id)
    if _check_lockout(uid):
        return False

    result = await db.execute(
        select(TwoFactorAuth).where(TwoFactorAuth.user_id == user.id)
    )
    record = result.scalar_one_or_none()
    if not record:
        return False

    secret = _safe_decrypt_totp_secret(record.secret_enc)
    if not secret:
        await reset_2fa(db, user.id)
        raise ValueError(
            "2FA configuration is invalid (encryption key may have changed). "
            "Please set up 2FA again."
        )

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        _record_failure(uid)
        return False

    record.is_enabled = True
    _clear_failures(uid)
    await db.flush()
    return True


async def verify_totp(db: AsyncSession, user: User, code: str) -> bool:
    """Verify a TOTP code for an admin user."""
    uid = str(user.id)
    if _check_lockout(uid):
        logger.warning(f"Admin 2FA lockout for user {uid}")
        return False

    result = await db.execute(
        select(TwoFactorAuth).where(
            TwoFactorAuth.user_id == user.id,
            TwoFactorAuth.is_enabled == True,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        return False

    secret = _safe_decrypt_totp_secret(record.secret_enc)
    if not secret:
        await reset_2fa(db, user.id)
        raise ValueError(
            "2FA configuration is invalid (encryption key may have changed). "
            "Please set up 2FA again."
        )

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        _record_failure(uid)
        return False

    _clear_failures(uid)
    return True


async def reset_2fa(db: AsyncSession, user_id) -> None:
    """Remove a user's 2FA configuration (e.g. after encryption key rotation)."""
    await db.execute(delete(TwoFactorAuth).where(TwoFactorAuth.user_id == user_id))
    await db.flush()


async def has_2fa_enabled(db: AsyncSession, user_id) -> bool:
    """Check if a user has 2FA enabled."""
    result = await db.execute(
        select(TwoFactorAuth).where(
            TwoFactorAuth.user_id == user_id,
            TwoFactorAuth.is_enabled == True,
        )
    )
    return result.scalar_one_or_none() is not None


async def create_admin_session(
    db: AsyncSession, user: User, ip: str = None, user_agent: str = None
) -> str:
    """Create a short-lived admin session token after successful 2FA."""
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ADMIN_SESSION_EXPIRY_MINUTES
    )

    session = AdminSession(
        user_id=user.id,
        session_token=token,
        totp_verified=True,
        ip_address=ip,
        user_agent=user_agent,
        expires_at=expires,
    )
    db.add(session)
    await db.flush()

    logger.info(f"Admin session created for {user.email}, expires at {expires}")
    return token


async def validate_admin_session(
    db: AsyncSession, token: str
) -> Optional[AdminSession]:
    """Validate an admin session token. Returns the session if valid."""
    if not token:
        return None

    result = await db.execute(
        select(AdminSession).where(
            AdminSession.session_token == token,
            AdminSession.totp_verified == True,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    # Check expiry
    expires_at = _coerce_utc_datetime(session.expires_at)
    if not expires_at:
        # Malformed or unreadable timestamp should not crash requests.
        # Treat as invalid session and remove it.
        try:
            await db.delete(session)
            await db.flush()
        except Exception:
            pass
        logger.warning("Admin session has invalid expires_at; session removed")
        return None

    if datetime.now(timezone.utc) > expires_at:
        # Clean up expired session
        await db.delete(session)
        await db.flush()
        return None

    return session


async def cleanup_expired_sessions(db: AsyncSession):
    """Remove all expired admin sessions."""
    await db.execute(
        delete(AdminSession).where(AdminSession.expires_at < datetime.now(timezone.utc))
    )
    await db.flush()
