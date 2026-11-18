"""Add monthly vacancy calculation frequency.

Revision ID: c8e4f2a1d609
Revises: b3e8f1c7d425
"""
from alembic import op
import sqlalchemy as sa


revision = "c8e4f2a1d609"
down_revision = "b3e8f1c7d425"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "valuations",
        sa.Column("vacancy_calculation_frequency", sa.String(length=16), nullable=False, server_default="annual"),
    )


def downgrade():
    op.drop_column("valuations", "vacancy_calculation_frequency")
