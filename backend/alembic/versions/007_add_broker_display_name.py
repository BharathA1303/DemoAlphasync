"""Add display_name column to broker_accounts

Revision ID: 007_broker_display_name
Revises: 006_broker_credentials
Create Date: 2026-06-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision = "007_broker_display_name"
down_revision = "006_broker_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    if "broker_accounts" in insp.get_table_names():
        existing_cols = [c["name"] for c in insp.get_columns("broker_accounts")]
        if "display_name" not in existing_cols:
            op.add_column(
                "broker_accounts",
                sa.Column("display_name", sa.String(100), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa_inspect(bind)
    if "broker_accounts" in insp.get_table_names():
        existing_cols = [c["name"] for c in insp.get_columns("broker_accounts")]
        if "display_name" in existing_cols:
            op.drop_column("broker_accounts", "display_name")
