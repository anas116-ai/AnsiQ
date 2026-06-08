"""Authentication & RBAC — secure multi-user access control.

Provides:
- User management with roles and permissions
- Role-based access control (admin, user, viewer)
- Session management with JWT tokens
- SSO provider abstractions (Google, GitHub, Microsoft)
- Audit logging for all actions
"""

from ansiq.auth.audit import AuditEvent, AuditLog
from ansiq.auth.models import Permission, Role, Session, User
from ansiq.auth.rbac import AccessDenied, RBACManager

__all__ = [
    "User",
    "Role",
    "Permission",
    "Session",
    "RBACManager",
    "AccessDenied",
    "AuditLog",
    "AuditEvent",
]
