"""Tests for the ansiq.auth module — User, Role, Permission, RBACManager, AuditLog."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ansiq.auth.audit import AuditEvent, AuditLog, EventType
from ansiq.auth.models import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    Session,
    User,
)


class TestPermission:
    """Test Permission enum."""

    def test_permission_values(self):
        assert Permission.AGENT_CREATE.value == "agent:create"
        assert Permission.SANDBOX_EXECUTE.value == "sandbox:execute"

    def test_permission_count(self):
        assert len(list(Permission)) >= 25


class TestRole:
    """Test Role enum with permission sets."""

    def test_role_values(self):
        assert Role.SUPER_ADMIN.value == "super_admin"
        assert Role.MEMBER.value == "member"
        assert Role.VIEWER.value == "viewer"

    def test_super_admin_has_all_permissions(self):
        assert len(ROLE_PERMISSIONS[Role.SUPER_ADMIN]) == len(list(Permission))

    def test_admin_has_core_permissions(self):
        admin_perms = ROLE_PERMISSIONS[Role.ADMIN]
        assert Permission.AGENT_CREATE in admin_perms
        assert Permission.ADMIN_MANAGE_USERS in admin_perms

    def test_member_limited(self):
        member_perms = ROLE_PERMISSIONS[Role.MEMBER]
        assert Permission.AGENT_CREATE in member_perms
        assert Permission.ADMIN_MANAGE_USERS not in member_perms

    def test_viewer_read_only(self):
        viewer_perms = ROLE_PERMISSIONS[Role.VIEWER]
        assert Permission.AGENT_READ in viewer_perms
        assert Permission.AGENT_CREATE not in viewer_perms


class TestUser:
    """Test User model."""

    def test_create_user(self):
        user = User(email="test@example.com", username="tester")
        assert user.email == "test@example.com"
        assert user.role == Role.MEMBER
        assert user.active is True
        assert user.id.startswith("usr_")

    def test_password(self):
        user = User(email="pw@test.com")
        user.set_password("secure_password_123")
        assert user.verify_password("secure_password_123") is True
        assert user.verify_password("wrong_password") is False

    def test_empty_password_fails(self):
        user = User(email="empty@test.com")
        assert user.verify_password("anything") is False

    def test_super_admin_permissions(self):
        user = User(email="admin@test.com", role=Role.SUPER_ADMIN)
        assert user.has_permission(Permission.ADMIN_MANAGE_USERS) is True
        assert user.has_permission(Permission.AGENT_DELETE) is True

    def test_member_permissions(self):
        user = User(email="member@test.com", role=Role.MEMBER)
        assert user.has_permission(Permission.AGENT_CREATE) is True
        assert user.has_permission(Permission.AGENT_DELETE) is False

    def test_viewer_permissions(self):
        user = User(email="viewer@test.com", role=Role.VIEWER)
        assert user.has_permission(Permission.AGENT_READ) is True
        assert user.has_permission(Permission.AGENT_EXECUTE) is False

    def test_has_any_permission(self):
        user = User(email="any@test.com", role=Role.MEMBER)
        assert user.has_any_permission([Permission.AGENT_READ, Permission.ADMIN_MANAGE_USERS]) is True

    def test_has_all_permissions(self):
        user = User(email="all@test.com", role=Role.ADMIN)
        assert user.has_all_permissions([Permission.AGENT_CREATE, Permission.AGENT_READ]) is True

    def test_all_permissions_member(self):
        user = User(email="perms@test.com", role=Role.MEMBER)
        perms = user.get_all_permissions()
        assert Permission.AGENT_READ in perms
        assert Permission.AGENT_DELETE not in perms

    def test_super_admin_gets_all(self):
        user = User(email="super@test.com", role=Role.SUPER_ADMIN)
        perms = user.get_all_permissions()
        assert len(perms) == len(list(Permission))

    def test_custom_permissions(self):
        user = User(email="custom@test.com", role=Role.CUSTOM,
                     custom_permissions=[Permission.AGENT_CREATE, Permission.SANDBOX_EXECUTE])
        assert user.has_permission(Permission.AGENT_CREATE) is True
        assert user.has_permission(Permission.AGENT_READ) is False

    def test_to_public_dict(self):
        user = User(email="public@test.com", username="public_user", role=Role.MEMBER)
        d = user.to_public_dict()
        assert d["email"] == "public@test.com"
        assert "password_hash" not in d


class TestSession:
    """Test Session model."""

    def test_create_session(self):
        session = Session(user_id="usr_test", token_hash="abc123hash", expires_at=time.time() + 3600)
        assert session.id.startswith("sess_")
        assert session.is_valid is True

    def test_expired_session(self):
        session = Session(user_id="usr_expired", expires_at=time.time() - 1)
        assert session.is_expired is True
        assert session.is_valid is False

    def test_revoked_session(self):
        session = Session(user_id="usr_revoked", expires_at=9999999999)
        session.revoke()
        assert session.active is False
        assert session.is_valid is False

    def test_ttl(self):
        session = Session(user_id="usr_ttl", expires_at=time.time() + 100)
        assert session.ttl_seconds > 0

    def test_touch(self):
        session = Session(user_id="usr_touch", expires_at=9999999999)
        old = session.last_active_at
        session.touch()
        assert session.last_active_at >= old


class TestAuditEvent:
    """Test AuditEvent model."""

    def test_create_event(self):
        event = AuditEvent(event_type=EventType.LOGIN_SUCCESS, actor_id="usr_test", description="Test login")
        assert event.id.startswith("evt_")
        assert event.success is True

    def test_to_dict(self):
        event = AuditEvent(event_type=EventType.AGENT_CREATED, actor_id="usr_admin", target_id="agent_1")
        d = event.to_dict()
        assert d["event_type"] == "agent.created"
        assert d["actor_id"] == "usr_admin"


class TestAuditLog:
    """Test AuditLog recording and search."""

    def test_create(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        assert len(audit) == 0

    def test_log_event(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        event = audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="usr_abc", description="Login")
        assert event is not None
        assert len(audit) == 1

    def test_search_by_type(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="u1")
        audit.log(event_type=EventType.LOGIN_FAILED, actor_id="u2")
        assert len(audit.search(event_type=EventType.LOGIN_SUCCESS)) == 1

    def test_search_by_actor(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="alice")
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="bob")
        assert len(audit.search(actor_id="alice")) == 1

    def test_search_since(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.GENERIC, actor_id="u1")
        assert len(audit.search(since=time.time() + 86400)) == 0

    def test_search_limit(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        for i in range(10):
            audit.log(event_type=EventType.GENERIC, actor_id=f"u{i}")
        assert len(audit.search(limit=3)) == 3

    def test_search_success_filter(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="u1")
        audit.log(event_type=EventType.LOGIN_FAILED, actor_id="u2", success=False)
        assert len(audit.search(success_only=True)) == 1
        assert len(audit.search(success_only=False)) == 1

    def test_get_event_by_id(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        event = audit.log(event_type=EventType.GENERIC, actor_id="u1")
        assert audit.get_event(event.id) is not None

    def test_get_count(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="u1")
        assert audit.get_count(event_type=EventType.LOGIN_SUCCESS) == 1

    def test_get_stats(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="u1")
        audit.log(event_type=EventType.LOGIN_FAILED, actor_id="u2", success=False)
        stats = audit.get_stats()
        assert stats["total_events"] == 2
        assert stats["successful_logins"] == 1

    def test_export_json(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="u_export")
        path = audit.export_json(path=tmp_path / "audit_test.json")
        data = json.loads(Path(path).read_text())
        assert data["total_events"] == 1

    def test_clear(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        audit.log(event_type=EventType.GENERIC, actor_id="u1")
        assert len(audit) == 1
        audit.clear()
        assert len(audit) == 0

    def test_persistence(self, tmp_path):
        """AuditLog persists events to JSON in storage_path subdir."""
        storage = tmp_path / "audit_data"
        audit = AuditLog(storage_path=storage)
        audit.log(event_type=EventType.LOGIN_SUCCESS, actor_id="persist_user")
        # Force sync
        audit._save()

        # Load from same path — create new instance that reads saved data
        audit2 = AuditLog(storage_path=storage)
        assert len(audit2) > 0

    def test_repr(self, tmp_path):
        audit = AuditLog(storage_path=tmp_path)
        assert "AuditLog" in repr(audit)


class TestEventType:
    """Test EventType enum values."""

    def test_values(self):
        assert EventType.USER_CREATED.value == "user.created"
        assert EventType.LOGIN_SUCCESS.value == "auth.login_success"
        assert EventType.SANDBOX_VIOLATION.value == "sandbox.violation"
        assert EventType.GENERIC.value == "generic"


class TestRBACManager:
    """Test RBACManager."""

    def test_import_rbac(self):
        from ansiq.auth.rbac import RBACManager
        assert RBACManager is not None

    def test_create_and_auth(self, tmp_path):
        from ansiq.auth.rbac import RBACManager
        rbac = RBACManager(storage_path=tmp_path)
        rbac.create_user(email="test@rbac.com", password="pass123")
        session = rbac.authenticate(email="test@rbac.com", password="pass123")
        assert session is not None and session.is_valid

    def test_wrong_password(self, tmp_path):
        from ansiq.auth.rbac import RBACManager
        rbac = RBACManager(storage_path=tmp_path)
        rbac.create_user(email="secure@test.com", password="correct")
        assert rbac.authenticate(email="secure@test.com", password="wrong") is None

    def test_delete_user(self, tmp_path):
        from ansiq.auth.rbac import RBACManager
        rbac = RBACManager(storage_path=tmp_path)
        user = rbac.create_user(email="delete@test.com", password="pwd")
        assert rbac.delete_user(user.id) is True
        assert rbac.get_user(user.id) is None

    def test_list_users(self, tmp_path):
        from ansiq.auth.rbac import RBACManager
        rbac = RBACManager(storage_path=tmp_path)
        rbac.create_user(email="u1@test.com", password="pwd")
        rbac.create_user(email="u2@test.com", password="pwd")
        assert len(rbac.list_users()) == 2

    def test_get_stats(self, tmp_path):
        from ansiq.auth.rbac import RBACManager
        rbac = RBACManager(storage_path=tmp_path)
        rbac.create_user(email="stats@test.com", password="pwd")
        stats = rbac.get_stats()
        assert stats["users"] >= 1
