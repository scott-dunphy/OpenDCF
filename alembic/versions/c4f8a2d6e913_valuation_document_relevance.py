"""Per-valuation choice to use or skip a linked document

Revision ID: c4f8a2d6e913
Revises: b7e2c9d4f160
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "c4f8a2d6e913"
down_revision = "b7e2c9d4f160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("valuation_documents") as batch:
        batch.add_column(sa.Column("relevant_override", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("valuation_documents") as batch:
        batch.drop_column("relevant_override")
