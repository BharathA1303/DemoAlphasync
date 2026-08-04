"""Add tenant_type to tenants table and support TRADER role.

Revision ID: 017_tenant_type_trader
Revises: 016_schema_reconciliation
Create Date: 2026-08-04 16:20:00.000000

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
        pass


def downgrade() -> None:
    try:
        op.drop_column('tenants', 'tenant_type')
    except Exception:
        pass
