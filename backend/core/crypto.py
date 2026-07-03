"""Symmetric encryption for secrets that must be replayable (not hashable).

Used for per-user Hardcover API tokens: unlike Tome's own API keys (stored as
SHA-256 hashes), a third-party token has to be sent back out verbatim, so it is
encrypted at rest with a Fernet key derived from the server secret. Rotating
TOME_SECRET_KEY therefore invalidates stored tokens — callers must treat a
failed decrypt as "not linked" and ask the user to re-link.
"""
import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.core.config import settings

logger = logging.getLogger(__name__)

_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        # Fernet wants a urlsafe-base64 32-byte key; derive one deterministically
        # from the resolved server secret (env var or {data_dir}/secret.key).
        digest = hashlib.sha256(settings.resolve_secret_key().encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt, returning None for empty input or an undecryptable value
    (e.g. after a TOME_SECRET_KEY rotation) — never raising."""
    if not ciphertext:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        logger.warning("Stored secret failed to decrypt (secret key rotated?)")
        return None
