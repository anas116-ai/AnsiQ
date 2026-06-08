"""API Key authentication middleware for the AnsiQ API.

Provides optional API key protection for production deployments.
Keys are configured via the ANSIQ_API_KEYS environment variable
(a comma-separated list of keys) or a config file at ~/.ansiq/api_keys.txt.

Usage:
    # Allow all requests (development, default)
    # Enable via environment:
    ANSIQ_API_KEYS=sk-abc123,sk-xyz789 uvicorn ...
    # Or create ~/.ansiq/api_keys.txt with one key per line

    # Client sends: Authorization: Bearer sk-abc123
    # Or:            X-API-Key: sk-abc123
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ── Key Loading ──

_security = HTTPBearer(auto_error=False)
_loaded_keys: list[str] | None = None


def _load_api_keys() -> list[str]:
    """Load API keys from environment variable or config file.

    Returns an empty list if no keys are configured (open access).
    """
    global _loaded_keys
    if _loaded_keys is not None:
        return _loaded_keys

    keys: list[str] = []

    # 1. Environment variable
    env_keys = os.environ.get("ANSIQ_API_KEYS", "").strip()
    if env_keys:
        keys.extend(k.strip() for k in env_keys.split(",") if k.strip())

    # 2. Config file
    key_file = Path.home() / ".ansiq" / "api_keys.txt"
    if key_file.exists():
        try:
            for line in key_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    keys.append(line)
        except Exception as e:
            logger.warning("Failed to read API keys file %s: %s", key_file, e)

    _loaded_keys = keys
    if keys:
        logger.info("Loaded %d API key(s)", len(keys))
    return keys


def reload_api_keys() -> None:
    """Force reload of API keys from config sources."""
    global _loaded_keys
    _loaded_keys = None
    _load_api_keys()


def is_auth_enabled() -> bool:
    """Check if API key authentication is configured."""
    return len(_load_api_keys()) > 0


# ── Auth Check ──


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> None:
    """FastAPI dependency that validates the API key.

    If no keys are configured, all requests are allowed (development mode).
    If keys are configured, the request must include a valid key via:
    - Authorization: Bearer <key>
    - X-API-Key: <key>
    """
    keys = _load_api_keys()
    if not keys:
        # No keys configured — open access
        return

    # Check Authorization header (via HTTPBearer dep)
    if credentials is not None and credentials.credentials in keys:
        return

    # Fallback: check X-API-Key header
    api_key = request.headers.get("X-API-Key", "")
    if api_key in keys:
        return

    # No valid key found
    logger.warning("Unauthorized API request to %s %s", request.method, request.url.path)
    raise HTTPException(
        status_code=401,
        detail="Unauthorized. Provide a valid API key via Authorization: Bearer <key>",
        headers={"WWW-Authenticate": "Bearer"},
    )
