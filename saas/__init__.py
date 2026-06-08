"""AnsiQ SaaS — Production-ready multi-tenant SaaS infrastructure.

This package provides the complete backend for running AnsiQ as a SaaS product:
- PostgreSQL database models + Alembic migrations
- User management (registration, auth, email verification, password reset)
- Subscription & billing (Stripe integration)
- Multi-tenant isolation
- Webhook system
- Email service (SMTP / SendGrid / SES)
- API key management
- Usage metering & billing
- Prometheus metrics
- Admin API
- Health checks & readiness probes
"""

from __future__ import annotations

__version__ = "0.1.0"
