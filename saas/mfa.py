"""TOTP (RFC 6238) multi-factor authentication.

Generates and validates one-time codes compatible with Google
Authenticator, Authy, 1Password, etc. Secrets are stored encrypted
(via :mod:`saas.crypto`) so a database leak does not let an attacker
recover valid TOTP seeds.

If ``pyotp`` is not installed, MFA enrolment endpoints will raise a
clear 501. Login still works for users without MFA.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import secrets

# qrcode and pyotp are imported lazily so the SaaS app can boot even
# if those optional deps are not installed. MFA endpoints will return
# a clear 501 in that case.
from saas.crypto import decrypt, encrypt

logger = logging.getLogger("ansiq.saas.mfa")


# ── Helpers ──────────────────────────────────────────────────────────────


def _issuer() -> str:
    """Issuer name shown in the user's authenticator app."""
    return os.getenv("ANSIQ_MFA_ISSUER", "AnsiQ")


def _label(email: str) -> str:
    """OTP label, e.g. ``AnsiQ:alice@example.com``."""
    return f"{_issuer()}:{email}"


def is_available() -> bool:
    """True when pyotp is importable."""
    try:
        import pyotp  # noqa: F401

        return True
    except ImportError:
        return False


def _require_pyotp():
    try:
        import pyotp

        return pyotp
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pyotp is required for MFA. Install with: pip install pyotp qrcode[pil]"
        ) from exc


# ── Enrollment ───────────────────────────────────────────────────────────


def generate_secret() -> str:
    """Return a fresh 160-bit base32 secret (suitable for authenticator apps)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(email: str, secret: str) -> str:
    """Build the ``otpauth://`` URI for QR-code generation."""
    pyotp = _require_pyotp()
    return pyotp.TOTP(secret).provisioning_uri(name=_label(email), issuer_name=_issuer())


def qr_code_png(uri: str) -> bytes:
    """Render the provisioning URI as a PNG (for inline display)."""
    try:
        import qrcode
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "qrcode[pil] is required for MFA QR codes. Install with: pip install 'qrcode[pil]'"
        ) from exc
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Verification ────────────────────────────────────────────────────────


def verify(secret_encrypted: str | None, code: str) -> bool:
    """Validate a 6-digit TOTP code against an encrypted secret.

    The code is rejected (without DB hit) when the secret is empty or
    the user has not enabled MFA. We also enforce a ±1 step window so
    legitimate clock drift works, but not more.
    """
    if not secret_encrypted or not code:
        return False
    secret = decrypt(secret_encrypted)
    if not secret:
        return False
    pyotp = _require_pyotp()
    totp = pyotp.TOTP(secret)
    # Reject obviously malformed codes before hitting pyotp.
    code_clean = "".join(c for c in code if c.isalnum())
    if not code_clean.isdigit() or not (4 <= len(code_clean) <= 8):
        return False
    return bool(totp.verify(code_clean, valid_window=1))


def encrypt_secret(plaintext_secret: str) -> str:
    """Encrypt a freshly-generated MFA secret for at-rest storage."""
    return encrypt(plaintext_secret)
