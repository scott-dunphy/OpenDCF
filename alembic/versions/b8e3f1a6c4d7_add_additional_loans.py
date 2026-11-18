"""Add additional loans to valuations

Revision ID: b8e3f1a6c4d7
Revises: c5d1e8a7b9f2
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e3f1a6c4d7"
down_revision = "c5d1e8a7b9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("additional_loans", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("additional_loans")
