"""Recovery pools: expense lines recovered over their own share denominator

Revision ID: f2a9c4e7d1b6
Revises: c3d8f1a6b2e4
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a9c4e7d1b6"
down_revision = "c3d8f1a6b2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_pools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expense_categories", sa.JSON(), nullable=False),
        sa.Column("denominator", sa.String(20), nullable=False, server_default="property_area"),
        sa.Column("fixed_area", sa.Numeric(18, 2), nullable=True),
        sa.Column("minimum_occupancy_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("excluded_suite_ids", sa.JSON(), nullable=False),
        sa.Column("deduct_excluded_recoveries", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("recovery_pools")
