import pytest
import jwt
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from config.settings import settings
import config.firebase as fb
from database.connection import get_db
from services.auth_service import verify_id_token
from main import app

# A helper to generate a mock JWT for testing payload decoding
def generate_mock_jwt(payload):
    return jwt.encode(payload, "secret", algorithm="HS256")

@pytest.fixture
def mock_verify_id_token_func():
    with patch("config.firebase.firebase_auth.verify_id_token") as mock:
        yield mock

@pytest.fixture
def override_settings_debug():
    original_debug = settings.DEBUG
    yield
    settings.DEBUG = original_debug

@pytest.fixture
def override_db(db):
    async def _get_db_override():
        yield db
    
    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.pop(get_db, None)

def test_verify_firebase_token_success(mock_verify_id_token_func):
    # Setup mock to return a valid claims dictionary
    mock_claims = {"uid": "user123", "email": "user@example.com"}
    mock_verify_id_token_func.return_value = mock_claims
    
    with patch("config.firebase._credentials_available", True):
        claims = fb.verify_firebase_token("valid-token")
        assert claims == mock_claims
        mock_verify_id_token_func.assert_called_once_with(
            "valid-token",
            check_revoked=False,
            clock_skew_seconds=60,
        )

def test_verify_firebase_token_invalid_raises_none(mock_verify_id_token_func):
    from firebase_admin.auth import InvalidIdTokenError
    mock_verify_id_token_func.side_effect = InvalidIdTokenError("Invalid token")
    
    with patch("config.firebase._credentials_available", True):
        claims = fb.verify_firebase_token("invalid-token")
        assert claims is None

def test_verify_firebase_token_expired_raises_none(mock_verify_id_token_func):
    from firebase_admin.auth import ExpiredIdTokenError
    mock_verify_id_token_func.side_effect = ExpiredIdTokenError("Expired token", None)
    
    with patch("config.firebase._credentials_available", True):
        claims = fb.verify_firebase_token("expired-token")
        assert claims is None

def test_verify_firebase_token_debug_fallback(override_settings_debug):
    # Set settings.DEBUG to True and _credentials_available to False to test JWT decoding fallback
    settings.DEBUG = True
    
    payload = {
        "user_id": "debug123",
        "email": "debug@example.com",
        "name": "Debug User",
        "picture": "http://example.com/pic.jpg",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"}
    }
    jwt_token = generate_mock_jwt(payload)
    
    with patch("config.firebase._credentials_available", False):
        claims = fb.verify_firebase_token(jwt_token)
        assert claims is not None
        assert claims["uid"] == "debug123"
        assert claims["email"] == "debug@example.com"
        assert claims["name"] == "Debug User"
        assert claims["picture"] == "http://example.com/pic.jpg"
        assert claims["email_verified"] is True

def test_verify_firebase_token_production_no_credentials_rejections(override_settings_debug):
    settings.DEBUG = False
    
    with patch("config.firebase._credentials_available", False):
        claims = fb.verify_firebase_token("some-token")
        assert claims is None

@patch("routes.auth.verify_id_token")
def test_sync_user_endpoint_success(mock_verify_id_token, db, override_db):
    client = TestClient(app)
    
    # Configure user claims returned by mock
    mock_verify_id_token.return_value = {
        "uid": "new_firebase_uid_999",
        "email": "new_user@alphasync.app",
        "name": "New User",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"}
    }
    
    # Perform a POST to /api/auth/sync with credentials header
    response = client.post(
        "/api/auth/sync",
        json={"auth_intent": "register"},
        headers={"Authorization": "Bearer fake-token-123"}
    )
    
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["user"]["email"] == "new_user@alphasync.app"
    assert res_data["user"]["role"] == "user"


def test_is_admin_allowlisted():
    from routes.auth import _is_admin_allowlisted
    
    with patch("routes.auth.settings") as mock_settings:
        # 1. Test allowlisted email matches
        mock_settings.ADMIN_EMAIL_ALLOWLIST = ["ashok.j2346@gmail.com"]
        mock_settings.ROOT_ADMIN_EMAIL = "ashok.j2346@gmail.com"
        assert _is_admin_allowlisted("ashok.j2346@gmail.com") is True
        
        # 2. Test fallback to ROOT_ADMIN_EMAIL even if allowlist is empty
        mock_settings.ADMIN_EMAIL_ALLOWLIST = []
        mock_settings.ROOT_ADMIN_EMAIL = "ashok.j2346@gmail.com"
        assert _is_admin_allowlisted("ashok.j2346@gmail.com") is True
        assert _is_admin_allowlisted("other@example.com") is False

        # 3. Test parsing comma-separated string from env
        mock_settings.ADMIN_EMAIL_ALLOWLIST = "one@admin.com, two@admin.com "
        mock_settings.ROOT_ADMIN_EMAIL = ""
        assert _is_admin_allowlisted("one@admin.com") is True
        assert _is_admin_allowlisted("two@admin.com") is True
        assert _is_admin_allowlisted("three@admin.com") is False


