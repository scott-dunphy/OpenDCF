"""Add round_start_to_month (market lease starts after downtime move to the 1st) to market leasing profiles

Revision ID: b8e3f1a6d742
Revises: e2b7d5a9c3f6
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e3f1a6d742"
down_revision = "e2b7d5a9c3f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("round_start_to_month", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("round_start_to_month")
