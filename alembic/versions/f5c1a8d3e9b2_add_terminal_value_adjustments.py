"""Add terminal value adjustments: free rent addback / deduction, forward TI/LC, exit costs on adjusted gross

Revision ID: f5c1a8d3e9b2
Revises: e2b7d5a9c3f6
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "f5c1a8d3e9b2"
down_revision = "e2b7d5a9c3f6"
branch_labels = None
depends_on = None

COLUMNS = (
    "exit_add_back_free_rent",
    "exit_deduct_forward_free_rent",
    "exit_deduct_forward_leasing_costs",
    "exit_costs_on_adjusted_gross",
)


def upgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        for name in reversed(COLUMNS):
            batch.drop_column(name)
