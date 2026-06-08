"""API Key Management — generate, manage, and validate API keys for tenants.

Provides:
- APIKeyGenerator: Create secure API keys
- APIKeyStore: Validate and manage keys
- Per-workspace key isolation
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class APIKey(BaseModel):
    """An API key for workspace authentication."""

    id: str = Field(default_factory=lambda: f"key_{uuid.uuid4().hex[:12]}")
    workspace_id: str = ""

    name: str = "default"
    """Human-readable key name."""

    key_hash: str = ""
    """SHA-256 hash of the actual key (never store plaintext)."""

    key_prefix: str = ""
    """First 8 characters of the key for display."""

    created_at: float = Field(default_factory=time.time)
    expires_at: float | None = None
    """None = no expiration."""

    last_used_at: float | None = None
    usage_count: int = 0

    active: bool = True

    # Rate limiting
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000

    # Quotas
    monthly_token_limit: int = 500000  # 500K tokens
    monthly_call_limit: int = 5000

    # Permissions
    allowed_scopes: list[str] = Field(default_factory=lambda: ["agents", "crews", "tasks"])
    denied_scopes: list[str] = Field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.active and not self.is_expired

    @property
    def days_until_expiry(self) -> int | None:
        if self.expires_at is None:
            return None
        days = int((self.expires_at - time.time()) / 86400)
        return max(days, 0)

    def has_scope(self, scope: str) -> bool:
        if scope in self.denied_scopes:
            return False
        return len(self.allowed_scopes) == 0 or scope in self.allowed_scopes

    def record_usage(self) -> None:
        self.last_used_at = time.time()
        self.usage_count += 1


class APIKeyStore:
    """API key management and validation.

    Usage:
        store = APIKeyStore()

        # Generate key
        raw_key, api_key = store.generate_key(
            workspace_id="ws_abc123",
            name="Production Key",
        )
        print(f"Key: {raw_key}")  # Only shown once!

        # Validate
        valid_key = store.validate(raw_key)
    """

    def __init__(self, storage_path: Path | str | None = None):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "keys")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._keys: dict[str, APIKey] = {}  # key_id -> APIKey
        self._hash_to_id: dict[str, str] = {}  # key_hash -> key_id
        self._load()

    def generate_key(
        self,
        workspace_id: str,
        name: str = "default",
        expires_in_days: int | None = None,
        monthly_token_limit: int = 500000,
        monthly_call_limit: int = 5000,
        allowed_scopes: list[str] | None = None,
    ) -> tuple[str, APIKey]:
        """Generate a new API key.

        Returns:
            (raw_key, api_key_record) — raw_key is shown once, api_key_record is stored
        """
        # Generate secure random key
        raw_key = f"ansiq_{secrets.token_urlsafe(32)}"

        # Hash the key for storage
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        # Create API key record
        api_key = APIKey(
            workspace_id=workspace_id,
            name=name,
            key_hash=key_hash,
            key_prefix=raw_key[:16] + "...",
            expires_at=(time.time() + expires_in_days * 86400 if expires_in_days else None),
            monthly_token_limit=monthly_token_limit,
            monthly_call_limit=monthly_call_limit,
            allowed_scopes=allowed_scopes or ["agents", "crews", "tasks", "sandbox"],
        )

        self._keys[api_key.id] = api_key
        self._hash_to_id[key_hash] = api_key.id
        self._save()

        logger.info("Generated API key '%s' for workspace %s", name, workspace_id)
        return raw_key, api_key

    def validate(self, raw_key: str) -> APIKey | None:
        """Validate an API key and return its record if valid."""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = self._hash_to_id.get(key_hash)

        if not key_id:
            return None

        key = self._keys.get(key_id)
        if key and key.is_valid:
            key.record_usage()
            self._save()
            return key

        return None

    def revoke_key(self, key_id: str) -> bool:
        """Revoke (deactivate) an API key."""
        key = self._keys.get(key_id)
        if key:
            key.active = False
            self._save()
            logger.info("Revoked API key %s", key_id)
            return True
        return False

    def delete_key(self, key_id: str) -> bool:
        """Permanently delete an API key."""
        key = self._keys.get(key_id)
        if key:
            self._hash_to_id.pop(key.key_hash, None)
            del self._keys[key_id]
            self._save()
            return True
        return False

    def get_keys_for_workspace(self, workspace_id: str) -> list[APIKey]:
        """Get all keys for a workspace."""
        return [k for k in self._keys.values() if k.workspace_id == workspace_id]

    def list_keys(self, include_expired: bool = False) -> list[APIKey]:
        """List all API keys."""
        keys = list(self._keys.values())
        if not include_expired:
            keys = [k for k in keys if k.is_valid]
        return sorted(keys, key=lambda k: k.created_at, reverse=True)

    def get_stats(self) -> dict[str, Any]:
        """Get API key statistics."""
        all_keys = list(self._keys.values())
        active = [k for k in all_keys if k.is_valid]
        return {
            "total_keys": len(all_keys),
            "active_keys": len(active),
            "expired_keys": len([k for k in all_keys if k.is_expired]),
            "total_usage": sum(k.usage_count for k in all_keys),
        }

    def _save(self) -> None:
        """Save key metadata to disk (never save raw keys)."""
        try:
            data = {
                "keys": [
                    {
                        "id": k.id,
                        "workspace_id": k.workspace_id,
                        "name": k.name,
                        "key_hash": k.key_hash,
                        "key_prefix": k.key_prefix,
                        "created_at": k.created_at,
                        "expires_at": k.expires_at,
                        "last_used_at": k.last_used_at,
                        "usage_count": k.usage_count,
                        "active": k.active,
                        "monthly_token_limit": k.monthly_token_limit,
                        "monthly_call_limit": k.monthly_call_limit,
                        "allowed_scopes": k.allowed_scopes,
                        "denied_scopes": k.denied_scopes,
                    }
                    for k in self._keys.values()
                ]
            }
            path = self.storage_path / "keys.json"
            path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug("Failed to save API keys: %s", e)

    def _load(self) -> None:
        """Load key metadata from disk."""
        try:
            path = self.storage_path / "keys.json"
            if path.exists():
                data = json.loads(path.read_text())
                for key_data in data.get("keys", []):
                    api_key = APIKey(**key_data)
                    self._keys[api_key.id] = api_key
                    self._hash_to_id[api_key.key_hash] = api_key.id
        except Exception as e:
            logger.debug("Failed to load API keys: %s", e)

    def __repr__(self) -> str:
        return f"APIKeyStore(keys={len(self._keys)})"
