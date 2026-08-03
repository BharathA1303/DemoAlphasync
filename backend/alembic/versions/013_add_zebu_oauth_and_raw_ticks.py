"""Add Zebu OAuth columns, symbol_master table, raw_ticks table, and bulk_file_index table

Revision ID: 013_add_zebu_oauth_and_raw_ticks
Revises: 012_local_password_auth
Create Date: 2026-08-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone, timedelta

revision = "013_zebu_oauth"
down_revision = "012_local_password_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    # 1. New columns on data_feed_configs
    if "data_feed_configs" in tables:
        existing_cols = {c["name"] for c in insp.get_columns("data_feed_configs")}
        cols_to_add = [
            ("broker", sa.Column("broker", sa.String(length=20), nullable=True)),
            ("broker_client_code", sa.Column("broker_client_code", sa.String(length=100), nullable=True)),
            ("broker_password_enc", sa.Column("broker_password_enc", sa.Text(), nullable=True)),
            ("broker_totp_secret_enc", sa.Column("broker_totp_secret_enc", sa.Text(), nullable=True)),
            ("broker_vendor_code", sa.Column("broker_vendor_code", sa.String(length=100), nullable=True)),
            ("broker_last_import_at", sa.Column("broker_last_import_at", sa.DateTime(timezone=True), nullable=True)),
            ("broker_last_import_status", sa.Column("broker_last_import_status", sa.String(length=50), nullable=True)),
            ("broker_last_import_error", sa.Column("broker_last_import_error", sa.Text(), nullable=True)),
            ("broker_last_import_rows", sa.Column("broker_last_import_rows", sa.Integer(), nullable=True)),
            ("broker_last_import_symbols_found", sa.Column("broker_last_import_symbols_found", sa.Integer(), nullable=True)),
            ("broker_last_import_symbols_total", sa.Column("broker_last_import_symbols_total", sa.Integer(), nullable=True)),
            ("broker_import_progress_done", sa.Column("broker_import_progress_done", sa.Integer(), nullable=True)),
            ("broker_import_progress_total", sa.Column("broker_import_progress_total", sa.Integer(), nullable=True)),
            ("oauth_base_url", sa.Column("oauth_base_url", sa.String(length=500), nullable=True, server_default=sa.text("'https://go.mynt.in'"))),
            ("oauth_client_id", sa.Column("oauth_client_id", sa.String(length=100), nullable=True)),
            ("oauth_secret_key_enc", sa.Column("oauth_secret_key_enc", sa.Text(), nullable=True)),
            ("oauth_redirect_url", sa.Column("oauth_redirect_url", sa.String(length=500), nullable=True)),
            ("oauth_access_token_enc", sa.Column("oauth_access_token_enc", sa.Text(), nullable=True)),
            ("oauth_refresh_token_enc", sa.Column("oauth_refresh_token_enc", sa.Text(), nullable=True)),
            ("oauth_token_expires_at", sa.Column("oauth_token_expires_at", sa.DateTime(timezone=True), nullable=True)),
            ("oauth_connection_status", sa.Column("oauth_connection_status", sa.String(length=50), nullable=True, server_default=sa.text("'disconnected'"))),
            ("oauth_last_error", sa.Column("oauth_last_error", sa.Text(), nullable=True)),
            ("feed_delay_seconds", sa.Column("feed_delay_seconds", sa.Integer(), nullable=False, server_default=sa.text("900"))),
            ("redis_active_market_hours_only", sa.Column("redis_active_market_hours_only", sa.Boolean(), nullable=False, server_default=sa.text("true"))),
            ("broker_live_feed_enabled", sa.Column("broker_live_feed_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
        ]
        for col_name, col_obj in cols_to_add:
            if col_name not in existing_cols:
                op.add_column("data_feed_configs", col_obj)

    # 2. symbol_master table
    if "symbol_master" not in tables:
        op.create_table(
            "symbol_master",
            sa.Column("exchange", sa.String(length=10), nullable=False),
            sa.Column("token", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=50), nullable=False),
            sa.Column("trading_symbol", sa.String(length=100), nullable=False),
            sa.Column("instrument_type", sa.String(length=20), nullable=False),
            sa.Column("lot_size", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("tick_size", sa.Numeric(precision=10, scale=4), nullable=False, server_default=sa.text("0.05")),
            sa.Column("expiry", sa.Date(), nullable=True),
            sa.Column("strike", sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column("option_type", sa.String(length=2), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("exchange", "token"),
        )
        op.create_index("ix_symbol_master_symbol", "symbol_master", ["symbol", "exchange"])
        op.create_index("ix_symbol_master_active", "symbol_master", ["is_active"])
        op.create_index("ix_symbol_master_trading_symbol", "symbol_master", ["trading_symbol"])

    # 3. bulk_file_index table
    if "bulk_file_index" not in tables:
        op.create_table(
            "bulk_file_index",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("exchange", sa.String(length=10), nullable=False),
            sa.Column("segment", sa.String(length=20), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("start_ts", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_ts", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_bulk_file_index_ex_date", "bulk_file_index", ["exchange", "segment", "date"])

    # 4. raw_ticks table (RANGE Partitioned by real_timestamp)
    if "raw_ticks" in tables:
        relkind = bind.execute(sa.text("SELECT relkind FROM pg_class WHERE relname = 'raw_ticks'")).scalar()
        if relkind != 'p':
            op.execute("DROP TABLE IF EXISTS raw_ticks CASCADE;")

    if "raw_ticks" not in sa.inspect(bind).get_table_names():
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_ticks (
                id              BIGSERIAL,
                exchange        VARCHAR(10) NOT NULL,
                token           VARCHAR(20) NOT NULL,
                symbol          VARCHAR(50) NOT NULL,
                ltp             NUMERIC(12,4) NOT NULL,
                open            NUMERIC(12,4),
                high            NUMERIC(12,4),
                low             NUMERIC(12,4),
                close           NUMERIC(12,4),
                volume          BIGINT,
                best_bid        NUMERIC(12,4),
                best_ask        NUMERIC(12,4),
                real_timestamp  TIMESTAMPTZ NOT NULL,
                ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (id, real_timestamp)
            ) PARTITION BY RANGE (real_timestamp);
            """
        )

    # Initial migration-time partitions (today, tomorrow, and subsequent day)
    now_utc = datetime.now(timezone.utc)
    for i in range(-1, 3):
        p_date = (now_utc + timedelta(days=i)).date()
        p_name = f"raw_ticks_{p_date.strftime('%Y_%m_%d')}"
        start_ts = f"{p_date.strftime('%Y-%m-%d')} 00:00:00+00"
        end_ts = f"{(p_date + timedelta(days=1)).strftime('%Y-%m-%d')} 00:00:00+00"
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {p_name} PARTITION OF raw_ticks
            FOR VALUES FROM ('{start_ts}') TO ('{end_ts}');
            """
        )
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS ix_{p_name}_ex_tok_ts ON {p_name} (exchange, token, real_timestamp DESC);
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw_ticks CASCADE;")
    op.drop_index("ix_bulk_file_index_ex_date", table_name="bulk_file_index")
    op.drop_table("bulk_file_index")
    op.drop_index("ix_symbol_master_trading_symbol", table_name="symbol_master")
    op.drop_index("ix_symbol_master_active", table_name="symbol_master")
    op.drop_index("ix_symbol_master_symbol", table_name="symbol_master")
    op.drop_table("symbol_master")

    op.drop_column("data_feed_configs", "broker_live_feed_enabled")
    op.drop_column("data_feed_configs", "redis_active_market_hours_only")
    op.drop_column("data_feed_configs", "feed_delay_seconds")
    op.drop_column("data_feed_configs", "oauth_last_error")
    op.drop_column("data_feed_configs", "oauth_connection_status")
    op.drop_column("data_feed_configs", "oauth_token_expires_at")
    op.drop_column("data_feed_configs", "oauth_refresh_token_enc")
    op.drop_column("data_feed_configs", "oauth_access_token_enc")
    op.drop_column("data_feed_configs", "oauth_redirect_url")
    op.drop_column("data_feed_configs", "oauth_secret_key_enc")
    op.drop_column("data_feed_configs", "oauth_client_id")
    op.drop_column("data_feed_configs", "oauth_base_url")
