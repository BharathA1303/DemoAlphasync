"""Switch auth_provider default from 'firebase' to 'local' (Firebase auth removed)

Revision ID: 012_local_password_auth
Revises: 011_drop_admin_2fa_tables
Create Date: 2026-07-31 00:00:00.000000

Firebase Authentication has been fully replaced by local username/email +
password login (JWT sessions, see routes/auth.py). New users are created
with auth_provider='local'. The firebase_uid column is kept (unused,
harmless) rather than dropped, to avoid risk to any existing rows.
"""

from alembic import op
import sqlalchemy as sa

revision = "012_local_password_auth"
down_revision = "011_drop_admin_2fa_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "auth_provider",
            existing_type=sa.String(30),
            server_default=sa.text("'local'"),
        )


def downgrade() -> None:
    op.alter_column(
        "users",
        "auth_provider",
        existing_type=sa.String(30),
        server_default=sa.text("'firebase'"),
    )
