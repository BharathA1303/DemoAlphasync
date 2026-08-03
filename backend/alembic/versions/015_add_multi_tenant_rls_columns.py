"""Add multi-tenant RLS tables and tenant_id columns to all domain tables.

Revision ID: 015
Revises: 014
Create Date: 2026-08-03 17:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users",
    "admin_audit_log",
    "email_notifications_log",
    "academy_courses",
    "academy_enrollments",
    "academy_lesson_progress",
    "academy_study_activity",
    "academy_quiz_attempts",
    "academy_skill_mastery",
    "academy_teacher_student_assignments",
    "academy_challenges",
    "academy_student_challenge_progress",
    "orders",
    "portfolios",
    "holdings",
    "transactions",
    "watchlists",
    "watchlist_items",
    "futures_orders",
    "futures_watchlists",
    "futures_watchlist_items",
    "algo_strategies",
]


def upgrade():
    # 1. Create tenants table if not existing
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(200) NOT NULL,
            slug VARCHAR(100) UNIQUE NOT NULL,
            domain VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            max_users INTEGER DEFAULT 1000,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Create user_tenant_roles table if not existing
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_tenant_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(50) NOT NULL DEFAULT 'student',
            assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Add tenant_id column to all domain tables safely in PL/pgSQL
    op.execute("""
        DO $$ 
        DECLARE
            tbl text;
            tables text[] := ARRAY[
                'users', 'admin_audit_log', 'email_notifications_log', 'academy_courses',
                'academy_enrollments', 'academy_lesson_progress', 'academy_study_activity',
                'academy_quiz_attempts', 'academy_skill_mastery', 'academy_teacher_student_assignments',
                'academy_challenges', 'academy_student_challenge_progress', 'orders', 'portfolios',
                'holdings', 'transactions', 'watchlists', 'watchlist_items', 'futures_orders',
                'futures_watchlists', 'futures_watchlist_items', 'algo_strategies'
            ];
        BEGIN
            FOREACH tbl IN ARRAY tables LOOP
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
                    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;', tbl);
                END IF;
            END LOOP;
        END $$;
    """)

    # 4. Add user management / admin columns to users table
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users') THEN
                ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status VARCHAR(30) NOT NULL DEFAULT 'active';
                ALTER TABLE users ADD COLUMN IF NOT EXISTS access_expires_at TIMESTAMPTZ;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS access_duration_days INTEGER;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_by UUID;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivation_reason VARCHAR(500);
                ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_level VARCHAR(20);
                ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_assigned_by UUID;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_assigned_at TIMESTAMPTZ;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS academy_role VARCHAR(20) DEFAULT 'student';
            END IF;
        END $$;
    """)

    # 5. Enable RLS and FORCE RLS on all tables
    op.execute("""
        DO $$ 
        DECLARE
            tbl text;
            tables text[] := ARRAY[
                'users', 'admin_audit_log', 'email_notifications_log', 'academy_courses',
                'academy_enrollments', 'academy_lesson_progress', 'academy_study_activity',
                'academy_quiz_attempts', 'academy_skill_mastery', 'academy_teacher_student_assignments',
                'academy_challenges', 'academy_student_challenge_progress', 'orders', 'portfolios',
                'holdings', 'transactions', 'watchlists', 'watchlist_items', 'futures_orders',
                'futures_watchlists', 'futures_watchlist_items', 'algo_strategies'
            ];
        BEGIN
            FOREACH tbl IN ARRAY tables LOOP
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
                    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
                    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', tbl);
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies WHERE tablename = tbl AND policyname = 'tenant_isolation_policy'
                    ) THEN
                        EXECUTE format('CREATE POLICY tenant_isolation_policy ON %I FOR ALL USING (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid);', tbl);
                    END IF;
                END IF;
            END LOOP;
        END $$;
    """)


def downgrade():
    for tbl in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS tenant_id;")

    op.execute("DROP TABLE IF EXISTS user_tenant_roles;")
    op.execute("DROP TABLE IF EXISTS tenants;")
