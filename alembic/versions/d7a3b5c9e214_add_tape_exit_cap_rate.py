"""add tape exit cap rate to mortgage loans

Revision ID: d7a3b5c9e214
Revises: c4f8e2a6d913
Create Date: 2026-10-25 00:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d7a3b5c9e214"
down_revision = "c4f8e2a6d913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mortgage_loans", sa.Column("tape_exit_cap_rate", sa.Numeric(10, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("mortgage_loans", "tape_exit_cap_rate")
