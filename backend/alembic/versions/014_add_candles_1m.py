"""Add candles_1m table for 1-minute OHLCV candle aggregation

Revision ID: 014_add_candles_1m
Revises: 013_add_zebu_oauth_and_raw_ticks
Create Date: 2026-08-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "014_candles_1m"
down_revision = "013_zebu_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candles_1m",
        sa.Column("exchange", sa.String(length=10), nullable=False),
        sa.Column("token", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("exchange", "token", "bucket_start"),
    )
    op.create_index("ix_candles_1m_sym_bucket", "candles_1m", ["symbol", "exchange", "bucket_start"])


def downgrade() -> None:
    op.drop_index("ix_candles_1m_sym_bucket", table_name="candles_1m")
    op.drop_table("candles_1m")
