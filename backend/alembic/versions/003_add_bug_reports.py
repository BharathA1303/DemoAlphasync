"""add bug_report table for user issue tracking

Revision ID: 003_add_bug_reports
Revises: 002_order_type_bracket_take_profit
Create Date: 2024-04-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_add_bug_reports'
down_revision = '002_order_type_bracket_take_profit'
branch_labels = None
depends_on = None


def upgrade():
    # Create enum for severity if using PostgreSQL
    op.create_table(
        'bug_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='medium'),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='open'),
        sa.Column('page_url', sa.String(500), nullable=True),
        sa.Column('component_name', sa.String(200), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('screenshot_url', sa.String(500), nullable=True),
        sa.Column('attachment_url', sa.String(500), nullable=True),
        sa.Column('browser', sa.String(100), nullable=True),
        sa.Column('os_info', sa.String(100), nullable=True),
        sa.Column('app_version', sa.String(50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('steps_to_reproduce', sa.Text(), nullable=True),
        sa.Column('expected_behavior', sa.Text(), nullable=True),
        sa.Column('actual_behavior', sa.Text(), nullable=True),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_user_id_status', 'bug_reports', ['user_id', 'status'])
    op.create_index('idx_status_severity', 'bug_reports', ['status', 'severity'])
    op.create_index('idx_created_at_desc', 'bug_reports', ['created_at'])
    op.create_index('idx_bug_reports_user_id', 'bug_reports', ['user_id'])
    op.create_index('idx_bug_reports_category', 'bug_reports', ['category'])
    op.create_index('idx_bug_reports_status', 'bug_reports', ['status'])


def downgrade():
    op.drop_index('idx_bug_reports_status', table_name='bug_reports')
    op.drop_index('idx_bug_reports_category', table_name='bug_reports')
    op.drop_index('idx_bug_reports_user_id', table_name='bug_reports')
    op.drop_index('idx_created_at_desc', table_name='bug_reports')
    op.drop_index('idx_status_severity', table_name='bug_reports')
    op.drop_index('idx_user_id_status', table_name='bug_reports')
    op.drop_table('bug_reports')
