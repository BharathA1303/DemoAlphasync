"""Clear saved broker app credentials for all users (one-time migration)

Revision ID: 009_clear_broker_credentials
Revises: 008_admin_2fa
Create Date: 2026-06-17 00:00:00.000000

Wipes only encrypted broker credential blobs and session tokens from
broker_accounts. User accounts, portfolios, orders, and all other data
are left untouched.
"""

from alembic import op

revision = "009_clear_broker_credentials"
down_revision = "008_admin_2fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE broker_accounts
        SET
            credentials_enc = NULL,
            broker_user_id = NULL,
            display_name = NULL,
            access_token_enc = NULL,
            refresh_token_enc = NULL,
            extra_data_enc = NULL,
            is_active = false,
            token_expiry = NULL,
            last_used_at = NULL
        WHERE credentials_enc IS NOT NULL
           OR access_token_enc IS NOT NULL
           OR broker_user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Credential blobs cannot be restored once cleared.
    pass
