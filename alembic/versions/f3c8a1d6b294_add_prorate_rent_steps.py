"""Add prorate_rent_steps (split a month at a mid-month fixed rent step) to leases

Revision ID: f3c8a1d6b294
Revises: e2b7d5a9c3f6
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "f3c8a1d6b294"
down_revision = "e2b7d5a9c3f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leases") as batch:
        batch.add_column(sa.Column("prorate_rent_steps", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("leases") as batch:
        batch.drop_column("prorate_rent_steps")
