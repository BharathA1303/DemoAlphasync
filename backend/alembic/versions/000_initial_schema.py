"""Initial schema: create all base tables from SQLAlchemy metadata.

This migration is the root of the chain (down_revision = None).
It uses Base.metadata.create_all so that every subsequent migration
(001 onwards) can safely assume the tables already exist.

Revision ID: 000_initial_schema
Revises:
Create Date: 2026-08-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = "000_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Enable uuid-ossp so gen_random_uuid() works
    bind.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

    # ── tenants ────────────────────────────────────────────────────────────────
    if not _table_exists(bind, "tenants"):
        op.create_table(
            "tenants",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("slug", sa.String(100), nullable=False, unique=True),
            sa.Column("domain", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False,
                      server_default=sa.text("true")),
            sa.Column("max_users", sa.Integer, nullable=True,
                      server_default=sa.text("1000")),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── users ──────────────────────────────────────────────────────────────────
    if not _table_exists(bind, "users"):
        op.create_table(
            "users",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("firebase_uid", sa.String(128), unique=True, nullable=True),
            sa.Column("auth_provider", sa.String(30), nullable=False,
                      server_default=sa.text("'local'")),
            sa.Column("email", sa.String(255), unique=True, nullable=False),
            sa.Column("username", sa.String(50), unique=True, nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=True),
            sa.Column("full_name", sa.String(100), nullable=False),
            sa.Column("is_verified", sa.Boolean, nullable=False,
                      server_default=sa.text("false")),
            sa.Column("is_active", sa.Boolean, nullable=False,
                      server_default=sa.text("true")),
            sa.Column("virtual_capital", sa.Numeric(16, 2), nullable=False,
                      server_default=sa.text("1000000.0")),
            sa.Column("role", sa.String(20), nullable=False,
                      server_default=sa.text("'user'")),
            sa.Column("avatar_url", sa.String(500), nullable=True),
            sa.Column("phone", sa.String(20), nullable=True),
            sa.Column("academy_role", sa.String(20), nullable=True,
                      server_default=sa.text("'student'")),
            sa.Column("admin_level", sa.String(20), nullable=True),
            sa.Column("admin_assigned_by", UUID(as_uuid=True),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("admin_assigned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("account_status", sa.String(30), nullable=False,
                      server_default=sa.text("'pending_approval'")),
            sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("access_duration_days", sa.Integer, nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approved_by", UUID(as_uuid=True),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("deactivation_reason", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_index("ix_users_username", "users", ["username"], unique=True)
        op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"], unique=True)
        op.create_index("ix_users_role_active", "users", ["role", "is_active"])
        op.create_index("ix_users_account_status", "users", ["account_status"])

    # ── user_tenant_roles ──────────────────────────────────────────────────────
    if not _table_exists(bind, "user_tenant_roles"):
        op.create_table(
            "user_tenant_roles",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("role", sa.String(50), nullable=False,
                      server_default=sa.text("'student'")),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── portfolios ─────────────────────────────────────────────────────────────
    if not _table_exists(bind, "portfolios"):
        op.create_table(
            "portfolios",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, unique=True),
            sa.Column("cash_balance", sa.Numeric(16, 2), nullable=False,
                      server_default=sa.text("1000000.0")),
            sa.Column("total_invested", sa.Numeric(16, 2), nullable=False,
                      server_default=sa.text("0")),
            sa.Column("realized_pnl", sa.Numeric(16, 2), nullable=False,
                      server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── holdings ───────────────────────────────────────────────────────────────
    if not _table_exists(bind, "holdings"):
        op.create_table(
            "holdings",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("portfolio_id", UUID(as_uuid=True),
                      sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("symbol", sa.String(30), nullable=False),
            sa.Column("exchange", sa.String(10), nullable=False,
                      server_default=sa.text("'NSE'")),
            sa.Column("quantity", sa.Integer, nullable=False,
                      server_default=sa.text("0")),
            sa.Column("average_price", sa.Numeric(14, 2), nullable=False,
                      server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── transactions ───────────────────────────────────────────────────────────
    if not _table_exists(bind, "transactions"):
        op.create_table(
            "transactions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("portfolio_id", UUID(as_uuid=True),
                      sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("type", sa.String(20), nullable=False),
            sa.Column("amount", sa.Numeric(16, 2), nullable=False),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── orders ─────────────────────────────────────────────────────────────────
    if not _table_exists(bind, "orders"):
        op.create_table(
            "orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("symbol", sa.String(30), nullable=False),
            sa.Column("exchange", sa.String(10), nullable=False,
                      server_default=sa.text("'NSE'")),
            sa.Column("order_type", sa.String(20), nullable=False),
            sa.Column("side", sa.String(4), nullable=False),
            sa.Column("product_type", sa.String(10), nullable=False,
                      server_default=sa.text("'CNC'")),
            sa.Column("quantity", sa.Integer, nullable=False),
            sa.Column("price", sa.Numeric(14, 2), nullable=True),
            sa.Column("trigger_price", sa.Numeric(14, 2), nullable=True),
            sa.Column("target_price", sa.Numeric(14, 2), nullable=True),
            sa.Column("stop_loss_price", sa.Numeric(14, 2), nullable=True),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default=sa.text("'PENDING'")),
            sa.Column("filled_quantity", sa.Integer, nullable=False,
                      server_default=sa.text("0")),
            sa.Column("filled_price", sa.Numeric(14, 2), nullable=True),
            sa.Column("rejection_reason", sa.String(500), nullable=True),
            sa.Column("tag", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── watchlists ─────────────────────────────────────────────────────────────
    if not _table_exists(bind, "watchlists"):
        op.create_table(
            "watchlists",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── watchlist_items ────────────────────────────────────────────────────────
    if not _table_exists(bind, "watchlist_items"):
        op.create_table(
            "watchlist_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("watchlist_id", UUID(as_uuid=True),
                      sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("symbol", sa.String(30), nullable=False),
            sa.Column("exchange", sa.String(10), nullable=False,
                      server_default=sa.text("'NSE'")),
            sa.Column("added_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── algo_strategies ────────────────────────────────────────────────────────
    if not _table_exists(bind, "algo_strategies"):
        op.create_table(
            "algo_strategies",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("strategy_type", sa.String(50), nullable=False),
            sa.Column("config", JSONB, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False,
                      server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── admin_audit_log ────────────────────────────────────────────────────────
    if not _table_exists(bind, "admin_audit_log"):
        op.create_table(
            "admin_audit_log",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("admin_user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("target_user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("details", JSONB, nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── email_notifications_log ────────────────────────────────────────────────
    if not _table_exists(bind, "email_notifications_log"):
        op.create_table(
            "email_notifications_log",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("email_type", sa.String(50), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default=sa.text("'pending'")),
            sa.Column("error_message", sa.Text, nullable=True),
        )

    # ── futures_orders ─────────────────────────────────────────────────────────
    if not _table_exists(bind, "futures_orders"):
        op.create_table(
            "futures_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("symbol", sa.String(30), nullable=False),
            sa.Column("exchange", sa.String(10), nullable=False,
                      server_default=sa.text("'NSE'")),
            sa.Column("order_type", sa.String(20), nullable=False),
            sa.Column("side", sa.String(4), nullable=False),
            sa.Column("quantity", sa.Integer, nullable=False),
            sa.Column("price", sa.Numeric(14, 2), nullable=True),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default=sa.text("'PENDING'")),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── futures_watchlists ─────────────────────────────────────────────────────
    if not _table_exists(bind, "futures_watchlists"):
        op.create_table(
            "futures_watchlists",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── futures_watchlist_items ────────────────────────────────────────────────
    if not _table_exists(bind, "futures_watchlist_items"):
        op.create_table(
            "futures_watchlist_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("watchlist_id", UUID(as_uuid=True),
                      sa.ForeignKey("futures_watchlists.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("symbol", sa.String(30), nullable=False),
            sa.Column("exchange", sa.String(10), nullable=False,
                      server_default=sa.text("'NSE'")),
            sa.Column("added_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── data_feed_configs ──────────────────────────────────────────────────────
    if not _table_exists(bind, "data_feed_configs"):
        op.create_table(
            "data_feed_configs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("provider", sa.String(50), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False,
                      server_default=sa.text("false")),
            sa.Column("config_json", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── symbol_master ──────────────────────────────────────────────────────────
    if not _table_exists(bind, "symbol_master"):
        op.create_table(
            "symbol_master",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("exchange", sa.String(10), nullable=False),
            sa.Column("token", sa.String(20), nullable=False),
            sa.Column("symbol", sa.String(50), nullable=False),
            sa.Column("name", sa.String(200), nullable=True),
            sa.Column("instrument_type", sa.String(20), nullable=True),
            sa.Column("lot_size", sa.Integer, nullable=True),
            sa.Column("tick_size", sa.Numeric(10, 4), nullable=True),
            sa.Column("expiry", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── raw_ticks ──────────────────────────────────────────────────────────────
    if not _table_exists(bind, "raw_ticks"):
        op.create_table(
            "raw_ticks",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("exchange", sa.String(10), nullable=False),
            sa.Column("token", sa.String(20), nullable=False),
            sa.Column("symbol", sa.String(50), nullable=True),
            sa.Column("ltp", sa.Numeric(12, 4), nullable=True),
            sa.Column("volume", sa.BigInteger, nullable=True),
            sa.Column("bid", sa.Numeric(12, 4), nullable=True),
            sa.Column("ask", sa.Numeric(12, 4), nullable=True),
            sa.Column("open", sa.Numeric(12, 4), nullable=True),
            sa.Column("high", sa.Numeric(12, 4), nullable=True),
            sa.Column("low", sa.Numeric(12, 4), nullable=True),
            sa.Column("close", sa.Numeric(12, 4), nullable=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True),
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── candles_1m ─────────────────────────────────────────────────────────────
    if not _table_exists(bind, "candles_1m"):
        op.create_table(
            "candles_1m",
            sa.Column("exchange", sa.String(10), nullable=False),
            sa.Column("token", sa.String(20), nullable=False),
            sa.Column("symbol", sa.String(50), nullable=False),
            sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("open", sa.Numeric(12, 4), nullable=False),
            sa.Column("high", sa.Numeric(12, 4), nullable=False),
            sa.Column("low", sa.Numeric(12, 4), nullable=False),
            sa.Column("close", sa.Numeric(12, 4), nullable=False),
            sa.Column("volume", sa.BigInteger, nullable=False,
                      server_default=sa.text("0")),
            sa.PrimaryKeyConstraint("exchange", "token", "bucket_start"),
        )
        op.create_index("ix_candles_1m_sym_bucket", "candles_1m",
                        ["symbol", "exchange", "bucket_start"])


def downgrade() -> None:
    # Drop in reverse dependency order
    for tbl in [
        "candles_1m", "raw_ticks", "symbol_master", "data_feed_configs",
        "futures_watchlist_items", "futures_watchlists", "futures_orders",
        "email_notifications_log", "admin_audit_log", "algo_strategies",
        "watchlist_items", "watchlists", "orders",
        "transactions", "holdings", "portfolios",
        "user_tenant_roles", "users", "tenants",
    ]:
        op.drop_table(tbl)


# ── helper ─────────────────────────────────────────────────────────────────────
def _table_exists(bind, table_name: str) -> bool:
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()
