"""
Broker Crypto — AES-GCM encryption for broker access tokens.

Tokens are encrypted at rest in the database and decrypted only when
needed to open a WebSocket session. The encryption key is derived from
the BROKER_ENCRYPTION_KEY environment variable using HKDF.

Algorithm:  AES-256-GCM  (authenticated encryption)
Key:        Derived via HKDF-SHA256 from BROKER_ENCRYPTION_KEY
Nonce:      Random 12 bytes, prepended to ciphertext
Tag:        16 bytes, appended by GCM automatically
Storage:    base64(nonce + ciphertext + tag)

Why AES-GCM:
    - Provides both confidentiality AND integrity.
    - If someone tampers with the ciphertext, decryption fails loudly.
    - Standard, auditable, no custom crypto.

IMPORTANT:
    - BROKER_ENCRYPTION_KEY must be at least 32 characters.
    - Rotate by re-encrypting all rows with new key + maintaining old
      key for a migration window (not implemented yet — Phase 2).
    - NEVER log decrypted tokens.
"""

import base64
import json
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger(__name__)

# ── Key derivation ──────────────────────────────────────────────────

_HKDF_INFO = b"alphasync-broker-token-encryption"
_NONCE_SIZE = 12  # bytes — standard for AES-GCM


def _derive_key(master_key: str) -> bytes:
    """Derive a 256-bit AES key from the master secret using HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,  # deterministic derivation — acceptable here
        info=_HKDF_INFO,
    )
    return hkdf.derive(master_key.encode("utf-8"))


def _get_key() -> bytes:
    """Load and derive the encryption key from settings."""
    from config.settings import settings

    raw = settings.BROKER_ENCRYPTION_KEY
    if not raw or len(raw) < 32:
        raise ValueError(
            "BROKER_ENCRYPTION_KEY must be set and at least 32 characters. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return _derive_key(raw)


# ── Public API ──────────────────────────────────────────────────────


def encrypt_token(plaintext: str) -> str:
    """
    Encrypt a token string for database storage.

    Returns a base64-encoded string containing nonce + ciphertext + tag.
    """
    if not plaintext:
        return ""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # nonce (12) + ciphertext + tag (16) — all in one blob
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_token(encrypted: str) -> str:
    """
    Decrypt a token stored in the database.

    Raises ValueError on tampered or invalid data.
    """
    if not encrypted:
        return ""
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.urlsafe_b64decode(encrypted)
    nonce = raw[:_NONCE_SIZE]
    ciphertext = raw[_NONCE_SIZE:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def encrypt_json(data: dict) -> str:
    """Encrypt a dict as JSON for the extra_data_enc column."""
    return encrypt_token(json.dumps(data))


def decrypt_json(encrypted: str) -> dict:
    """Decrypt extra_data_enc back to a dict."""
    raw = decrypt_token(encrypted)
    return json.loads(raw) if raw else {}
