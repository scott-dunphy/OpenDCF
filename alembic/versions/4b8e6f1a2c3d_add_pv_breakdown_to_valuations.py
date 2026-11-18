"""add pv breakdown to valuations

Revision ID: 4b8e6f1a2c3d
Revises: 1e4c0d2a9b11
Create Date: 2026-03-06 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4b8e6f1a2c3d"
down_revision = "1e4c0d2a9b11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("valuations", sa.Column("result_pv_cash_flows", sa.Numeric(24, 12), nullable=True))
    op.add_column("valuations", sa.Column("result_pv_terminal_value", sa.Numeric(24, 12), nullable=True))


def downgrade() -> None:
    op.drop_column("valuations", "result_pv_terminal_value")
    op.drop_column("valuations", "result_pv_cash_flows")
