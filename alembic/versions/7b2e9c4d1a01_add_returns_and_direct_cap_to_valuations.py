"""add purchase price returns, direct cap and sensitivity inputs to valuations

Revision ID: 7b2e9c4d1a01
Revises: 5a9d3e7f0b12
Create Date: 2026-10-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7b2e9c4d1a01"
down_revision = "5a9d3e7f0b12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("loan_fees_pct", sa.Numeric(10, 6), nullable=False, server_default="0"))
        batch.add_column(sa.Column("purchase_price", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("acquisition_costs_pct", sa.Numeric(10, 6), nullable=False, server_default="0"))
        batch.add_column(sa.Column("direct_cap_rate", sa.Numeric(10, 6), nullable=True))
        batch.add_column(sa.Column("exit_deduct_forward_capital", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("result_terminal_capital_deduction_amount", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("result_direct_cap_value", sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column("result_levered_irr", sa.Numeric(10, 6), nullable=True))
        batch.add_column(sa.Column("result_returns_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        for col in (
            "result_returns_json",
            "result_levered_irr",
            "result_direct_cap_value",
            "result_terminal_capital_deduction_amount",
            "exit_deduct_forward_capital",
            "direct_cap_rate",
            "acquisition_costs_pct",
            "purchase_price",
            "loan_fees_pct",
        ):
            batch.drop_column(col)
