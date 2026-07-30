"""
Add take-profit storage and expand supported order types.

Revision ID: 002_order_type_bracket_take_profit
Revises: 001_firebase_auth
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision = "002_order_type_bracket_take_profit"
down_revision = "001_firebase_auth"
branch_labels = None
depends_on = None


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa_inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def _has_check_constraint(table, constraint_name):
    bind = op.get_bind()
    insp = sa_inspect(bind)
    return any(
        c.get("name") == constraint_name for c in insp.get_check_constraints(table)
    )


def upgrade() -> None:
    if not _has_column("orders", "take_profit_price"):
        op.add_column(
            "orders",
            sa.Column(
                "take_profit_price", sa.Numeric(precision=14, scale=2), nullable=True
            ),
        )

    if _has_check_constraint("orders", "ck_order_type"):
        op.drop_constraint("ck_order_type", "orders", type_="check")

    op.create_check_constraint(
        "ck_order_type",
        "orders",
        "order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS', 'TAKE_PROFIT', 'BRACKET', 'STOP_LOSS_LIMIT')",
    )


def downgrade() -> None:
    if _has_check_constraint("orders", "ck_order_type"):
        op.drop_constraint("ck_order_type", "orders", type_="check")

    op.create_check_constraint(
        "ck_order_type",
        "orders",
        "order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT')",
    )

    if _has_column("orders", "take_profit_price"):
        op.drop_column("orders", "take_profit_price")
