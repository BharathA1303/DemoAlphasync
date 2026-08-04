"""Add tenant_type to tenants table and TRADER to TenantRole enum.

Revision ID: 017_tenant_type_trader
Revises: 016_schema_reconciliation
Create Date: 2026-08-04 16:20:00.000000

This migration is idempotent — safe to run multiple times.
Uses raw SQL DO $$ blocks to guard against column/enum already existing.
"""
from alembic import op
import sqlalchemy as sa

revision = '017_tenant_type_trader'
down_revision = '016_schema_reconciliation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == 'postgresql':
        # 1. Add tenant_type column to tenants if it doesn't already exist
        conn.execute(sa.text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name   = 'tenants'
                      AND column_name  = 'tenant_type'
                ) THEN
                    ALTER TABLE tenants
                        ADD COLUMN tenant_type VARCHAR(20) NOT NULL DEFAULT 'institution';
                END IF;
            END $$;
        """))

        # 2. Add 'trader' value to the tenantrole enum if not already present
        conn.execute(sa.text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'tenantrole'
                      AND e.enumlabel = 'trader'
                ) THEN
                    ALTER TYPE tenantrole ADD VALUE IF NOT EXISTS 'trader';
                END IF;
            END $$;
        """))
    else:
        # SQLite fallback (dev/test environments)
        try:
            op.add_column(
                'tenants',
                sa.Column(
                    'tenant_type',
                    sa.String(length=20),
                    nullable=False,
                    server_default='institution',
                ),
            )
        except Exception:
            pass  # Column already exists in SQLite


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == 'postgresql':
        conn.execute(sa.text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name   = 'tenants'
                      AND column_name  = 'tenant_type'
                ) THEN
                    ALTER TABLE tenants DROP COLUMN tenant_type;
                END IF;
            END $$;
        """))
    else:
        try:
            op.drop_column('tenants', 'tenant_type')
        except Exception:
            pass
