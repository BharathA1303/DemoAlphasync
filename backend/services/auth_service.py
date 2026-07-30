"""
Auth Service — Firebase-based authentication.

The frontend handles sign-in/sign-up via Firebase JS SDK.
The backend verifies Firebase ID tokens using the Admin SDK.
No passwords are stored in our database.
"""

import logging
from typing import Optional

from config.firebase import verify_firebase_token

logger = logging.getLogger(__name__)


def verify_id_token(token: str) -> Optional[dict]:
    """
    Verify a Firebase ID token.

    Returns decoded claims dict with keys:
        uid, email, name, picture, email_verified, sign_in_provider, etc.
    Returns None if invalid.
    """
    return verify_firebase_token(token)
