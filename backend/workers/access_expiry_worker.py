"""
Access Expiry Worker — Background task that runs every hour.

Checks for:
  1. Users whose access is expiring within 2 days → sends reminder email
  2. Users whose access has expired → deactivates and sends expired email

Email dedup: Checks email_notifications_log to avoid sending duplicates.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import async_session_factory
from models.user import User, EmailNotificationLog
from services.email_service import send_access_expiring_email, send_access_expired_email

logger = logging.getLogger(__name__)

_CHECK_INTERVAL = 3600  # 1 hour


def _coerce_utc_datetime(value):
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


class AccessExpiryWorker:
    def __init__(self):
        self._running = False
        self._task = None

    async def run(self):
        """Main loop — runs every hour."""
        self._running = True
        logger.info("Access expiry worker started")

        # Wait a bit on startup to let the system stabilize
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._check_expiries()
            except Exception as e:
                logger.error(f"Access expiry check failed: {e}", exc_info=True)

            await asyncio.sleep(_CHECK_INTERVAL)

    async def stop(self):
        self._running = False

    def get_stats(self) -> dict:
        return {"running": self._running}

    async def _check_expiries(self):
        """Check for expiring and expired users."""
        now = datetime.now(timezone.utc)
        warning_threshold = now + timedelta(days=2)

        async with async_session_factory() as db:
            # 1. Find users expiring within 2 days (still active)
            expiring_result = await db.execute(
                select(User).where(
                    and_(
                        User.account_status == "active",
                        User.access_expires_at != None,
                        User.access_expires_at <= warning_threshold,
                        User.access_expires_at > now,
                    )
                )
            )
            expiring_users = expiring_result.scalars().all()

            for user in expiring_users:
                # Check if we already sent an expiring email
                already_sent = await self._has_recent_email(
                    db, user.id, "access_expiring", hours=24
                )
                if not already_sent:
                    expires_at = _coerce_utc_datetime(user.access_expires_at)
                    if not expires_at:
                        continue
                    days_left = max(1, (expires_at - now).days)
                    send_access_expiring_email(user, days_left)
                    logger.info(
                        f"Sent expiry warning to {user.email} ({days_left} days left)"
                    )

            # 2. Find users whose access has expired (still marked active)
            expired_result = await db.execute(
                select(User).where(
                    and_(
                        User.account_status == "active",
                        User.access_expires_at != None,
                        User.access_expires_at <= now,
                    )
                )
            )
            expired_users = expired_result.scalars().all()

            for user in expired_users:
                user.account_status = "expired"
                user.is_active = False

                already_sent = await self._has_recent_email(
                    db, user.id, "access_expired", hours=24
                )
                if not already_sent:
                    send_access_expired_email(user)
                    logger.info(f"Expired and notified: {user.email}")

            if expired_users:
                await db.commit()

            if expiring_users or expired_users:
                logger.info(
                    f"Expiry check: {len(expiring_users)} expiring, "
                    f"{len(expired_users)} newly expired"
                )

    async def _has_recent_email(
        self, db: AsyncSession, user_id, email_type: str, hours: int = 24
    ) -> bool:
        """Check if an email of this type was recently sent to the user."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await db.execute(
            select(func.count())
            .select_from(EmailNotificationLog)
            .where(
                and_(
                    EmailNotificationLog.user_id == user_id,
                    EmailNotificationLog.email_type == email_type,
                    EmailNotificationLog.status == "sent",
                    EmailNotificationLog.sent_at > cutoff,
                )
            )
        )
        count = result.scalar() or 0
        return count > 0


access_expiry_worker = AccessExpiryWorker()
