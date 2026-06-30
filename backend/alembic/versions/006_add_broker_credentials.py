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


def _has_column(table_name, column_name):
    bind = op.get_bind()
    insp = sa_inspect(bind)
    return column_name in [c["name"] for c in insp.get_columns(table_name)]


def upgrade() -> None:
    if not _has_column("broker_accounts", "credentials_enc"):
        op.add_column(
            "broker_accounts",
            sa.Column("credentials_enc", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("broker_accounts", "credentials_enc"):
        op.drop_column("broker_accounts", "credentials_enc")
