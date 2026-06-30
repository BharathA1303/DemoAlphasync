"""
Firebase Admin SDK initialization for AlphaSync backend.

Verifies Firebase ID tokens sent by the frontend.

Setup:
    1. Go to Firebase Console → Project Settings → Service Accounts
    2. Click "Generate New Private Key" → download the JSON file
    3. Either:
       a) Set FIREBASE_CREDENTIALS_PATH to point to the JSON file (recommended for localhost), OR
       b) Set FIREBASE_CREDENTIALS_JSON env var to the entire JSON string (for Docker), OR
       c) Set GOOGLE_APPLICATION_CREDENTIALS as system environment variable

The Firebase Admin SDK is used ONLY for token verification —
all user sign-in/sign-up happens on the client via Firebase JS SDK.

LOCALHOST DEVELOPMENT:
    1. Download your Firebase service account JSON from Firebase Console
    2. Save it as: backend/firebase-credentials.json
    3. Ensure .env has: FIREBASE_CREDENTIALS_PATH=firebase-credentials.json
    4. Restart the backend server

If credentials are not found:
    - In DEBUG mode: token verification is skipped (development only)
    - In PRODUCTION: requests without valid tokens will be rejected
"""

import base64
import json
import logging
import os
from typing import Optional

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

from config.settings import settings

logger = logging.getLogger(__name__)

_initialized = False
_credentials_available = False


def init_firebase() -> None:
    """Initialize Firebase Admin SDK (idempotent)."""
    global _initialized, _credentials_available
    if _initialized:
        return

    # Clean up any previous failed initialization attempt
    try:
        firebase_admin.get_app()
        # App exists from a failed init — delete it so we can retry
        firebase_admin.delete_app(firebase_admin.get_app())
    except ValueError:
        pass  # No existing app — good

    try:
        # Try to load credentials from environment variables
        if settings.FIREBASE_CREDENTIALS_JSON:
            try:
                cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                _credentials_available = True
                logger.info("✓ Firebase Admin SDK initialized from FIREBASE_CREDENTIALS_JSON")
            except json.JSONDecodeError as e:
                logger.error(f"✗ FIREBASE_CREDENTIALS_JSON is not valid JSON: {e}")
                raise
                
        elif settings.FIREBASE_CREDENTIALS_PATH:
            path = settings.FIREBASE_CREDENTIALS_PATH
            
            # Resolve relative paths from backend directory
            if not os.path.isabs(path):
                backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                path = os.path.join(backend_dir, path)
            
            if not os.path.isfile(path):
                raise FileNotFoundError(
                    f"✗ Firebase credentials file not found at: {path}\n"
                    f"   Expected path: {path}\n"
                    f"   To fix localhost:\n"
                    f"   1. Download Firebase service account JSON from Firebase Console\n"
                    f"   2. Save as: backend/firebase-credentials.json\n"
                    f"   3. Set FIREBASE_CREDENTIALS_PATH=firebase-credentials.json in .env"
                )
            
            if not os.access(path, os.R_OK):
                raise PermissionError(
                    f"✗ Cannot read Firebase credentials file: {path}\n"
                    f"   Check file permissions (current uid={os.getuid() if hasattr(os, 'getuid') else 'N/A'}, "
                    f"file owner={os.stat(path).st_uid if hasattr(os, 'getuid') else 'N/A'}, "
                    f"mode={oct(os.stat(path).st_mode)})"
                )
            
            cred = credentials.Certificate(path)
            firebase_admin.initialize_app(cred)
            _credentials_available = True
            logger.info(f"✓ Firebase Admin SDK initialized from file: {path}")
            
        else:
            # No explicit credentials provided
            logger.warning(
                "⚠ No Firebase credentials found in FIREBASE_CREDENTIALS_JSON or FIREBASE_CREDENTIALS_PATH\n"
                "   Attempting to use GOOGLE_APPLICATION_CREDENTIALS (system env var)...\n"
                "   For localhost development:\n"
                "   1. Download Firebase service account JSON from Firebase Console\n"
                "   2. Save as: backend/firebase-credentials.json\n"
                "   3. Add to .env: FIREBASE_CREDENTIALS_PATH=firebase-credentials.json"
            )
            try:
                firebase_admin.initialize_app()
                _credentials_available = True
                logger.info("✓ Firebase Admin SDK initialized from GOOGLE_APPLICATION_CREDENTIALS")
            except Exception as e:
                logger.error(
                    f"✗ Firebase initialization failed: {e}\n"
                    f"   No credentials available. Token verification will NOT work.\n"
                    f"   For localhost: Set FIREBASE_CREDENTIALS_PATH in .env to your service account JSON file"
                )
                firebase_admin.initialize_app()  # Initialize without credentials for development
                _credentials_available = False
                
        _initialized = True
        
    except Exception as e:
        logger.error(f"✗ Firebase Admin initialization failed: {e}")
        # Don't re-raise — allow app to continue in development mode
        _initialized = True
        _credentials_available = False


def _decode_jwt_payload(token: str) -> Optional[dict]:
    """
    Decode a Firebase JWT token's payload WITHOUT verifying the signature.
    Extracts real user info (uid, email, name, picture) from the token.
    Only used in DEBUG mode when Firebase Admin credentials are unavailable.
    """
    try:
        # JWT format: header.payload.signature — we only need the payload
        parts = token.split(".")
        if len(parts) != 3:
            logger.warning("Token is not a valid JWT (expected 3 parts)")
            return None

        # Base64url decode the payload (add padding if needed)
        payload_b64 = parts[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        claims = json.loads(payload_bytes)

        # Map standard Firebase JWT claims to the format the app expects
        return {
            "uid": claims.get("user_id") or claims.get("sub", ""),
            "email": claims.get("email", ""),
            "name": claims.get("name", ""),
            "picture": claims.get("picture"),
            "email_verified": claims.get("email_verified", False),
            "firebase": claims.get("firebase", {}),
            "iss": claims.get("iss", ""),
            "sub": claims.get("sub", ""),
        }
    except Exception as e:
        logger.error(f"Failed to decode JWT payload: {e}")
        return None


def verify_firebase_token(id_token: str) -> Optional[dict]:
    """
    Verify a Firebase ID token and return the decoded claims.

    Returns None if the token is invalid or expired.
    Claims include: uid, email, name, picture, email_verified, etc.
    
    In DEBUG mode without credentials: Returns a mock user for development.
    In PRODUCTION without credentials: Returns None (request rejected).
    """
    if not _initialized:
        try:
            init_firebase()
        except Exception as e:
            logger.error(f"Cannot verify token — Firebase init failed: {e}")
            return None

    # If no credentials available
    if not _credentials_available:
        if settings.DEBUG:
            # Development mode without credentials: decode the JWT payload
            # to extract the real user info (no signature verification)
            logger.warning(
                "⚠ Firebase credentials not available. "
                "Decoding token without verification in DEBUG mode."
            )
            return _decode_jwt_payload(id_token)
        else:
            # Production mode: reject without valid credentials
            logger.error(
                "✗ Firebase credentials not available and DEBUG=false. "
                "Token verification cannot proceed in production."
            )
            return None

    # In DEBUG mode, accept demo tokens ONLY when Firebase credentials
    # are NOT configured (pure local development without Firebase).
    if settings.DEBUG and not _credentials_available and id_token == "demo-token-alphasync":
        logger.warning("Accepting demo token — DEBUG mode with no Firebase credentials")
        return {
            "uid": "dev-user-123",
            "email": "demo@alphasync.app",
            "name": "Demo Trader",
            "email_verified": True,
            "iss": "demo-mode",
            "sub": "dev-user-123",
        }

    # Firebase credentials are available — verify the token
    try:
        # Allow small clock skew between client and server to prevent
        # transient "Token used too early" failures on localhost/dev machines.
        # Keep revocation checks enabled.
        try:
            decoded = firebase_auth.verify_id_token(
                id_token,
                check_revoked=True,
                clock_skew_seconds=60,
            )
        except TypeError:
            # Backward compatibility for firebase-admin versions that don't
            # support clock_skew_seconds.
            decoded = firebase_auth.verify_id_token(id_token, check_revoked=True)
        return decoded
    except firebase_auth.RevokedIdTokenError:
        logger.warning("Firebase token has been revoked")
        return None
    except firebase_auth.ExpiredIdTokenError:
        logger.debug("Firebase token expired")
        return None
    except firebase_auth.InvalidIdTokenError as e:
        logger.warning(f"Invalid Firebase token: {e}")
        return None
    except Exception as e:
        logger.error(f"Firebase token verification error: {type(e).__name__}: {e}")
        return None
