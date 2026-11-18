"""Group repeated extracted facts (one tenant's lease row) by record key

Revision ID: b7e2c9d4f160
Revises: a1d4e7c2b903
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "b7e2c9d4f160"
down_revision = "a1d4e7c2b903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extracted_facts") as batch:
        batch.add_column(sa.Column("record_key", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("extracted_facts") as batch:
        batch.drop_column("record_key")
