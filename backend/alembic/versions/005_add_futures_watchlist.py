"""Add FuturesWatchlist and FuturesWatchlistItem tables

Revision ID: 005_futures_watchlist
Revises: 004_add_user_feedback
Create Date: 2025-01-01 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision = "005_futures_watchlist"
down_revision = "004_add_user_feedback"
branch_labels = None
depends_on = None


def _has_table(table_name):
    """Check if a table exists (idempotent migrations)."""
    bind = op.get_bind()
    insp = sa_inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    # Create futures_watchlists table
    if not _has_table("futures_watchlists"):
        op.create_table(
            "futures_watchlists",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(100), nullable=False, server_default=sa.text("'My Futures Watchlist'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.Index("ix_futures_watchlists_user_id", "user_id"),
        )

    # Create futures_watchlist_items table
    if not _has_table("futures_watchlist_items"):
        op.create_table(
            "futures_watchlist_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("watchlist_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("contract_symbol", sa.String(50), nullable=False),
            sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["watchlist_id"], ["futures_watchlists.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.Index("ix_futures_watchlist_items_watchlist_id", "watchlist_id"),
            sa.Index("ix_futures_watchlist_items_unique", "watchlist_id", "contract_symbol", unique=True),
        )


def downgrade() -> None:
    op.drop_index("ix_futures_watchlist_items_unique", table_name="futures_watchlist_items")
    op.drop_index("ix_futures_watchlist_items_watchlist_id", table_name="futures_watchlist_items")
    op.drop_table("futures_watchlist_items")

    op.drop_index("ix_futures_watchlists_user_id", table_name="futures_watchlists")
    op.drop_table("futures_watchlists")
