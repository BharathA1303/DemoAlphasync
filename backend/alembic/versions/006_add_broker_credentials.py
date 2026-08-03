"""Add credentials_enc column to broker_accounts

Revision ID: 006_broker_credentials
Revises: 005_futures_watchlist
Create Date: 2026-06-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision = "006_broker_credentials"
down_revision = "005_futures_watchlist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    if "broker_accounts" in insp.get_table_names():
        existing_cols = [c["name"] for c in insp.get_columns("broker_accounts")]
        if "credentials_enc" not in existing_cols:
            op.add_column(
                "broker_accounts",
                sa.Column("credentials_enc", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    if "broker_accounts" in insp.get_table_names():
        existing_cols = [c["name"] for c in insp.get_columns("broker_accounts")]
        if "credentials_enc" in existing_cols:
            op.drop_column("broker_accounts", "credentials_enc")
