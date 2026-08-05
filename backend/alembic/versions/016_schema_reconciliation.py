"""Reconcile ad-hoc database startup DDL into versioned Alembic migration.

Revision ID: 016_schema_reconciliation
Revises: 015_multi_tenant_rls
Create Date: 2026-08-04 16:10:00.000000

All column additions use DO $$ IF NOT EXISTS $$ blocks so they never throw
an error when the column already exists, preventing transaction abort.
RLS policies use single-quoted EXECUTE format() strings (no $fmt$ quoting)
to avoid asyncpg mis-interpreting custom dollar-quote delimiters as bind params.
"""
from alembic import op
import sqlalchemy as sa

revision = '016_schema_reconciliation'
down_revision = '015_multi_tenant_rls'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect != 'postgresql':
        return  # SQLite handled by init_db self-heal

    # 1. Admin hierarchy & status columns on users table
    # Uses IF NOT EXISTS inside DO block — never raises an exception, never aborts transaction
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='account_status') THEN
                ALTER TABLE users ADD COLUMN account_status VARCHAR(30);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='access_expires_at') THEN
                ALTER TABLE users ADD COLUMN access_expires_at TIMESTAMPTZ;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='access_duration_days') THEN
                ALTER TABLE users ADD COLUMN access_duration_days INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='approved_at') THEN
                ALTER TABLE users ADD COLUMN approved_at TIMESTAMPTZ;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='approved_by') THEN
                ALTER TABLE users ADD COLUMN approved_by UUID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='deactivation_reason') THEN
                ALTER TABLE users ADD COLUMN deactivation_reason VARCHAR(500);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='admin_level') THEN
                ALTER TABLE users ADD COLUMN admin_level VARCHAR(20);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='admin_assigned_by') THEN
                ALTER TABLE users ADD COLUMN admin_assigned_by UUID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='admin_assigned_at') THEN
                ALTER TABLE users ADD COLUMN admin_assigned_at TIMESTAMPTZ;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='academy_role') THEN
                ALTER TABLE users ADD COLUMN academy_role VARCHAR(20);
            END IF;
        END $$;
    """))

    # 2. Academy courses instructor_id
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='academy_courses') THEN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='academy_courses' AND column_name='instructor_id') THEN
                    ALTER TABLE academy_courses ADD COLUMN instructor_id UUID;
                END IF;
            END IF;
        END $$;
    """))

    # 3. Data feed configs oauth & broker columns
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='data_feed_configs') THEN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='data_feed_configs' AND column_name='oauth_base_url') THEN
                    ALTER TABLE data_feed_configs ADD COLUMN oauth_base_url VARCHAR(500);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='data_feed_configs' AND column_name='broker_last_import_rows') THEN
                    ALTER TABLE data_feed_configs ADD COLUMN broker_last_import_rows INTEGER;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='data_feed_configs' AND column_name='broker_last_import_symbols_found') THEN
                    ALTER TABLE data_feed_configs ADD COLUMN broker_last_import_symbols_found INTEGER;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='data_feed_configs' AND column_name='broker_last_import_symbols_total') THEN
                    ALTER TABLE data_feed_configs ADD COLUMN broker_last_import_symbols_total INTEGER;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='data_feed_configs' AND column_name='broker_import_progress_done') THEN
                    ALTER TABLE data_feed_configs ADD COLUMN broker_import_progress_done INTEGER;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='data_feed_configs' AND column_name='broker_import_progress_total') THEN
                    ALTER TABLE data_feed_configs ADD COLUMN broker_import_progress_total INTEGER;
                END IF;
            END IF;
        END $$;
    """))

    # 4. RLS policy idempotency — IMPORTANT: use single-quoted strings only inside format()
    # DO NOT use $fmt$...$fmt$ custom dollar-quote delimiters — asyncpg misinterprets $fmt as a bind param
    conn.execute(sa.text("""
        DO $$
        DECLARE
            tbl text;
            tables text[] := ARRAY[
                'users', 'admin_audit_log', 'email_notifications_log', 'auth_refresh_tokens',
                'auth_impersonation_sessions', 'academy_courses', 'academy_modules', 'academy_lessons',
                'academy_content_blocks', 'academy_enrollments', 'academy_lesson_progress', 'academy_study_activity',
                'academy_quiz_attempts', 'academy_skill_mastery', 'academy_teacher_student_assignments',
                'academy_challenges', 'academy_student_challenge_progress', 'orders', 'portfolios',
                'holdings', 'transactions', 'watchlists', 'watchlist_items', 'futures_orders',
                'futures_watchlists', 'futures_watchlist_items', 'algo_strategies'
            ];
            policy_sql text;
        BEGIN
            FOREACH tbl IN ARRAY tables LOOP
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
                    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
                    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', tbl);
                    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_policy ON %I;', tbl);
                    policy_sql := format(
                        'CREATE POLICY tenant_isolation_policy ON %I FOR ALL '
                        'USING ('
                        '    tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid '
                        '    OR NULLIF(current_setting(''app.is_super_admin'', true), '''')::boolean IS TRUE'
                        ') WITH CHECK ('
                        '    tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid '
                        '    OR NULLIF(current_setting(''app.is_super_admin'', true), '''')::boolean IS TRUE'
                        ');',
                        tbl
                    );
                    EXECUTE policy_sql;
                END IF;
            END LOOP;
        END $$;
    """))


def downgrade() -> None:
    pass
