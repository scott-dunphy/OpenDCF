"""Add memo flag to operating expenses (recoverable, not an operating expense)

Revision ID: f3c8a1d6e2b4
Revises: f3c8a1d6b2e4
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "f3c8a1d6e2b4"
down_revision = "f3c8a1d6b2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("property_expenses") as batch:
        batch.add_column(sa.Column("is_memo", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("property_expenses") as batch:
        batch.drop_column("is_memo")
