"""Audit Log — immutable record of all security-relevant events.

Every login, permission check, key rotation, and admin action is recorded.
Provides:
- AuditEvent — individual event
- AuditLog — event collection with search and export
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """Categories of auditable events."""

    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"

    LOGIN_SUCCESS = "auth.login_success"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"

    SESSION_CREATED = "session.created"
    SESSION_REVOKED = "session.revoked"

    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"

    PERMISSION_CHECK_FAILED = "permission.denied"
    PERMISSION_CHECK_PASSED = "permission.granted"

    AGENT_CREATED = "agent.created"
    AGENT_EXECUTED = "agent.executed"
    AGENT_DELETED = "agent.deleted"

    CREW_EXECUTED = "crew.executed"
    TASK_EXECUTED = "task.executed"

    SANDBOX_EXECUTED = "sandbox.executed"
    SANDBOX_VIOLATION = "sandbox.violation"

    COST_BUDGET_EXCEEDED = "cost.budget_exceeded"

    SYSTEM_ERROR = "system.error"

    GENERIC = "generic"


class AuditEvent(BaseModel):
    """A single auditable event — immutable once created."""

    id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    timestamp: float = Field(default_factory=time.time)

    event_type: EventType = EventType.GENERIC
    actor_id: str = ""
    """User ID or 'system' if automated."""

    target_id: str = ""
    """ID of the resource acted upon."""

    description: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    ip_address: str = ""
    user_agent: str = ""
    session_id: str = ""

    success: bool = True
    error_message: str | None = None

    organization_id: str | None = None
    workspace_id: str | None = None

    @property
    def datetime_iso(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.datetime_iso,
            "event_type": self.event_type.value,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "description": self.description,
            "details": self.details,
            "ip_address": self.ip_address,
            "success": self.success,
            "error_message": self.error_message,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
        }


class AuditLog:
    """Immutable audit trail with search and export.

    Usage:
        audit = AuditLog()

        audit.log(
            event_type=EventType.LOGIN_SUCCESS,
            actor_id="usr_abc",
            description="Successful login",
            ip_address="192.168.1.1",
        )

        # Search
        events = audit.search(event_type=EventType.LOGIN_SUCCESS)

        # Export
        audit.export_json("audit_log.json")
    """

    def __init__(
        self,
        storage_path: Path | str | None = None,
        max_events: int = 10000,
    ):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "audit")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.max_events = max_events
        self._events: list[AuditEvent] = []
        self._load()

    def log(
        self,
        event_type: EventType = EventType.GENERIC,
        actor_id: str = "",
        target_id: str = "",
        description: str = "",
        details: dict[str, Any] | None = None,
        ip_address: str = "",
        user_agent: str = "",
        session_id: str = "",
        success: bool = True,
        error_message: str | None = None,
        organization_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AuditEvent:
        """Record an audit event."""
        event = AuditEvent(
            event_type=event_type,
            actor_id=actor_id,
            target_id=target_id,
            description=description,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            success=success,
            error_message=error_message,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

        self._events.append(event)

        # Auto-prune if too many events
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]

        self._save()
        logger.debug("Audit: %s by %s", event_type.value, actor_id or "system")
        return event

    def search(
        self,
        event_type: EventType | None = None,
        actor_id: str | None = None,
        target_id: str | None = None,
        since: float | None = None,
        organization_id: str | None = None,
        success_only: bool | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Search audit events with optional filters."""
        results = list(self._events)

        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if actor_id:
            results = [e for e in results if e.actor_id == actor_id]
        if target_id:
            results = [e for e in results if e.target_id == target_id]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if organization_id:
            results = [e for e in results if e.organization_id == organization_id]
        if success_only is not None:
            results = [e for e in results if e.success == success_only]

        # Most recent first
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]

    def get_event(self, event_id: str) -> AuditEvent | None:
        return next((e for e in self._events if e.id == event_id), None)

    def get_count(
        self,
        event_type: EventType | None = None,
        since: float | None = None,
    ) -> int:
        results = self._events
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if since:
            results = [e for e in results if e.timestamp >= since]
        return len(results)

    def get_stats(self, since: float | None = None) -> dict[str, Any]:
        """Get audit statistics."""
        events = self._events
        if since:
            events = [e for e in events if e.timestamp >= since]

        failed_logins = len([e for e in events if e.event_type == EventType.LOGIN_FAILED])
        successful_logins = len([e for e in events if e.event_type == EventType.LOGIN_SUCCESS])
        permission_denials = len(
            [e for e in events if e.event_type == EventType.PERMISSION_CHECK_FAILED]
        )

        return {
            "total_events": len(events),
            "failed_logins": failed_logins,
            "successful_logins": successful_logins,
            "permission_denials": permission_denials,
            "events_by_type": {
                et.value: len([e for e in events if e.event_type == et])
                for et in EventType
                if any(e.event_type == et for e in events)
            },
        }

    def export_json(self, path: Path | str | None = None) -> str:
        """Export audit log to JSON."""
        path = Path(path or self.storage_path / "audit_export.json")
        data = {
            "export_time": time.time(),
            "total_events": len(self._events),
            "events": [e.to_dict() for e in self._events[-2000:]],
        }
        path.write_text(json.dumps(data, indent=2))
        logger.info("Exported %d audit events to %s", data["total_events"], path)
        return str(path)

    def _save(self) -> None:
        """Save recent events to disk."""
        try:
            path = self.storage_path / "audit.json"
            recent = self._events[-500:]
            data = [e.to_dict() for e in recent]
            path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug("Failed to save audit log: %s", e)

    def _load(self) -> None:
        """Load audit events from disk."""
        try:
            path = self.storage_path / "audit.json"
            if not path.exists():
                return
            data = json.loads(path.read_text())
            for item in data:
                # Convert ISO timestamp strings back to floats if needed
                ts = item.get("timestamp")
                if isinstance(ts, str):
                    try:
                        item["timestamp"] = datetime.fromisoformat(ts).timestamp()
                    except (ValueError, TypeError):
                        item["timestamp"] = time.time()
                self._events.append(AuditEvent(**item))
        except Exception as e:
            logger.debug("Failed to load audit log: %s", e)

    def clear(self) -> None:
        """Clear all audit events (admin only)."""
        self._events.clear()
        self._save()
        logger.warning("Audit log cleared")

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        return f"AuditLog(events={len(self._events)})"
