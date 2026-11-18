"""add valuation basis and nominal-real controls

Revision ID: 7e2a9c4f1d63
Revises: 3a7d1c9e5b20
Create Date: 2026-11-14 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "7e2a9c4f1d63"
down_revision = "3a7d1c9e5b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("basis_of_value", sa.String(32), nullable=False, server_default="market_value"))
        batch.add_column(sa.Column("intended_use", sa.String(255), nullable=True))
        batch.add_column(sa.Column("risk_treatment", sa.String(32), nullable=False, server_default="deterministic"))
        batch.add_column(sa.Column("cash_flow_basis", sa.String(16), nullable=False, server_default="nominal"))
        batch.add_column(sa.Column("discount_rate_basis", sa.String(16), nullable=False, server_default="nominal"))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("discount_rate_basis")
        batch.drop_column("cash_flow_basis")
        batch.drop_column("risk_treatment")
        batch.drop_column("intended_use")
        batch.drop_column("basis_of_value")
