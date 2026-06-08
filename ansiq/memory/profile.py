"""Profile Manager — builds and maintains user/agent profiles over time.

Tracks preferences, behavior patterns, and learned traits
for personalized agent interactions.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE_PATH = Path.home() / ".ansiq" / "profiles"


class Trait(BaseModel):
    """A learned trait or preference about a user."""

    name: str
    value: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = "observation"
    observed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class UserProfile(BaseModel):
    """Complete user profile with traits, preferences, and history."""

    user_id: str
    name: str | None = None
    traits: list[Trait] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    interaction_count: int = 0
    last_interaction: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ProfileManager:
    """Manages user/agent profiles with persistent storage.

    Profiles are stored as JSON files and loaded on demand.
    """

    def __init__(self, profiles_dir: Path | str | None = None):
        self.profiles_dir = Path(profiles_dir or _DEFAULT_PROFILE_PATH)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, UserProfile] = {}

    def _profile_path(self, user_id: str) -> Path:
        return self.profiles_dir / f"{user_id}.json"

    def get_profile(self, user_id: str) -> UserProfile:
        """Get a user's profile, creating it if it doesn't exist."""
        if user_id in self._cache:
            return self._cache[user_id]

        path = self._profile_path(user_id)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                profile = UserProfile(**data)
                self._cache[user_id] = profile
                return profile
            except Exception as e:
                logger.warning("Failed to load profile for '%s': %s", user_id, e)

        profile = UserProfile(user_id=user_id)
        self._cache[user_id] = profile
        self._save_profile(profile)
        return profile

    def save_profile(self, profile: UserProfile) -> None:
        """Save a profile to disk."""
        profile.updated_at = datetime.now(UTC).isoformat()
        self._cache[profile.user_id] = profile
        self._save_profile(profile)

    def _save_profile(self, profile: UserProfile) -> None:
        """Internal: write profile to disk."""
        path = self._profile_path(profile.user_id)
        try:
            path.write_text(profile.model_dump_json(indent=2))
            logger.debug("Saved profile for '%s'", profile.user_id)
        except Exception as e:
            logger.error("Failed to save profile for '%s': %s", profile.user_id, e)

    def record_interaction(
        self,
        user_id: str,
        interaction_type: str,
        data: dict[str, Any] | None = None,
    ) -> UserProfile:
        """Record an interaction and update the profile."""
        profile = self.get_profile(user_id)
        profile.interaction_count += 1
        profile.last_interaction = datetime.now(UTC).isoformat()
        self.save_profile(profile)
        return profile

    def add_trait(
        self,
        user_id: str,
        name: str,
        value: str,
        confidence: float = 0.5,
        source: str = "observation",
    ) -> UserProfile:
        """Add or update a trait in the user's profile."""
        profile = self.get_profile(user_id)

        # Update existing trait or add new one
        for trait in profile.traits:
            if trait.name == name:
                trait.value = value
                trait.confidence = confidence
                trait.source = source
                trait.observed_at = datetime.now(UTC).isoformat()
                self.save_profile(profile)
                return profile

        profile.traits.append(Trait(name=name, value=value, confidence=confidence, source=source))
        self.save_profile(profile)
        return profile

    def get_trait(self, user_id: str, name: str) -> Trait | None:
        """Get a specific trait by name."""
        profile = self.get_profile(user_id)
        for trait in profile.traits:
            if trait.name == name:
                return trait
        return None

    def set_preference(self, user_id: str, key: str, value: Any) -> UserProfile:
        """Set a user preference."""
        profile = self.get_profile(user_id)
        profile.preferences[key] = value
        self.save_profile(profile)
        return profile

    def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        profile = self.get_profile(user_id)
        return profile.preferences.get(key, default)

    def get_profile_summary(self, user_id: str) -> str:
        """Get a human-readable summary of the profile."""
        profile = self.get_profile(user_id)
        parts = [f"Profile: {profile.user_id}"]
        parts.append(f"Interactions: {profile.interaction_count}")

        if profile.traits:
            parts.append("\nTraits:")
            for trait in profile.traits:
                parts.append(
                    f"  - {trait.name}: {trait.value} (confidence: {trait.confidence:.0%})"
                )

        if profile.preferences:
            parts.append("\nPreferences:")
            for key, value in profile.preferences.items():
                parts.append(f"  - {key}: {value}")

        return "\n".join(parts)

    def delete_profile(self, user_id: str) -> bool:
        """Delete a user's profile."""
        self._cache.pop(user_id, None)
        path = self._profile_path(user_id)
        if path.exists():
            path.unlink()
            logger.info("Deleted profile for '%s'", user_id)
            return True
        return False

    def list_profiles(self) -> list[str]:
        """List all profile user IDs."""
        return [p.stem for p in self.profiles_dir.glob("*.json")]
