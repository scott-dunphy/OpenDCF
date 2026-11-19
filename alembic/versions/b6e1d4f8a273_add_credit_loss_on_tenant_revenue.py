"""Add credit loss on tenant revenue option to valuations

Revision ID: b6e1d4f8a273
Revises: e2b7d5a9c3f6
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "b6e1d4f8a273"
down_revision = "e2b7d5a9c3f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column(
            "credit_loss_on_tenant_revenue", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("credit_loss_on_tenant_revenue")
