"""
Master Session — DISABLED.

Users must connect their own broker account (Zebu, Alice Blue, or Zerodha).
This service is kept as a no-op stub for backward compatibility with any
existing imports, but it no longer starts a shared data session.
"""

import logging

logger = logging.getLogger(__name__)


class MasterSessionService:
    """No-op stub — master shared session is disabled."""

    def __init__(self):
        self._initialized = False

    async def initialize(self) -> bool:
        logger.info("Master session is disabled — users connect their own broker accounts")
        return False

    async def refresh(self) -> bool:
        return False

    def is_active(self) -> bool:
        return False

    def get_provider(self):
        return None

    def get_status(self) -> dict:
        return {
            "active": False,
            "configured": False,
            "user_id": None,
            "missing": [],
            "last_error": "Master session disabled — each user connects their own broker",
        }


master_session_service = MasterSessionService()
