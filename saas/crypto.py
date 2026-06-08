"""Symmetric encryption for secrets at rest (webhook secrets, MFA seeds, etc.).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from ``cryptography``. The key is
derived from ``ANSIQ_SECRET_KEY`` via SHA-256 so any sufficiently long
secret works as input — we never expose the raw Fernet key on disk.

If ``cryptography`` is not installed the module falls back to a no-op
pass-through (development only) and logs a one-time warning. In
production a missing cryptography package is a fatal configuration
error.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from saas.config import config

logger = logging.getLogger("ansiq.saas.crypto")


@lru_cache(maxsize=1)
def _fernet():
    """Build a Fernet instance from ANSIQ_SECRET_KEY.

    We hash the secret with SHA-256 (32 bytes) and base64-url-encode it
    to get a valid Fernet key. SHA-256 is acceptable here because the
    input already has ≥32 bytes of entropy from ``secrets.token_hex``.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        if config.is_production:
            raise RuntimeError(
                "FATAL: cryptography package is required in production "
                "for at-rest encryption of webhook secrets and MFA seeds."
            ) from exc
        logger.warning(
            "cryptography not installed — at-rest encryption DISABLED "
            "(dev only). Install with: pip install cryptography"
        )
        return None

    secret = config.secret_key
    if not secret or len(secret) < 32:
        if config.is_production:
            raise RuntimeError(
                "FATAL: ANSIQ_SECRET_KEY must be ≥32 chars in production "
                "to derive an encryption key."
            )
        # Dev fallback — never use this in prod.
        secret = "dev-only-insecure-encryption-key-padding!!"

    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string and return a URL-safe base64 token.

    No-op (returns the input unchanged) when cryptography is unavailable
    in dev — the returned value is still stored in the DB column so no
    migration is needed when cryptography is later installed.
    """
    if not plaintext:
        return plaintext
    f = _fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`.

    Returns the input unchanged if it doesn't look like a Fernet token
    (so legacy plaintext values still load) or if cryptography is
    unavailable in dev.
    """
    if not token:
        return token
    f = _fernet()
    if f is None:
        return token
    # Fernet tokens always start with "gAAAAA" (version 0x80 + base64).
    if not token.startswith("gAAAAA"):
        # Legacy plaintext — return as-is.
        return token
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to decrypt value")
        return ""


def is_encryption_enabled() -> bool:
    """Return True when at-rest encryption is active."""
    return _fernet() is not None
