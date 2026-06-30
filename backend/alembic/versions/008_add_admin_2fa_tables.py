"""Add admin 2FA and session tables

Revision ID: 008_admin_2fa
Revises: 007_broker_display_name
Create Date: 2026-06-17 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

revision = "008_admin_2fa"
down_revision = "007_broker_display_name"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in sa_inspect(bind).get_table_names()


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)

    if not _has_table("admin_totp_secrets"):
        op.create_table(
            "admin_totp_secrets",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "user_id",
                uuid_type,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("secret_enc", sa.Text(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("backup_codes_enc", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )

    if not _has_table("admin_sessions"):
        op.create_table(
            "admin_sessions",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "user_id",
                uuid_type,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("session_token", sa.String(256), nullable=False, unique=True),
            sa.Column("totp_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(500), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_admin_sessions_session_token", "admin_sessions", ["session_token"])


def downgrade() -> None:
    if _has_table("admin_sessions"):
        op.drop_index("ix_admin_sessions_session_token", table_name="admin_sessions")
        op.drop_table("admin_sessions")
    if _has_table("admin_totp_secrets"):
        op.drop_table("admin_totp_secrets")
