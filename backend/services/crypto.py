import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from config.settings import settings

_HKDF_INFO = b"alphasync-data-feed-secret-encryption"
_NONCE_SIZE = 12  # bytes — standard for AES-GCM

def _derive_key(master_key: str) -> bytes:
    """Derive a 256-bit AES key from the master secret using HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    )
    return hkdf.derive(master_key.encode("utf-8"))

def _get_key() -> bytes:
    """Load and derive the encryption key from settings."""
    raw = settings.DATA_FEED_ENCRYPTION_KEY
    if not raw or len(raw) < 32:
        raise ValueError(
            "DATA_FEED_ENCRYPTION_KEY must be set and at least 32 characters."
        )
    return _derive_key(raw)

def encrypt_token(plaintext: str) -> str:
    """Encrypt a string (e.g. the internal simulation engine client secret) for database storage."""
    if not plaintext:
        return ""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

def decrypt_token(encrypted: str) -> str:
    """Decrypt a string stored in the database."""
    if not encrypted:
        return ""
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.urlsafe_b64decode(encrypted)
    nonce = raw[:_NONCE_SIZE]
    ciphertext = raw[_NONCE_SIZE:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
