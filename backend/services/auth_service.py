"""
Auth Service — local username/email/password authentication.

Passwords are hashed with bcrypt (passlib). Sessions are self-issued
JWTs (HS256) returned to the frontend as a Bearer token, verified on
every request by decode_access_token().
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from config.settings import settings

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt only considers the first 72 bytes of a password; passlib raises
# instead of silently truncating. Registration already rejects passwords
# over 72 bytes, so this is just a defensive backstop.
_BCRYPT_MAX_BYTES = 72


def _clamp_to_bcrypt_limit(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) <= _BCRYPT_MAX_BYTES:
        return password
    return encoded[:_BCRYPT_MAX_BYTES].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    return _pwd_context.hash(_clamp_to_bcrypt_limit(password))


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return _pwd_context.verify(_clamp_to_bcrypt_limit(password), password_hash)
    except Exception:
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Verify and decode a local JWT. Returns None if invalid/expired."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        logger.debug(f"JWT decode failed: {e}")
        return None
