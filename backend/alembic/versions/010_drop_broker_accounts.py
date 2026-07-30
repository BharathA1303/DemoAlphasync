"""Drop broker_accounts table (broker integrations fully removed)

Revision ID: 010_drop_broker_accounts
Revises: 009_clear_broker_credentials
Create Date: 2026-07-05 00:00:00.000000

DemoAlphasync no longer supports per-user broker connections of any kind.
Market data is now supplied exclusively by the internal simulation engine data feed layer,
configured once by an admin (see data_feed_configs table). The
broker_accounts table (and its already-wiped credential columns, see
migration 009) is no longer referenced anywhere in the application and is
dropped here.
"""

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "010_drop_broker_accounts"
down_revision = "009_clear_broker_credentials"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in sa_inspect(bind).get_table_names()


def upgrade() -> None:
    if _has_table("broker_accounts"):
        op.drop_table("broker_accounts")


def downgrade() -> None:
    # Broker integration is permanently removed; the table is not recreated.
    pass
