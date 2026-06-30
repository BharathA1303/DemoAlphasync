"""add user_feedback table for session feedback

Revision ID: 004_add_user_feedback
Revises: 003_add_bug_reports
Create Date: 2026-04-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_add_user_feedback'
down_revision = '003_add_bug_reports'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'user_feedback' not in inspector.get_table_names():
        op.create_table(
            'user_feedback',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )

    if 'user_feedback' in inspector.get_table_names():
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('user_feedback')}
        if 'idx_user_feedback_user_id' not in existing_indexes:
            op.create_index('idx_user_feedback_user_id', 'user_feedback', ['user_id'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'user_feedback' in inspector.get_table_names():
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('user_feedback')}
        if 'idx_user_feedback_user_id' in existing_indexes:
            op.drop_index('idx_user_feedback_user_id', table_name='user_feedback')
        op.drop_table('user_feedback')