"""Add recoverable % to per-category recovery overrides and recovery structure items

Revision ID: f3c8a1d6b2e4
Revises: b6e1d4f8a273
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "f3c8a1d6b2e4"
down_revision = "b6e1d4f8a273"
branch_labels = None
depends_on = None

TABLES = ("lease_expense_recoveries", "recovery_structure_items")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("recoverable_pct", sa.Numeric(10, 6), nullable=False, server_default="1"))


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("recoverable_pct")
