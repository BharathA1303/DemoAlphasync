"""
Broker Auth Service — Zebu OAuth / API-key login flow.

Handles the full lifecycle of a per-user broker connection:

    1.  generate_connect_url()   → Build the redirect URL for Zebu login.
    2.  handle_callback()        → Exchange the auth code for an access token.
    3.  get_active_session()     → Return a decrypted, valid session token.
    4.  refresh_session()        → Renew an expired token if possible.
    5.  disconnect()             → Revoke and remove a broker link.

Zebu Auth Flow (NorenOMS / Zebull API):
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ Frontend  │────→│ AlphaSync│────→│  Zebu    │
    │           │     │  Backend │     │  Server  │
    └──────────┘     └──────────┘     └──────────┘
         │                │                 │
         │  1. GET /broker/connect/zebu      │
         │────────────────→│                 │
         │  2. Redirect URL │                │
         │←────────────────│                 │
         │  3. User logs in at Zebu          │
         │──────────────────────────────────→│
         │  4. Redirect back with auth code  │
         │←──────────────────────────────────│
         │  5. GET /broker/callback/zebu?code=...
         │────────────────→│                 │
         │                 │ 6. POST token exchange
         │                 │────────────────→│
         │                 │ 7. access_token  │
         │                 │←────────────────│
         │                 │ 8. Encrypt & store
         │  9. { connected }│                │
         │←────────────────│                 │

IMPORTANT:
    - We ONLY use the token for opening a market-data WebSocket.
    - We NEVER call order-placement or funds-transfer APIs.
    - The token is encrypted at rest (AES-256-GCM).
"""

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from config.settings import settings
from models.broker import BrokerAccount
from services.broker_crypto import (
    encrypt_token,
    decrypt_token,
    encrypt_json,
    decrypt_json,
)

logger = logging.getLogger(__name__)

# ── Zebu API endpoints ──────────────────────────────────────────────
ZEBU_API_BASE = settings.ZEBU_API_URL
# NOTE: ZEBU_AUTH_URL is now in settings (configurable via .env)


def _is_expired(token_expiry: Optional[datetime]) -> bool:
    """
    True if token_expiry is in the past. SQLite drops tzinfo on round-trip
    even for DateTime(timezone=True) columns, so naive values are assumed
    UTC rather than compared directly against an aware "now".
    """
    if token_expiry is None:
        return False
    if token_expiry.tzinfo is None:
        token_expiry = token_expiry.replace(tzinfo=timezone.utc)
    return token_expiry < datetime.now(timezone.utc)


class BrokerAuthService:
    """
    Manages broker authentication flows.

    Broker-agnostic interface; the `broker` parameter selects the
    concrete implementation (currently only "zebu").
    """

    # ── OAuth state tokens (Redis + in-memory fallback) ─────────────
    _pending_states: dict[str, dict] = {}
    _OAUTH_STATE_TTL = 600  # 10 minutes

    def _zebu_oauth_client_id(self) -> str:
        """Resolve MYNT OAuth client_id from server env (dev fallback only)."""
        if settings.ZEBU_OAUTH_CLIENT_ID:
            return settings.ZEBU_OAUTH_CLIENT_ID
        vendor = (settings.ZEBU_VENDOR_CODE or "").strip()
        if not vendor:
            return ""
        return vendor if vendor.endswith("_U") else f"{vendor}_U"

    async def _resolve_zebu_oauth_creds(
        self, db: AsyncSession, user_id: str
    ) -> tuple[str, str]:
        """Per-user MYNT OAuth Client ID + Secret from encrypted credentials."""
        creds = await self._load_app_credentials(db, user_id, "zebu")
        client_id = ((creds or {}).get("api_key") or "").strip()
        client_secret = ((creds or {}).get("api_secret") or "").strip()
        return client_id, client_secret

    @staticmethod
    def _jwt_payload_sub(token: str) -> str:
        """Best-effort uid extraction from a JWT access_token."""
        try:
            import base64

            parts = token.split(".")
            if len(parts) < 2:
                return ""
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            return (
                payload.get("uid")
                or payload.get("sub")
                or payload.get("user_id")
                or ""
            )
        except Exception:
            return ""

    async def _store_oauth_state(self, state: str, data: dict) -> None:
        payload = {
            "user_id": str(data["user_id"]),
            "broker": data["broker"],
            "created": data["created"].isoformat(),
        }
        self._pending_states[state] = data
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.REDIS_URL)
            await client.setex(
                f"alphasync:oauth:{state}",
                self._OAUTH_STATE_TTL,
                json.dumps(payload),
            )
            await client.aclose()
        except Exception as e:
            logger.warning(f"Redis OAuth state store failed (using in-memory): {e}")

    async def _pop_oauth_state(self, state: str) -> Optional[dict]:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.REDIS_URL)
            raw = await client.get(f"alphasync:oauth:{state}")
            if raw:
                await client.delete(f"alphasync:oauth:{state}")
                await client.aclose()
                data = json.loads(raw)
                created = datetime.fromisoformat(data["created"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                self._pending_states.pop(state, None)
                return {
                    "user_id": data["user_id"],
                    "broker": data["broker"],
                    "created": created,
                }
            await client.aclose()
        except Exception as e:
            logger.warning(f"Redis OAuth state read failed: {e}")
        return self._pending_states.pop(state, None)

    # ────────────────────────────────────────────────────────────────
    # 1. Generate Connect URL
    # ────────────────────────────────────────────────────────────────

    async def generate_connect_url(
        self, db: AsyncSession, user_id: str, broker: str = "zebu"
    ) -> dict:
        """
        Build the redirect URL for the broker login page.

        Returns: { "redirect_url": str, "state": str }
        """
        state = secrets.token_urlsafe(32)
        pending = {
            "user_id": user_id,
            "broker": broker,
            "created": datetime.now(timezone.utc),
        }
        await self._store_oauth_state(state, pending)

        if broker == "zebu":
            client_id, client_secret = await self._resolve_zebu_oauth_creds(db, user_id)
            if not client_id or not client_secret:
                raise ValueError(
                    "MYNT OAuth credentials not configured. "
                    "Enter your OAuth Client ID and Secret Key from the MYNT portal first."
                )
            # Redirect URL is registered in MYNT portal — only client_id in authorize URL.
            redirect_url = (
                f"{settings.ZEBU_AUTH_URL}"
                f"?client_id={quote(client_id, safe='')}"
            )
        elif broker == "aliceblue":
            creds = await self._load_app_credentials(db, user_id, "aliceblue")
            app_code = (creds or {}).get("api_key") or ""
            if not app_code:
                raise ValueError(
                    "Alice Blue API credentials not configured. "
                    "Please enter your App Code and API Secret first."
                )
            redirect_url = (
                f"{settings.ALICE_BLUE_APPCODE_AUTH_URL}"
                f"?appcode={quote(app_code, safe='')}"
            )
        elif broker == "zerodha":
            # Per-user app credentials required — Kite Connect apps are
            # registered (and billed) per developer, so each user supplies
            # their own api_key/api_secret.
            creds = await self._load_app_credentials(db, user_id, "zerodha")
            api_key = (creds or {}).get("api_key") or ""
            if not api_key:
                raise ValueError(
                    "Zerodha API credentials not configured. "
                    "Please enter your API Key and Secret first."
                )
            redirect_url = (
                f"{settings.ZERODHA_AUTH_URL}"
                f"?api_key={api_key}"
                f"&v=3"
                # Zerodha doesn't support state param — we encode it in redirect_uri
            )
            # Store state in pending so we can validate the broker on callback
        else:
            raise ValueError(f"Unsupported broker: {broker}")

        return {"redirect_url": redirect_url, "state": state}

    # ────────────────────────────────────────────────────────────────
    # 2. Handle Callback (exchange code for token)
    # ────────────────────────────────────────────────────────────────

    async def handle_callback(
        self,
        db: AsyncSession,
        broker: str,
        auth_code: str,
        state: str,
        susertoken: str = "",
        uid: str = "",
        actid: str = "",
        request_token: str = "",
        fallback_user_id: str = "",
        broker_user_id: str = "",
    ) -> dict:
        """
        Exchange the auth code for an access token and store it encrypted.

        Dispatches to broker-specific token exchange.

        Returns: { "success": True, "broker_user_id": str }
        Raises: ValueError on invalid state or failed exchange.
        """
        pending = await self._pop_oauth_state(state) if state else None
        if pending:
            if (datetime.now(timezone.utc) - pending["created"]).total_seconds() > self._OAUTH_STATE_TTL:
                raise ValueError("OAuth state token expired (>10 min)")
            user_id = pending["user_id"]
            expected_broker = pending.get("broker", "zebu")
            if expected_broker != broker:
                raise ValueError(
                    f"State token broker mismatch: expected {expected_broker}, got {broker}"
                )
        elif fallback_user_id and broker in ("zebu", "aliceblue"):
            user_id = fallback_user_id
            logger.info(
                f"OAuth callback using authenticated user (state not echoed) broker={broker}"
            )
        else:
            raise ValueError("Invalid or expired OAuth state token")

        if broker == "zebu":
            return await self._zebu_callback(
                db, user_id, broker, auth_code, susertoken, uid, actid
            )
        elif broker == "aliceblue":
            return await self._aliceblue_callback(
                db, user_id, auth_code, broker_user_id or uid
            )
        elif broker == "zerodha":
            return await self._zerodha_callback(
                db, user_id, request_token or auth_code
            )
        else:
            raise ValueError(f"Unsupported broker: {broker}")

    async def _zebu_callback(
        self,
        db: AsyncSession,
        user_id: str,
        broker: str,
        auth_code: str,
        susertoken: str,
        uid: str,
        actid: str,
    ) -> dict:
        if susertoken:
            token_data = {
                "susertoken": susertoken,
                "uid": uid or "",
                "actid": actid or uid or "",
                "stat": "Ok",
            }
        else:
            token_data = await self._zebu_oauth_token_exchange(db, user_id, auth_code)
            session_token = token_data.get("susertoken") or token_data.get("access_token")
            if not session_token:
                token_data = await self._zebu_token_exchange(auth_code, uid=uid, db=db, user_id=user_id)
                session_token = token_data.get("susertoken") or token_data.get("access_token")
            if not session_token:
                raise ValueError(
                    f"Zebu token exchange failed: {token_data.get('emsg', 'unknown error')}"
                )
            token_data["susertoken"] = session_token

        session_token = token_data["susertoken"]
        broker_user_id = (
            token_data.get("actid")
            or token_data.get("uid")
            or self._jwt_payload_sub(session_token)
            or ""
        )
        extra = {
            "uid": token_data.get("uid") or broker_user_id,
            "actid": token_data.get("actid") or broker_user_id,
            "brkname": token_data.get("brkname", "ZEBU"),
            "email": token_data.get("email", ""),
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token", ""),
        }
        await self._upsert_broker_account(
            db, user_id, broker, broker_user_id, encrypt_token(session_token), extra
        )
        logger.info(f"Zebu connected: user={str(user_id)[:8]} broker_user={broker_user_id}")
        return {"success": True, "broker": broker, "broker_user_id": broker_user_id}

    async def _aliceblue_callback(
        self, db: AsyncSession, user_id: str, auth_code: str, alice_user_id: str = ""
    ) -> dict:
        """Exchange Alice Blue authCode for userSession (ANT appcode flow)."""
        creds = await self._load_app_credentials(db, user_id, "aliceblue")
        app_code = (creds or {}).get("api_key") or ""
        api_secret = (creds or {}).get("api_secret") or ""
        if not app_code or not api_secret:
            raise ValueError(
                "Alice Blue API credentials not configured. "
                "Please enter your App Code and API Secret first."
            )

        if alice_user_id:
            return await self._aliceblue_appcode_session(
                db, user_id, alice_user_id, auth_code, api_secret
            )

        return await self._aliceblue_oauth2_session(
            db, user_id, auth_code, app_code, api_secret
        )

    async def _aliceblue_checksum_exchange(
        self, alice_user_id: str, auth_code: str, api_secret: str
    ) -> tuple[str, str]:
        """
        Pure ANT checksum exchange: SHA256(userId + authCode + apiSecret) →
        POST {"checkSum": ...} → getUserDetails → userSession token.

        Used both for the real OAuth callback (authCode = Alice Blue's own
        code) and for headless auto_authenticate (authCode = TOTP or a
        password hash, per Alice Blue's documented non-OAuth SDK path).

        Returns (session_token, client_id). Raises ValueError on failure.
        """
        import hashlib

        checksum = hashlib.sha256(
            f"{alice_user_id}{auth_code}{api_secret}".encode()
        ).hexdigest()
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                settings.ALICE_BLUE_SESSION_URL,
                json={"checkSum": checksum},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                raise ValueError(
                    f"Alice Blue session failed: HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()

        if data.get("stat") != "Ok" or not data.get("userSession"):
            raise ValueError(data.get("emsg", "Alice Blue session exchange failed"))

        return data["userSession"], (data.get("clientId") or alice_user_id)

    async def _aliceblue_appcode_session(
        self,
        db: AsyncSession,
        user_id: str,
        alice_user_id: str,
        auth_code: str,
        api_secret: str,
    ) -> dict:
        """ANT documented flow: SHA256(userId + authCode + apiSecret) → userSession."""
        try:
            session_token, broker_user_id = await self._aliceblue_checksum_exchange(
                alice_user_id, auth_code, api_secret
            )
            extra = {
                "uid": alice_user_id,
                "client_id": broker_user_id,
                "brkname": "ALICEBLUE",
            }
            await self._upsert_broker_account(
                db,
                user_id,
                "aliceblue",
                broker_user_id,
                encrypt_token(session_token),
                extra,
                expiry_hours=8,
            )
            logger.info(
                f"Alice Blue connected (appcode): user={str(user_id)[:8]} "
                f"broker_user={broker_user_id}"
            )
            return {
                "success": True,
                "broker": "aliceblue",
                "broker_user_id": broker_user_id,
            }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Alice Blue appcode session error: {e}", exc_info=True)
            raise ValueError(f"Alice Blue authentication failed: {e}")

    async def _aliceblue_auto_authenticate(
        self, client_id: str, api_key: str, api_secret: str, password: str, totp_secret: str
    ) -> str:
        """
        Headless Alice Blue login: password + TOTP secret → session token,
        no browser/OAuth redirect required. Tries multiple checksum
        strategies used by different Alice Blue API versions/integrations.
        """
        import hashlib
        import pyotp

        uid = (client_id or "").strip()
        pwd = (password or "").strip()
        totp_sec = (totp_secret or "").strip()
        if not uid or not api_key or not api_secret or not pwd or not totp_sec:
            raise ValueError(
                "auto_authenticate: client_id, api_key, api_secret, password, "
                "and totp_secret are all required"
            )

        totp_now = pyotp.TOTP(totp_sec).now()
        sha_pwd = hashlib.sha256(pwd.encode()).hexdigest()
        sha_totp = hashlib.sha256(totp_now.encode()).hexdigest()

        # ── Strategy 1: TOTP as the "authCode" in the documented checksum flow ──
        try:
            token, _ = await self._aliceblue_checksum_exchange(uid, totp_now, api_secret)
            if token:
                return token
        except Exception:
            pass

        # ── Strategy 2: SHA256(password) as the "authCode" ──────────────────
        try:
            token, _ = await self._aliceblue_checksum_exchange(uid, sha_pwd, api_secret)
            if token:
                return token
        except Exception:
            pass

        # ── Strategy 3: direct ANT webLoginValidateOTP (legacy but reliable) ─
        enc = hashlib.sha256((sha_pwd + sha_totp).encode()).hexdigest()
        ant_url = (
            "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/"
            "customer/webLoginValidateOTP"
        )
        body = {
            "userId": uid,
            "enc": enc,
            "factor2": totp_now,
            "captchaAnswer": "",
            "imei": f"alphasync-{uid}",
            "source": "API",
        }
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(
                    ant_url,
                    json=body,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                data = resp.json()
                token = str(
                    (data or {}).get("jKey")
                    or (data or {}).get("userSession")
                    or (data or {}).get("susertoken")
                    or (data or {}).get("sUserToken")
                    or (data or {}).get("access_token")
                    or ""
                ).strip()
                if token and not token.startswith("<"):
                    return token
        except Exception:
            pass

        raise ValueError(
            "Alice Blue auto-authenticate failed — check the saved password and TOTP "
            "secret. The TOTP secret must be the base-32 key from Alice Blue's "
            "authenticator setup, not a 6-digit code."
        )

    async def _aliceblue_oauth2_session(
        self,
        db: AsyncSession,
        user_id: str,
        auth_code: str,
        client_id: str,
        client_secret: str,
    ) -> dict:
        """Legacy OAuth2 code exchange — fallback if userId not in redirect."""
        try:
            payload = {
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": settings.ALICE_BLUE_REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    settings.ALICE_BLUE_TOKEN_URL,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code != 200:
                    body = resp.text[:300]
                    raise ValueError(
                        f"Alice Blue token exchange failed: HTTP {resp.status_code}: {body}"
                    )
                data = resp.json()
                access_token = data.get("access_token")
                if not access_token:
                    raise ValueError(f"Alice Blue: no access_token in response: {data}")

            session_token, alice_user_id = await self._aliceblue_get_session(
                access_token, data.get("user_id", "")
            )
            broker_user_id = alice_user_id or data.get("user_id", "")
            extra = {
                "uid": broker_user_id,
                "access_token": access_token,
                "brkname": "ALICEBLUE",
            }
            await self._upsert_broker_account(
                db, user_id, "aliceblue", broker_user_id,
                encrypt_token(session_token or access_token), extra,
                expiry_hours=8
            )
            logger.info(f"Alice Blue connected: user={str(user_id)[:8]} broker_user={broker_user_id}")
            return {"success": True, "broker": "aliceblue", "broker_user_id": broker_user_id}
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Alice Blue OAuth2 callback error: {e}", exc_info=True)
            raise ValueError(f"Alice Blue authentication failed: {e}")

    async def _aliceblue_get_session(
        self, access_token: str, user_id: str
    ) -> tuple[Optional[str], str]:
        """Get Alice Blue WebSocket session ID from access_token."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{settings.ALICE_BLUE_API_URL}/customer/getUserSID",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Session-Type": "API",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    session_id = data.get("sessionID") or data.get("susertoken")
                    uid = data.get("userID", user_id)
                    return session_id, uid
        except Exception as e:
            logger.warning(f"Alice Blue getUserSID failed: {e}")
        # Fall back to using access_token directly
        return access_token, user_id

    async def _zerodha_callback(
        self, db: AsyncSession, user_id: str, request_token: str
    ) -> dict:
        """Exchange Zerodha request_token for access_token using HMAC checksum."""
        import hashlib

        creds = await self._load_app_credentials(db, user_id, "zerodha")
        api_key = (creds or {}).get("api_key") or ""
        api_secret = (creds or {}).get("api_secret") or ""
        if not api_key or not api_secret:
            raise ValueError(
                "Zerodha API credentials not configured. "
                "Please enter your API Key and Secret first."
            )

        checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{settings.ZERODHA_API_URL}/session/token",
                    data={
                        "api_key": api_key,
                        "request_token": request_token,
                        "checksum": checksum,
                    },
                    headers={
                        "X-Kite-Version": "3",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                if resp.status_code != 200:
                    body = resp.text[:300]
                    raise ValueError(f"Zerodha token exchange failed: HTTP {resp.status_code}: {body}")
                data = resp.json()
                result_data = data.get("data", data)
                access_token = result_data.get("access_token")
                if not access_token:
                    raise ValueError(f"Zerodha: no access_token in response: {data}")

            broker_user_id = result_data.get("user_id", "")
            extra = {
                "uid": broker_user_id,
                "api_key": api_key,
                "user_name": result_data.get("user_name", ""),
                "email": result_data.get("email", ""),
                "brkname": "ZERODHA",
            }
            await self._upsert_broker_account(
                db, user_id, "zerodha", broker_user_id,
                encrypt_token(access_token), extra,
                expiry_hours=24
            )
            logger.info(f"Zerodha connected: user={str(user_id)[:8]} broker_user={broker_user_id}")
            return {"success": True, "broker": "zerodha", "broker_user_id": broker_user_id}
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Zerodha callback error: {e}", exc_info=True)
            raise ValueError(f"Zerodha authentication failed: {e}")

    async def _upsert_broker_account(
        self,
        db: AsyncSession,
        user_id: str,
        broker: str,
        broker_user_id: str,
        access_token_enc: str,
        extra: dict,
        expiry_hours: int = 8,
    ) -> None:
        """Upsert a BrokerAccount record with encrypted token."""
        result = await db.execute(
            select(BrokerAccount).where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker == broker,
                )
            )
        )
        account = result.scalar_one_or_none()

        if account:
            account.access_token_enc = access_token_enc
            account.broker_user_id = broker_user_id
            account.extra_data_enc = encrypt_json(extra)
            account.is_active = True
            account.token_expiry = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
            account.last_used_at = datetime.now(timezone.utc)
        else:
            account = BrokerAccount(
                user_id=user_id,
                broker=broker,
                broker_user_id=broker_user_id,
                access_token_enc=access_token_enc,
                extra_data_enc=encrypt_json(extra),
                is_active=True,
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
                connected_at=datetime.now(timezone.utc),
                last_used_at=datetime.now(timezone.utc),
            )
            db.add(account)
        # Deactivate any other broker accounts for this user
        await db.execute(
            update(BrokerAccount)
            .where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker != broker,
                )
            )
            .values(is_active=False)
        )
        await db.flush()

    # ────────────────────────────────────────────────────────────────
    # 2b. Per-user broker app credentials (API key/secret, vendor code)
    #
    # Independent of the session token: saved once, editable any time,
    # reused for every connect/refresh so the user is never asked to
    # re-type their app credentials.
    # ────────────────────────────────────────────────────────────────

    async def _load_app_credentials(
        self, db: AsyncSession, user_id: str, broker: str
    ) -> Optional[dict]:
        """Decrypt and return a user's saved app credentials for a broker, or None."""
        result = await db.execute(
            select(BrokerAccount).where(
                and_(BrokerAccount.user_id == user_id, BrokerAccount.broker == broker)
            )
        )
        account = result.scalar_one_or_none()
        if not account or not account.credentials_enc:
            return None
        try:
            return decrypt_json(account.credentials_enc)
        except Exception as e:
            logger.error(
                f"Failed to decrypt saved credentials for user={str(user_id)[:8]} "
                f"broker={broker}: {e}"
            )
            return None

    # Fields that are not secret and live on plaintext columns instead of
    # inside the encrypted credentials_enc blob.
    _PLAINTEXT_CREDENTIAL_FIELDS = {"client_id": "broker_user_id", "display_name": "display_name"}

    async def save_credentials(
        self, db: AsyncSession, user_id: str, broker: str, fields: dict
    ) -> dict:
        """
        Save (or update) a user's own broker app credentials.

        `fields` is broker-specific:
          - Zebu: api_key, api_secret, client_id, factor2 (DOB/PAN, optional),
            trading_password (optional — enables zero-click daily refresh).
          - Alice Blue: api_key, api_secret, client_id, totp_secret (optional),
            trading_password (optional), algo_id (optional, unused).
        `client_id` and `display_name` are not secret and are written to
        plaintext columns; everything else goes into the encrypted
        credentials_enc blob. Saving credentials does NOT by itself activate
        a session — the connect/refresh flow that follows does that.
        """
        cleaned = {k: str(v).strip() for k, v in fields.items() if v and str(v).strip()}
        if not cleaned:
            raise ValueError("No credential fields provided")

        if broker in ("zebu", "aliceblue", "zerodha"):
            if not cleaned.get("api_key"):
                raise ValueError("App Key is required")
            if broker in ("aliceblue", "zerodha") and not cleaned.get("api_secret"):
                raise ValueError("App Key and Secret Key are both required")
            if broker == "zebu" and not cleaned.get("trading_password"):
                raise ValueError("Trading Password is required for Zebu API login")
            if broker == "zebu" and not cleaned.get("factor2"):
                raise ValueError("Date of Birth / PAN is required for Zebu API login")

        plaintext_updates = {
            col: cleaned.pop(key)
            for key, col in self._PLAINTEXT_CREDENTIAL_FIELDS.items()
            if key in cleaned
        }

        result = await db.execute(
            select(BrokerAccount).where(
                and_(BrokerAccount.user_id == user_id, BrokerAccount.broker == broker)
            )
        )
        account = result.scalar_one_or_none()

        if account:
            # Check if broker user ID is changing. If so, clear the old session entirely
            # and discard the old credentials (do not do existing.update).
            new_client_id = plaintext_updates.get("broker_user_id")
            user_id_changed = new_client_id and account.broker_user_id != new_client_id

            if user_id_changed:
                logger.info(
                    f"Broker user ID changed from {account.broker_user_id} to {new_client_id}. "
                    "Clearing active session tokens and old credentials."
                )
                account.access_token_enc = None
                account.refresh_token_enc = None
                account.token_expiry = None
                account.extra_data_enc = None
                account.is_active = False
                # Do NOT merge — start fresh so old api_key/vendor_code from
                # the previous account never bleeds into the new one.
                existing = {}
            else:
                existing = {}
                if account.credentials_enc:
                    try:
                        existing = decrypt_json(account.credentials_enc)
                    except Exception:
                        existing = {}
                # Deactivate the session when credentials are saved/updated to force reconnection
                account.is_active = False

            # Merge: new values overwrite old, but old values that were NOT
            # supplied this time are kept (e.g. totp_secret kept when only
            # trading_password is being updated).
            existing.update(cleaned)
            account.credentials_enc = encrypt_json(existing)
            for col, value in plaintext_updates.items():
                setattr(account, col, value)
        else:
            account = BrokerAccount(
                user_id=user_id,
                broker=broker,
                is_active=False,
                credentials_enc=encrypt_json(cleaned),
                **plaintext_updates,
            )
            db.add(account)
        await db.flush()

        logger.info(f"Saved {broker} app credentials for user={str(user_id)[:8]}")
        return {"success": True, "broker": broker}

    async def get_credentials_status(
        self, db: AsyncSession, user_id: str, broker: str
    ) -> dict:
        """Return whether app credentials are saved, with a masked preview."""
        creds = await self._load_app_credentials(db, user_id, broker)
        if not creds:
            return {
                "configured": False,
                "broker": broker,
                "api_key_preview": None,
                "can_quickauth": False,
            }

        api_key = creds.get("api_key", "")
        preview = f"****{api_key[-4:]}" if len(api_key) >= 4 else ("****" if api_key else None)
        can_quickauth = False
        if broker == "zebu":
            can_quickauth = bool(creds.get("trading_password") and creds.get("factor2"))
        elif broker == "aliceblue":
            can_quickauth = bool(creds.get("trading_password") and creds.get("totp_secret"))
        return {
            "configured": True,
            "broker": broker,
            "api_key_preview": preview,
            "can_quickauth": can_quickauth,
        }

    # ────────────────────────────────────────────────────────────────
    # 3. Get Active Session Token
    # ────────────────────────────────────────────────────────────────

    async def get_active_session(
        self, db: AsyncSession, user_id: str, broker: str = "zebu"
    ) -> Optional[dict]:
        """
        Retrieve an active, decrypted session for opening WebSocket.

        Returns:
            {
                "user_id": str,           # Zebu user ID
                "session_token": str,     # Decrypted susertoken
                "broker_user_id": str,
                "extra": dict,
            }
            or None if no active connection.
        """
        result = await db.execute(
            select(BrokerAccount).where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker == broker,
                    BrokerAccount.is_active == True,  # noqa: E712
                )
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            return None

        # Check token expiry
        if _is_expired(account.token_expiry):
            logger.warning(
                f"Broker token expired for user={str(user_id)[:8]} broker={broker}"
            )
            # Try refresh if we have a refresh token
            refreshed = await self._try_refresh(db, account)
            if not refreshed:
                account.is_active = False
                await db.flush()
                return None

        try:
            session_token = decrypt_token(account.access_token_enc)
            extra = (
                decrypt_json(account.extra_data_enc) if account.extra_data_enc else {}
            )
        except Exception as e:
            logger.error(f"Token decryption failed for user={str(user_id)[:8]}: {e}")
            account.is_active = False
            await db.flush()
            return None

        # Update last used
        account.last_used_at = datetime.now(timezone.utc)
        await db.flush()

        return {
            "user_id": extra.get("uid", account.broker_user_id),
            "session_token": session_token,
            "broker_user_id": account.broker_user_id,
            "extra": extra,
        }

    # ────────────────────────────────────────────────────────────────
    # 4. Get Any Active Session (for system-level WebSocket)
    # ────────────────────────────────────────────────────────────────

    async def get_any_active_session(
        self, db: AsyncSession, broker: str = "zebu"
    ) -> Optional[dict]:
        """
        Retrieve ANY active broker session — used for the global
        market-data WebSocket connection.

        The system only needs ONE valid session to stream prices.
        All users share the same price feed.

        Returns same shape as get_active_session() or None.
        """
        result = await db.execute(
            select(BrokerAccount)
            .where(
                and_(
                    BrokerAccount.broker == broker,
                    BrokerAccount.is_active == True,  # noqa: E712
                )
            )
            .order_by(BrokerAccount.last_used_at.desc())
            .limit(1)
        )
        account = result.scalar_one_or_none()
        if not account:
            return None

        return await self.get_active_session(db, account.user_id, broker)

    # ────────────────────────────────────────────────────────────────
    # 5. Disconnect / clear saved credentials
    # ────────────────────────────────────────────────────────────────

    async def clear_saved_credentials(
        self, db: AsyncSession, user_id: str, broker: str
    ) -> bool:
        """
        Remove saved broker app credentials and active session tokens.

        Keeps the broker_accounts row and all user data — only wipes the
        encrypted credential blob, session tokens, and related metadata so
        the user is prompted to enter fresh credentials on next connect.
        """
        result = await db.execute(
            select(BrokerAccount).where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker == broker,
                )
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            return False

        account.credentials_enc = None
        account.broker_user_id = None
        account.display_name = None
        account.access_token_enc = None
        account.refresh_token_enc = None
        account.extra_data_enc = None
        account.is_active = False
        account.token_expiry = None
        account.last_used_at = None
        await db.flush()

        logger.info(
            f"Cleared saved broker credentials: user={str(user_id)[:8]} broker={broker}"
        )
        return True

    async def disconnect(
        self, db: AsyncSession, user_id: str, broker: str = "zebu"
    ) -> bool:
        """
        Disconnect a broker account: wipe tokens and deactivate.

        Returns True if an account was found and disconnected.
        """
        result = await db.execute(
            select(BrokerAccount).where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker == broker,
                )
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            return False

        account.access_token_enc = None
        account.refresh_token_enc = None
        account.extra_data_enc = None
        account.is_active = False
        await db.flush()

        logger.info(f"Broker disconnected: user={str(user_id)[:8]} broker={broker}")
        return True

    # ────────────────────────────────────────────────────────────────
    # 6. Get Connection Status
    # ────────────────────────────────────────────────────────────────

    async def get_status(
        self, db: AsyncSession, user_id: str, broker: str = "zebu"
    ) -> dict:
        """Return the connection status for a user's broker account."""
        result = await db.execute(
            select(BrokerAccount).where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker == broker,
                )
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            return {"connected": False, "broker": broker}

        is_expired = _is_expired(account.token_expiry)

        return {
            "connected": account.is_active and not is_expired,
            "broker": broker,
            "broker_user_id": account.broker_user_id,
            "connected_at": (
                account.connected_at.isoformat() if account.connected_at else None
            ),
            "token_expiry": (
                account.token_expiry.isoformat() if account.token_expiry else None
            ),
            "is_expired": is_expired,
            "last_used_at": (
                account.last_used_at.isoformat() if account.last_used_at else None
            ),
        }

    # ════════════════════════════════════════════════════════════════
    # PRIVATE — Zebu-specific methods
    # ════════════════════════════════════════════════════════════════

    def _resolve_zebu_vendor_code(
        self, uid: str, custom_vc: Optional[str] = None, api_key: Optional[str] = None
    ) -> str:
        """
        Resolve the vendor code for a Zebu account.
        1. If a custom vendor code is explicitly provided (and doesn't look like an OAuth secret), use that.
        2. If the user's api_key matches the server-level credentials, or the UID matches the master user,
           fall back to settings.ZEBU_VENDOR_CODE.
        3. Otherwise, fall back to the user's own UID (Zebu default for individual accounts).
        """
        uid = (uid or "").strip()
        
        # If custom_vc is set and doesn't look like an OAuth secret (typically > 20 chars)
        if custom_vc and custom_vc.strip():
            vc_clean = custom_vc.strip()
            if len(vc_clean) <= 20:
                return vc_clean
                
        is_master = False
        if settings.ZEBU_MASTER_USER_ID and uid == settings.ZEBU_MASTER_USER_ID.strip():
            is_master = True
        if api_key and settings.ZEBU_API_SECRET and api_key.strip() == settings.ZEBU_API_SECRET.strip():
            is_master = True
        if api_key and settings.ZEBU_API_KEY and api_key.strip() == settings.ZEBU_API_KEY.strip():
            is_master = True
            
        if is_master and settings.ZEBU_VENDOR_CODE:
            return settings.ZEBU_VENDOR_CODE.strip()
            
        return uid

    async def _zebu_oauth_token_exchange(
        self, db: AsyncSession, user_id: str, auth_code: str
    ) -> dict:
        """
        Exchange MYNT OAuth authorization code via GenAcsTok.

        Checksum: SHA-256(client_id + secret_key + code)
        Uses per-user credentials from MYNT portal.
        """
        import hashlib

        client_id, client_secret = await self._resolve_zebu_oauth_creds(db, user_id)
        if not client_id or not client_secret:
            client_id = self._zebu_oauth_client_id()
            client_secret = settings.ZEBU_API_SECRET or settings.ZEBU_API_KEY or ""
        if not client_id or not client_secret or not auth_code:
            return {"emsg": "Missing MYNT OAuth client_id, secret, or auth code"}

        checksum = hashlib.sha256(
            f"{client_id}{client_secret}{auth_code}".encode()
        ).hexdigest()
        payload = json.dumps({"code": auth_code, "checksum": checksum})
        jdata = f"jData={payload}"
        headers = {"Content-Type": "text/plain"}
        url = "https://go.mynt.in/NorenWClientAPI/GenAcsTok"

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                logger.info(f"Zebu OAuth GenAcsTok → {url}")
                resp = await client.post(url, data=jdata, headers=headers)
                if resp.status_code != 200:
                    return {"emsg": f"HTTP {resp.status_code}: {resp.text[:200]}"}
                if not resp.text or not resp.text.strip():
                    return {"emsg": "Empty response from GenAcsTok"}
                data = resp.json()
                if data.get("stat") == "Ok" or data.get("susertoken") or data.get("access_token"):
                    logger.info("Zebu OAuth token exchange successful")
                    return data
                return {"emsg": data.get("emsg", str(data))}
        except Exception as e:
            logger.warning(f"Zebu OAuth GenAcsTok error: {e}")
            return {"emsg": str(e)}

    async def _zebu_token_exchange(
        self, auth_code: str, uid: str = "", db: Optional[AsyncSession] = None, user_id: str = ""
    ) -> dict:
        """
        Exchange a Zebu auth code for an access token.

        Calls Zebu's NorenAPI QuickAuth endpoint.
        The `uid` is the Zebu user ID (per-user, NOT a global setting).
        If uid is empty, uses auth_code as both uid and pwd (some flows).
        """
        try:
            import hashlib

            # uid comes from the redirect params or the auth_code itself
            zebu_uid = uid or auth_code

            # Load credentials if db and user_id are provided
            custom_vc = None
            api_key = None
            if db and user_id:
                creds = await self._load_app_credentials(db, user_id, "zebu")
                if creds:
                    custom_vc = creds.get("vendor_code") or creds.get("api_secret") or ""
                    api_key = creds.get("api_key")

            # Build appkey: SHA-256 of "uid|api_secret"
            # Use api_key from credentials if available; otherwise fall back to global ZEBU_API_SECRET
            _api_secret = api_key or settings.ZEBU_API_SECRET or settings.ZEBU_API_KEY
            appkey_raw = f"{zebu_uid}|{_api_secret}"
            appkey = hashlib.sha256(appkey_raw.encode()).hexdigest()

            # Resolve vendor code
            vc = self._resolve_zebu_vendor_code(
                uid=zebu_uid,
                custom_vc=custom_vc,
                api_key=_api_secret
            )

            payload = {
                "apkversion": "1.0.0",
                "uid": zebu_uid,
                "pwd": auth_code,  # In OAuth flow this is the received code
                "factor2": "",
                "vc": vc,
                "appkey": appkey,
                "imei": "alphasync",
                "source": "API",
            }

            # Zebu expects jData= form-encoded, NOT JSON body
            jdata = "jData=" + json.dumps(payload)
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            _FALLBACK_HOSTS = [
                "https://go.mynt.in/NorenWClientTP",
                settings.ZEBU_API_URL,
            ]
            seen: set[str] = set()
            hosts = []
            for h in _FALLBACK_HOSTS:
                h = (h or "").rstrip("/")
                if not h or "api.zebull.in" in h:
                    continue
                if h not in seen:
                    seen.add(h)
                    hosts.append(h)
            if not hosts:
                hosts = ["https://go.mynt.in/NorenWClientTP"]

            data = None
            last_error = None
            async with httpx.AsyncClient(timeout=12.0) as client:
                for host in hosts:
                    url = f"{host}/QuickAuth"
                    try:
                        logger.info(f"Zebu QuickAuth (OAuth) → {url} uid={zebu_uid}")
                        resp = await client.post(url, data=jdata, headers=headers)
                        if resp.status_code != 200:
                            last_error = f"HTTP {resp.status_code} from {host}"
                            logger.warning(f"Zebu QuickAuth {last_error}")
                            continue
                        if not resp.text or not resp.text.strip():
                            raise ValueError(
                                "Server returned empty response. "
                                "Check Vendor Code and App Key in MYNT portal."
                            )
                        data = resp.json()
                        break
                    except httpx.TimeoutException:
                        last_error = f"Timeout connecting to {host}"
                        logger.warning(f"Zebu QuickAuth timeout: {host}")
                        continue
                    except httpx.ConnectError as e:
                        last_error = f"Cannot reach {host}: {e}"
                        logger.warning(f"Zebu QuickAuth connect error: {host} — {e}")
                        continue

            if data is None:
                return {"emsg": last_error or "Cannot reach MYNT API (go.mynt.in)"}

            if data.get("stat") == "Ok" or data.get("susertoken"):
                logger.info("Zebu token exchange successful")
                return data
            else:
                logger.error(f"Zebu token exchange failed: {data}")
                return data

        except Exception as e:
            logger.error(f"Zebu token exchange error: {e}", exc_info=True)
            return {"emsg": str(e)}

    async def _try_refresh(self, db: AsyncSession, account: BrokerAccount) -> bool:
        """
        Attempt to refresh an expired token.

        Zebu's NorenOMS does not provide a standard refresh flow;
        tokens are valid for one trading session (~8 hours).
        Users must re-authenticate daily.

        This method is a placeholder for brokers that DO support
        refresh tokens (e.g. Angel, Fyers).
        """
        if not account.refresh_token_enc:
            return False

        # Placeholder — implement per-broker refresh logic here
        logger.info(
            f"Token refresh not supported for broker={account.broker}, "
            f"user must re-authenticate"
        )
        return False

    async def _zebu_quickauth_call(self, payload: dict) -> dict:
        """
        POST a built QuickAuth payload to Zebu/MYNT, trying the configured
        host then known fallbacks. Pure HTTP — caller builds the payload
        (uid/pwd/factor2/vc/appkey) and stores the resulting token.

        Returns the parsed response dict. Raises ValueError on failure.
        """
        _FALLBACK_HOSTS = [
            "https://go.mynt.in/NorenWClientTP",
            settings.ZEBU_API_URL,
        ]
        seen = set()
        hosts = []
        for h in _FALLBACK_HOSTS:
            h = (h or "").rstrip("/")
            if not h or "api.zebull.in" in h:
                continue
            if h not in seen:
                seen.add(h)
                hosts.append(h)
        if not hosts:
            hosts = ["https://go.mynt.in/NorenWClientTP"]

        jdata = "jData=" + json.dumps(payload)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = None
        last_error = None

        async with httpx.AsyncClient(timeout=12.0) as client:
            for host in hosts:
                url = f"{host}/QuickAuth"
                try:
                    logger.info(f"Zebu QuickAuth → {url} uid={payload.get('uid')}")
                    resp = await client.post(url, data=jdata, headers=headers)

                    if resp.status_code != 200:
                        body_preview = resp.text[:300] if resp.text else "(empty)"
                        logger.error(
                            f"Zebu QuickAuth HTTP {resp.status_code} from {host}: {body_preview}"
                        )
                        last_error = f"Zebu API returned HTTP {resp.status_code}"
                        continue

                    if not resp.text or not resp.text.strip():
                        logger.error(
                            f"Zebu QuickAuth: EMPTY response from {host}. "
                            "Check Vendor Code / App Key."
                        )
                        raise ValueError(
                            "Server returned empty response. "
                            "Check Vendor Code and App Key in MYNT portal."
                        )

                    data = resp.json()
                    break  # success — got a JSON response

                except httpx.TimeoutException:
                    logger.warning(f"Zebu QuickAuth timeout: {host}")
                    last_error = f"Timeout connecting to {host}"
                    continue
                except httpx.ConnectError as e:
                    logger.warning(f"Zebu QuickAuth connect error: {host} — {e}")
                    last_error = f"Cannot reach {host}"
                    continue

        if data is None:
            raise ValueError(
                last_error
                or "Cannot reach MYNT API (go.mynt.in). Check your App Key and server network."
            )

        if data.get("stat") != "Ok" and not data.get("susertoken"):
            error_msg = data.get("emsg", "Authentication failed")
            logger.error(f"Zebu QuickAuth failed: {error_msg}")
            raise ValueError(f"Zebu login failed: {error_msg}")

        return data

    async def _zebu_quickauth_headless(
        self, client_id: str, api_key: str, api_secret: str, password: str, factor2: str
    ) -> dict:
        """
        Headless Zebu QuickAuth using saved credentials — zero browser
        interaction. `api_secret` here is the saved App Key used to build
        the appkey hash (Zebu's QuickAuth has no separate "secret" field —
        the App Key itself is the secret material).
        """
        import hashlib

        uid = (client_id or "").strip()
        pwd = (password or "").strip()
        dob_or_pan = (factor2 or "").strip()
        api_key = (api_key or "").strip()
        api_secret = (api_secret or "").strip()
        if not uid or not api_key or not pwd or not dob_or_pan:
            raise ValueError(
                "Headless refresh needs a saved Zebu User ID, App Key, "
                "Trading Password, and DOB/PAN."
            )

        # QuickAuth appkey uses the MYNT App Key (saved as api_key), not the OAuth secret.
        appkey = hashlib.sha256(f"{uid}|{api_key or api_secret}".encode()).hexdigest()
        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()

        # vendor_code is per-user (saved as api_secret field when the user fills
        # the credential form). Global ZEBU_VENDOR_CODE is only the server-level
        # fallback for the admin/demo account — never override a per-user vc.
        vendor_code_to_use = self._resolve_zebu_vendor_code(
            uid=uid,
            custom_vc=api_secret,
            api_key=api_key
        )
        logger.debug(
            f"Zebu headless QuickAuth: uid={uid} vc={vendor_code_to_use}"
        )
        payload = {
            "apkversion": "1.0.0",
            "uid": uid,
            "pwd": pwd_hash,
            "factor2": dob_or_pan,
            "vc": vendor_code_to_use,
            "appkey": appkey,
            "imei": "alphasync",
            "source": "API",
        }
        return await self._zebu_quickauth_call(payload)

    # ────────────────────────────────────────────────────────────────
    # 8. Refresh — zero-click when a password was saved, else redirect
    # ────────────────────────────────────────────────────────────────

    async def refresh_session(self, db: AsyncSession, user_id: str, broker: str) -> dict:
        """
        Refresh a broker connection for the day.

        If the user saved their trading password (+ DOB/PAN for Zebu, or
        + TOTP secret for Alice Blue) when connecting, re-authenticate
        headlessly server-side — zero browser interaction. A saved-password
        failure is surfaced directly (it means the password needs updating,
        not a silent fallback). Otherwise, fall back to a one-click OAuth
        re-redirect using the saved App Key.
        """
        creds = await self._load_app_credentials(db, user_id, broker) or {}
        client_id = ""
        result = await db.execute(
            select(BrokerAccount).where(
                and_(BrokerAccount.user_id == user_id, BrokerAccount.broker == broker)
            )
        )
        account = result.scalar_one_or_none()
        if account:
            client_id = account.broker_user_id or ""
        if not client_id:
            client_id = (creds.get("client_id") or "").strip()

        if broker == "zebu" and creds.get("trading_password") and creds.get("factor2"):
            # Pass saved vendor_code explicitly as api_secret so _zebu_quickauth_headless
            # can use it for the vc field (api_secret slot is repurposed here because
            # Zebu QuickAuth has no OAuth secret — vendor_code is the per-user discriminator).
            saved_vendor_code = creds.get("vendor_code") or creds.get("api_secret") or ""
            try:
                data = await self._zebu_quickauth_headless(
                    client_id, creds.get("api_key", ""), saved_vendor_code,
                    creds["trading_password"], creds["factor2"],
                )
            except ValueError:
                raise
            session_token = data["susertoken"]
            broker_user_id = data.get("actid") or data.get("uid") or client_id
            extra = {
                "uid": data.get("uid", client_id),
                "actid": data.get("actid", client_id),
                "brkname": data.get("brkname", "ZEBU"),
            }
            await self._upsert_broker_account(
                db, user_id, broker, broker_user_id, encrypt_token(session_token), extra
            )
            logger.info(f"Zebu headless refresh OK: user={str(user_id)[:8]}")
            return {"success": True, "reauth_required": False, "broker": broker, "broker_user_id": broker_user_id}

        if broker == "aliceblue" and creds.get("trading_password") and creds.get("totp_secret"):
            session_token = await self._aliceblue_auto_authenticate(
                client_id, creds.get("api_key", ""), creds.get("api_secret", ""),
                creds["trading_password"], creds["totp_secret"],
            )
            extra = {"uid": client_id, "client_id": client_id, "brkname": "ALICEBLUE"}
            await self._upsert_broker_account(
                db, user_id, broker, client_id, encrypt_token(session_token), extra, expiry_hours=8
            )
            logger.info(f"Alice Blue headless refresh OK: user={str(user_id)[:8]}")
            return {"success": True, "reauth_required": False, "broker": broker, "broker_user_id": client_id}

        # No password saved (or unsupported broker) — fall back to the
        # existing-token check, then a fresh OAuth redirect if needed.
        status = await self.get_status(db, user_id, broker)
        if status.get("connected"):
            return {"success": True, "reauth_required": False, "broker": broker, "message": "Session still valid"}

        # Zebu API-only accounts cannot use the MYNT OAuth web login page.
        # Skip browser OAuth unless an OAuth secret was explicitly saved.
        if broker == "zebu" and not creds.get("api_secret"):
            return {
                "success": False,
                "reauth_required": True,
                "oauth_blocked": True,
                "broker": broker,
                "message": (
                    "Enter your Trading Password and Date of Birth / PAN to connect. "
                    "API-only MYNT accounts cannot use browser OAuth login."
                ),
            }

        connect_data = await self.generate_connect_url(db, user_id, broker)
        return {
            "success": False,
            "reauth_required": True,
            "broker": broker,
            "redirect_url": connect_data["redirect_url"],
            "state": connect_data["state"],
            "message": "Session expired — login required",
        }

    # ────────────────────────────────────────────────────────────────
    # 7. Direct Login (QuickAuth — no vendor SSO redirect needed)
    # ────────────────────────────────────────────────────────────────

    async def direct_login(
        self,
        db: AsyncSession,
        user_id: str,
        zebu_uid: str,
        password: str,
        totp: str = "",
        api_key: str = "",
        vendor_code: str = "",
    ) -> dict:
        """
        Authenticate directly via Zebu's QuickAuth API.

        This is the standard login method when vendor SSO redirect
        is unavailable. The user provides their Zebu credentials
        (User ID, Password, TOTP) and we exchange them for a session token.

        Returns: { "success": True, "broker_user_id": str }
        Raises: ValueError on authentication failure.
        """
        import hashlib

        # Refresh UX: if the caller left api_key/vendor_code blank (e.g. the
        # quick "Refresh" action), reuse whatever the user saved last time
        # instead of asking them to re-type it.
        saved_creds = None
        if not api_key or not vendor_code:
            saved_creds = await self._load_app_credentials(db, user_id, "zebu")

        effective_api_key = (api_key or (saved_creds or {}).get("api_key", "")).strip()
        # vendor_code is per-user — saved explicitly by the user in the credential form.
        # Do NOT fall through to the global ZEBU_VENDOR_CODE unless truly nothing is saved,
        # because mixing account A's vc with account B's uid causes a 400/auth-failed.
        effective_vendor_code = (
            vendor_code
            or (saved_creds or {}).get("vendor_code", "")
            or (saved_creds or {}).get("api_secret", "")
        ).strip()

        # Build appkey: SHA-256 of "uid|api_key"
        # api_key priority: user-provided api_key > saved api_key > server ZEBU_API_SECRET > ZEBU_API_KEY
        _api_secret = effective_api_key or settings.ZEBU_API_SECRET or settings.ZEBU_API_KEY
        if not _api_secret:
            raise ValueError(
                "API Key is required. Get it from MYNT portal → "
                "Client Code → API Key."
            )
        appkey_raw = f"{zebu_uid}|{_api_secret}"
        appkey = hashlib.sha256(appkey_raw.encode()).hexdigest()

        # Hash the password: SHA-256
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()

        # Resolve effective vendor code: per-user value > global setting > uid fallback
        vc = self._resolve_zebu_vendor_code(
            uid=zebu_uid,
            custom_vc=effective_vendor_code,
            api_key=effective_api_key
        )
        logger.info(
            f"Zebu direct_login: uid={zebu_uid} vc={vc} "
            f"api_key_set={bool(effective_api_key)}"
        )
        payload = {
            "apkversion": "1.0.0",
            "uid": zebu_uid,
            "pwd": pwd_hash,
            "factor2": totp,
            "vc": vc,
            "appkey": appkey,
            "imei": "alphasync",
            "source": "API",
        }

        data = await self._zebu_quickauth_call(payload)

        # ── Success — store token ───────────────────────────────────
        session_token = data["susertoken"]
        broker_user_id = data.get("actid", data.get("uid", zebu_uid))

        access_token_enc = encrypt_token(session_token)
        extra = {
            "uid": data.get("uid", zebu_uid),
            "actid": data.get("actid", zebu_uid),
            "brkname": data.get("brkname", "ZEBU"),
            "email": data.get("email", ""),
        }

        # Upsert broker account
        result = await db.execute(
            select(BrokerAccount).where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker == "zebu",
                )
            )
        )
        account = result.scalar_one_or_none()

        if account:
            account.access_token_enc = access_token_enc
            account.broker_user_id = broker_user_id
            account.extra_data_enc = encrypt_json(extra)
            account.is_active = True
            account.token_expiry = datetime.now(timezone.utc) + timedelta(hours=8)
            account.last_used_at = datetime.now(timezone.utc)
        else:
            account = BrokerAccount(
                user_id=user_id,
                broker="zebu",
                broker_user_id=broker_user_id,
                access_token_enc=access_token_enc,
                extra_data_enc=encrypt_json(extra),
                is_active=True,
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=8),
                connected_at=datetime.now(timezone.utc),
                last_used_at=datetime.now(timezone.utc),
            )
            db.add(account)

        # Persist whichever app credentials were actually supplied this time
        # (explicit user input takes priority) so "Refresh" never needs them
        # re-typed.
        new_creds = {k: v for k, v in {"api_key": api_key, "vendor_code": vendor_code}.items() if v}
        if new_creds:
            existing_creds = (saved_creds or {})
            account.credentials_enc = encrypt_json({**existing_creds, **new_creds})

        # Deactivate any other broker accounts for this user
        await db.execute(
            update(BrokerAccount)
            .where(
                and_(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.broker != "zebu",
                )
            )
            .values(is_active=False)
        )
        await db.flush()

        logger.info(
            f"Zebu direct login successful: user={str(user_id)[:8]} "
            f"broker_user={broker_user_id}"
        )

        return {
            "success": True,
            "broker": "zebu",
            "broker_user_id": broker_user_id,
        }


# ── Module-level singleton ──────────────────────────────────────────
broker_auth_service = BrokerAuthService()
