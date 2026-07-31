# models/data_feed_config.py - Database model for the admin-configured
# internal simulation engine (enable/disable, replay speed, live status)
# and optional real-broker historical EOD import (Zebu/MYNT).
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class DataFeedConfig(Base):
    """Single-row config for the internal simulation engine (admin-managed only)
    and, optionally, a real-broker credential set used only to pull historical
    EOD candles that seed the same internal simulator - never a live feed.

    The tick engine itself always runs in-process (no external vendor, no
    network hop for the live stream) - broker credentials here are only ever
    used for the one-off/periodic "import real historical prices" admin
    action, not for continuous trading or order placement.
    """

    __tablename__ = "data_feed_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Legacy columns from the old pretend-vendor client/server split, kept so
    # existing rows load without a migration. Repurposed below for the
    # optional Zebu historical-import credentials (api_key = client code,
    # api_secret = Zebu API secret, base_url = Zebu API base URL).
    api_key = Column(String(255), nullable=True)
    api_secret = Column(Text, nullable=True)  # AES-256-GCM encrypted, see services/crypto.py
    base_url = Column(String(500), nullable=True, default="http://localhost:8000")
    is_enabled = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    connection_status = Column(String(50), default="disconnected")  # disconnected, connecting, connected, error
    error_message = Column(Text, nullable=True)
    # Tracks which mock EOD generator version last seeded price_data, so a
    # code change to symbol coverage/anchors can force one re-seed even when
    # existing data already looks "recent" (see data_feed_session.py).
    seed_generation = Column(Integer, nullable=True)

    # ── Optional real-broker (Zebu) historical-import credentials ────────
    # broker is NULL/"" when only the internal simulator is used. When set
    # to "zebu", the admin "Import real historical prices" action logs into
    # Zebu's MYNT API once to pull real EOD candles instead of generating
    # deterministic mock ones - the simulator/tick engine is unchanged
    # either way, only price_data's source of truth differs.
    broker = Column(String(20), nullable=True)
    broker_client_code = Column(String(100), nullable=True)
    broker_password_enc = Column(Text, nullable=True)  # AES-256-GCM encrypted
    # Zebu's login "factor2" field: the account's DOB (DD-MM-YYYY) or PAN,
    # exactly as registered with Zebu - NOT a TOTP/authenticator code (Zebu's
    # API has no TOTP concept). Column kept as *_totp_secret_enc for the
    # underlying storage to avoid an extra migration; semantics corrected
    # via the get_broker_factor2/set_broker_factor2 accessors below.
    broker_totp_secret_enc = Column(Text, nullable=True)  # AES-256-GCM encrypted
    broker_vendor_code = Column(String(100), nullable=True)
    broker_last_import_at = Column(DateTime(timezone=True), nullable=True)
    broker_last_import_status = Column(String(50), nullable=True)
    broker_last_import_error = Column(Text, nullable=True)

    # ── Admin Zebu OAuth & Time-Delayed Feed Configuration ───────────────
    oauth_client_id = Column(String(100), nullable=True)
    oauth_secret_key_enc = Column(Text, nullable=True)
    oauth_redirect_url = Column(String(500), nullable=True)
    oauth_access_token_enc = Column(Text, nullable=True)
    oauth_refresh_token_enc = Column(Text, nullable=True)
    oauth_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    oauth_connection_status = Column(String(50), default="disconnected")
    oauth_last_error = Column(Text, nullable=True)
    feed_delay_seconds = Column(Integer, nullable=False, default=300, server_default=text("300"))
    redis_active_market_hours_only = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP"))

    def get_api_secret(self) -> str:
        """Decrypt and return the legacy/broker API secret, or '' if unset."""
        if not self.api_secret:
            return ""
        from services.crypto import decrypt_token
        try:
            return decrypt_token(self.api_secret)
        except Exception:
            # Pre-encryption legacy rows stored the secret in plaintext.
            # Fall back to the raw value so existing configs keep working
            # until the next save re-encrypts them.
            return self.api_secret

    def set_api_secret(self, plaintext: str) -> None:
        """Encrypt and store the legacy/broker API secret field."""
        from services.crypto import encrypt_token
        self.api_secret = encrypt_token(plaintext) if plaintext else None

    def get_broker_password(self) -> str:
        if not self.broker_password_enc:
            return ""
        from services.crypto import decrypt_token
        try:
            return decrypt_token(self.broker_password_enc)
        except Exception:
            return self.broker_password_enc

    def set_broker_password(self, plaintext: str) -> None:
        from services.crypto import encrypt_token
        self.broker_password_enc = encrypt_token(plaintext) if plaintext else None

    def get_broker_factor2(self) -> str:
        """Decrypt and return the stored Zebu login factor2 (DOB/PAN)."""
        if not self.broker_totp_secret_enc:
            return ""
        from services.crypto import decrypt_token
        try:
            return decrypt_token(self.broker_totp_secret_enc)
        except Exception:
            return self.broker_totp_secret_enc

    def set_broker_factor2(self, plaintext: str) -> None:
        from services.crypto import encrypt_token
        self.broker_totp_secret_enc = encrypt_token(plaintext) if plaintext else None

    # ── OAuth Crypto Accessors ───────────────────────────────────────────
    def get_oauth_secret_key(self) -> str:
        if not self.oauth_secret_key_enc:
            return ""
        from services.crypto import decrypt_token
        try:
            return decrypt_token(self.oauth_secret_key_enc)
        except Exception:
            return self.oauth_secret_key_enc

    def set_oauth_secret_key(self, plaintext: str) -> None:
        from services.crypto import encrypt_token
        self.oauth_secret_key_enc = encrypt_token(plaintext) if plaintext else None

    def get_oauth_access_token(self) -> str:
        if not self.oauth_access_token_enc:
            return ""
        from services.crypto import decrypt_token
        try:
            return decrypt_token(self.oauth_access_token_enc)
        except Exception:
            return self.oauth_access_token_enc

    def set_oauth_access_token(self, plaintext: str) -> None:
        from services.crypto import encrypt_token
        self.oauth_access_token_enc = encrypt_token(plaintext) if plaintext else None

    def get_oauth_refresh_token(self) -> str:
        if not self.oauth_refresh_token_enc:
            return ""
        from services.crypto import decrypt_token
        try:
            return decrypt_token(self.oauth_refresh_token_enc)
        except Exception:
            return self.oauth_refresh_token_enc

    def set_oauth_refresh_token(self, plaintext: str) -> None:
        from services.crypto import encrypt_token
        self.oauth_refresh_token_enc = encrypt_token(plaintext) if plaintext else None

