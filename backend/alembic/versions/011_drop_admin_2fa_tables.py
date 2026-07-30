"""Drop admin 2FA tables (TOTP-based admin 2FA removed)

Revision ID: 011_drop_admin_2fa_tables
Revises: 010_drop_broker_accounts
Create Date: 2026-07-06 00:00:00.000000

Admin panel access no longer requires a second TOTP factor — any user with
role='admin' can sign in and use the panel directly (see dependencies/admin.py
get_admin_user). The admin_totp_secrets and admin_sessions tables (created in
migration 008) are no longer referenced anywhere in the application and are
dropped here.
"""

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "011_drop_admin_2fa_tables"
down_revision = "010_drop_broker_accounts"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in sa_inspect(bind).get_table_names()


def upgrade() -> None:
    if _has_table("admin_sessions"):
        op.drop_index("ix_admin_sessions_session_token", table_name="admin_sessions", if_exists=True)
        op.drop_table("admin_sessions")
    if _has_table("admin_totp_secrets"):
        op.drop_table("admin_totp_secrets")


def downgrade() -> None:
    # Admin 2FA is permanently removed; the tables are not recreated.
    pass
