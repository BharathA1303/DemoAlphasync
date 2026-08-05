"""Add TRADER value to tenantrole enum — direct ALTER TYPE, no DO block.

Revision ID: 018_fix_trader_enum
Revises: 017_tenant_type_trader
Create Date: 2026-08-05 06:00:00.000000

IMPORTANT: ALTER TYPE ... ADD VALUE cannot be executed inside a DO $$ PL/pgSQL block
in PostgreSQL. It must run as a direct top-level statement. Migration 017 wrapped
it in DO $$ which silently did nothing, leaving 'trader' missing from the enum.
This migration fixes that by calling op.execute() directly.
"""
from alembic import op
import sqlalchemy as sa

revision = '018_fix_trader_enum'
down_revision = '017_tenant_type_trader'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != 'postgresql':
        return

    # Check if 'trader' already exists in the enum before trying to add it
    result = conn.execute(sa.text("""
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        WHERE t.typname = 'tenantrole' AND e.enumlabel = 'trader'
    """))
    already_exists = result.fetchone() is not None

    if not already_exists:
        # Must run as a direct statement — NOT inside DO $$ block
        # ALTER TYPE ... ADD VALUE is not supported inside PL/pgSQL
        conn.execute(sa.text("ALTER TYPE tenantrole ADD VALUE 'trader';"))

    # Also ensure tenant_type column exists (belt-and-suspenders)
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = 'tenants'
                  AND column_name  = 'tenant_type'
            ) THEN
                ALTER TABLE tenants ADD COLUMN tenant_type VARCHAR(20) NOT NULL DEFAULT 'institution';
            END IF;
        END $$;
    """))


def downgrade() -> None:
    pass  # PostgreSQL does not support removing enum values
