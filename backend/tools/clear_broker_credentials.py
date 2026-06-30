#!/usr/bin/env python3
"""Clear saved broker credentials for all users (keeps user accounts intact).

Usage:
    cd backend
    python -m tools.clear_broker_credentials
"""

import asyncio
import logging

from sqlalchemy import text

from database.connection import async_session_factory, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_CLEAR_SQL = text(
    """
    UPDATE broker_accounts
    SET
        credentials_enc = NULL,
        broker_user_id = NULL,
        display_name = NULL,
        access_token_enc = NULL,
        refresh_token_enc = NULL,
        extra_data_enc = NULL,
        is_active = false,
        token_expiry = NULL,
        last_used_at = NULL
    WHERE credentials_enc IS NOT NULL
       OR access_token_enc IS NOT NULL
       OR broker_user_id IS NOT NULL
    """
)


async def main() -> None:
    await init_db()
    async with async_session_factory() as db:
        result = await db.execute(_CLEAR_SQL)
        await db.commit()
        count = result.rowcount if result.rowcount is not None else 0
        logger.info("Cleared saved broker credentials on %s row(s)", count)


if __name__ == "__main__":
    asyncio.run(main())
