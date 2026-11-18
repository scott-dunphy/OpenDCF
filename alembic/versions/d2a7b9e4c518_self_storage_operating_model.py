"""Self storage operating model on the property

Revision ID: d2a7b9e4c518
Revises: c4f8a2d6e913
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "d2a7b9e4c518"
down_revision = "c4f8a2d6e913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("self_storage_assumptions_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("self_storage_assumptions_json")
