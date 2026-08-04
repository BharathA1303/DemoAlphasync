"""Reconcile ad-hoc database startup DDL into versioned Alembic migration.

Revision ID: 016_schema_reconciliation
Revises: 015_multi_tenant_rls
Create Date: 2026-08-04 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '016_schema_reconciliation'
down_revision = '015_multi_tenant_rls'
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users",
    "admin_audit_log",
    "email_notifications_log",
    "auth_refresh_tokens",
    "auth_impersonation_sessions",
    "academy_courses",
    "academy_modules",
    "academy_lessons",
    "academy_content_blocks",
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


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # 1. Admin hierarchy & status columns on users table
    for col_name, col_type in [
        ("account_status", sa.String(length=30)),
        ("access_expires_at", sa.DateTime(timezone=True)),
        ("access_duration_days", sa.Integer()),
        ("approved_at", sa.DateTime(timezone=True)),
        ("approved_by", sa.dialects.postgresql.UUID(as_uuid=True) if dialect == 'postgresql' else sa.CHAR(36)),
        ("deactivation_reason", sa.String(length=500)),
        ("admin_level", sa.String(length=20)),
        ("admin_assigned_by", sa.dialects.postgresql.UUID(as_uuid=True) if dialect == 'postgresql' else sa.CHAR(36)),
        ("admin_assigned_at", sa.DateTime(timezone=True)),
        ("academy_role", sa.String(length=20)),
    ]:
        try:
            op.add_column('users', sa.Column(col_name, col_type, nullable=True))
        except Exception:
            pass

    # 2. Academy courses instructor_id
    try:
        op.add_column(
            'academy_courses',
            sa.Column(
                'instructor_id',
                sa.dialects.postgresql.UUID(as_uuid=True) if dialect == 'postgresql' else sa.CHAR(36),
                nullable=True,
            ),
        )
    except Exception:
        pass

    # 3. Data feed configs oauth & broker columns
    for col_name, col_type in [
        ("oauth_base_url", sa.String(length=500)),
        ("broker_last_import_rows", sa.Integer()),
        ("broker_last_import_symbols_found", sa.Integer()),
        ("broker_last_import_symbols_total", sa.Integer()),
        ("broker_import_progress_done", sa.Integer()),
        ("broker_import_progress_total", sa.Integer()),
    ]:
        try:
            op.add_column('data_feed_configs', sa.Column(col_name, col_type, nullable=True))
        except Exception:
            pass

    # 4. PostgreSQL / SQLite RLS policy idempotency check
    if dialect == 'postgresql':
        op.execute(
            """
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
            BEGIN
                FOREACH tbl IN ARRAY tables LOOP
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
                        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
                        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', tbl);
                        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_policy ON %I;', tbl);
                        EXECUTE format('CREATE POLICY tenant_isolation_policy ON %I FOR ALL USING (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid OR NULLIF(current_setting(''app.is_super_admin'', true), '''')::boolean IS TRUE) WITH CHECK (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid OR NULLIF(current_setting(''app.is_super_admin'', true), '''')::boolean IS TRUE);', tbl);
                    END IF;
                END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    pass
