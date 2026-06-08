"""Add MFA + GDPR soft-delete columns to users.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06

Adds:
  - users.mfa_enabled      (boolean, default false)
  - users.mfa_secret       (varchar 512, encrypted TOTP seed)
  - users.deleted_at       (timestamp, soft-delete)
  - users.deletion_scheduled_for (timestamp, hard-delete grace end)
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mfa_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("mfa_secret", sa.String(512), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "deletion_scheduled_for",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_deleted_at", "users", ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deletion_scheduled_for")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
