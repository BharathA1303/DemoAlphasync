"""Fix tenantrole enum: add missing TRADER value AND convert role column to VARCHAR.

Revision ID: 019_fix_tenantrole_varchar
Revises: 018_fix_trader_enum
Create Date: 2026-08-05 06:05:00.000000

Two-part fix:
1. Add TRADER (uppercase, matching SQLAlchemy enum name storage) to the native
   PostgreSQL tenantrole enum — migrations 017/018 wrongly added lowercase 'trader'.
2. Alter the user_tenant_roles.role column from native enum type to VARCHAR(50)
   so future TenantRole additions never need a migration again.
"""
from alembic import op
import sqlalchemy as sa

revision = '019_fix_tenantrole_varchar'
down_revision = '018_fix_trader_enum'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != 'postgresql':
        return

    # Step 1: Add uppercase TRADER to the native enum if missing
    # (SQLAlchemy stores Python enum *names* — uppercase — in PostgreSQL)
    result = conn.execute(sa.text("""
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        WHERE t.typname = 'tenantrole' AND e.enumlabel = 'TRADER'
    """))
    trader_upper_missing = result.fetchone() is None

    if trader_upper_missing:
        # Must be a direct statement — not inside DO $$ block
        conn.execute(sa.text("ALTER TYPE tenantrole ADD VALUE IF NOT EXISTS 'TRADER';"))

    # Step 2: Convert role column to VARCHAR(50) so adding new enum values
    # never requires a migration again. Keep existing data intact.
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'user_tenant_roles' AND column_name = 'role'
                  AND data_type = 'USER-DEFINED'
            ) THEN
                ALTER TABLE user_tenant_roles
                    ALTER COLUMN role TYPE VARCHAR(50)
                    USING role::text;
            END IF;
        END $$;
    """))

    # Step 3: Drop the old native enum type if nothing else references it
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_attribute a
                JOIN pg_class c ON a.attrelid = c.oid
                JOIN pg_type t ON a.atttypid = t.oid
                WHERE t.typname = 'tenantrole' AND a.attnum > 0
            ) THEN
                DROP TYPE IF EXISTS tenantrole;
            END IF;
        END $$;
    """))


def downgrade() -> None:
    pass  # Cannot safely restore native enum from VARCHAR
