"""Tenant Management — multi-tenant support for SaaS deployment.

Provides:
- Organization and workspace management
- Per-tenant isolation
- Workspace membership and roles
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TenantRole(str):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class WorkspaceMember(BaseModel):
    """A member of a workspace."""

    user_id: str
    role: str = TenantRole.MEMBER
    joined_at: float = Field(default_factory=time.time)


class Workspace(BaseModel):
    """A workspace within an organization."""

    id: str = Field(default_factory=lambda: f"ws_{uuid.uuid4().hex[:12]}")
    name: str
    description: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    api_key_id: str | None = None
    """Associated API key for authentication."""

    members: list[WorkspaceMember] = Field(default_factory=list)

    settings: dict[str, Any] = Field(default_factory=dict)

    # Quotas
    max_members: int = 10
    max_api_keys: int = 3
    monthly_token_limit: int = 1000000  # 1M tokens
    monthly_calls_limit: int = 10000

    @property
    def member_count(self) -> int:
        return len(self.members)

    def add_member(self, user_id: str, role: str = TenantRole.MEMBER) -> bool:
        if self.member_count >= self.max_members:
            return False
        if any(m.user_id == user_id for m in self.members):
            return False  # Already a member
        self.members.append(WorkspaceMember(user_id=user_id, role=role))
        self.updated_at = time.time()
        return True

    def remove_member(self, user_id: str) -> bool:
        original_count = len(self.members)
        self.members = [m for m in self.members if m.user_id != user_id]
        if len(self.members) < original_count:
            self.updated_at = time.time()
            return True
        return False

    def get_member(self, user_id: str) -> WorkspaceMember | None:
        return next((m for m in self.members if m.user_id == user_id), None)


class Organization(BaseModel):
    """An organization that owns workspaces and members."""

    id: str = Field(default_factory=lambda: f"org_{uuid.uuid4().hex[:12]}")
    name: str
    description: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    owner_id: str = ""
    """User ID of the organization owner."""

    workspaces: list[Workspace] = Field(default_factory=list)

    # Billing
    plan: str = "free"
    """Plan tier: free, pro, enterprise"""

    billing_email: str = ""

    # Quotas (per org)
    max_workspaces: int = 3
    max_members_total: int = 20
    monthly_token_limit: int = 5000000  # 5M tokens

    @property
    def workspace_count(self) -> int:
        return len(self.workspaces)

    def create_workspace(self, name: str, description: str = "") -> Workspace:
        if self.workspace_count >= self.max_workspaces:
            raise ValueError(f"Workspace limit ({self.max_workspaces}) reached")
        ws = Workspace(name=name, description=description)
        self.workspaces.append(ws)
        self.updated_at = time.time()
        logger.info("Created workspace '%s' in org '%s'", name, self.name)
        return ws

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        return next((w for w in self.workspaces if w.id == workspace_id), None)

    def delete_workspace(self, workspace_id: str) -> bool:
        original_count = len(self.workspaces)
        self.workspaces = [w for w in self.workspaces if w.id != workspace_id]
        return len(self.workspaces) < original_count


class TenantManager:
    """Multi-tenant management for SaaS deployment.

    Usage:
        manager = TenantManager()

        # Create org
        org = manager.create_organization(name="Acme Corp", owner_id="user_123")

        # Create workspace
        ws = org.create_workspace(name="Research Team")

        # Add members
        ws.add_member("user_456", role=TenantRole.MEMBER)
        ws.add_member("user_789", role=TenantRole.VIEWER)

        # List all workspaces
        workspaces = manager.list_workspaces()
    """

    def __init__(self, storage_path: Path | str | None = None):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "tenants")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._organizations: dict[str, Organization] = {}
        self._workspace_org_map: dict[str, str] = {}  # workspace_id -> org_id
        self._load()

    def create_organization(
        self,
        name: str,
        owner_id: str,
        description: str = "",
        plan: str = "free",
    ) -> Organization:
        """Create a new organization."""
        org = Organization(
            name=name,
            owner_id=owner_id,
            description=description,
            plan=plan,
        )
        # Add owner as first member
        owner_ws = org.create_workspace("Default Workspace", "Primary workspace")
        owner_ws.add_member(owner_id, role=TenantRole.OWNER)

        self._organizations[org.id] = org
        self._workspace_org_map[owner_ws.id] = org.id
        self._save()

        logger.info("Created organization '%s' with owner '%s'", name, owner_id)
        return org

    def get_organization(self, org_id: str) -> Organization | None:
        return self._organizations.get(org_id)

    def list_organizations(self) -> list[Organization]:
        return list(self._organizations.values())

    def get_workspace(self, workspace_id: str) -> Organization | None:
        """Get the organization that owns a workspace."""
        org_id = self._workspace_org_map.get(workspace_id)
        if org_id:
            org = self._organizations.get(org_id)
            if org:
                return org.get_workspace(workspace_id)
        return None

    def list_workspaces(self) -> list[Workspace]:
        """List all workspaces across all organizations."""
        all_workspaces = []
        for org in self._organizations.values():
            all_workspaces.extend(org.workspaces)
        return all_workspaces

    def delete_organization(self, org_id: str) -> bool:
        """Delete an organization and all its workspaces."""
        if org_id in self._organizations:
            org = self._organizations.pop(org_id)
            for ws in org.workspaces:
                self._workspace_org_map.pop(ws.id, None)
            self._save()
            logger.info("Deleted organization '%s'", org_id)
            return True
        return False

    def _save(self) -> None:
        """Save tenant data to disk."""
        try:
            data = {
                "organizations": [
                    {
                        "id": org.id,
                        "name": org.name,
                        "description": org.description,
                        "owner_id": org.owner_id,
                        "plan": org.plan,
                        "created_at": org.created_at,
                        "workspace_count": org.workspace_count,
                        "workspaces": [
                            {
                                "id": ws.id,
                                "name": ws.name,
                                "description": ws.description,
                                "members": [m.model_dump() for m in ws.members],
                                "monthly_token_limit": ws.monthly_token_limit,
                            }
                            for ws in org.workspaces
                        ],
                    }
                    for org in self._organizations.values()
                ]
            }
            path = self.storage_path / "tenants.json"
            path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug("Failed to save tenant data: %s", e)

    def _load(self) -> None:
        """Load tenant data from disk."""
        try:
            path = self.storage_path / "tenants.json"
            if path.exists():
                data = json.loads(path.read_text())
                for org_data in data.get("organizations", []):
                    org = Organization(
                        id=org_data["id"],
                        name=org_data["name"],
                        description=org_data.get("description", ""),
                        owner_id=org_data.get("owner_id", ""),
                        plan=org_data.get("plan", "free"),
                        created_at=org_data.get("created_at", time.time()),
                    )
                    self._organizations[org.id] = org
                    for ws_data in org_data.get("workspaces", []):
                        ws = Workspace(
                            id=ws_data["id"],
                            name=ws_data["name"],
                            description=ws_data.get("description", ""),
                            monthly_token_limit=ws_data.get("monthly_token_limit", 1000000),
                        )
                        for m_data in ws_data.get("members", []):
                            ws.members.append(WorkspaceMember(**m_data))
                        org.workspaces.append(ws)
                        self._workspace_org_map[ws.id] = org.id
        except Exception as e:
            logger.debug("Failed to load tenant data: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Get tenant statistics."""
        total_members = sum(
            sum(ws.member_count for ws in org.workspaces) for org in self._organizations.values()
        )
        return {
            "organizations": len(self._organizations),
            "total_workspaces": sum(o.workspace_count for o in self._organizations.values()),
            "total_members": total_members,
            "plans": {
                plan: sum(1 for o in self._organizations.values() if o.plan == plan)
                for plan in ["free", "pro", "enterprise"]
            },
        }

    def __repr__(self) -> str:
        return f"TenantManager(orgs={len(self._organizations)}, workspaces={sum(o.workspace_count for o in self._organizations.values())})"
