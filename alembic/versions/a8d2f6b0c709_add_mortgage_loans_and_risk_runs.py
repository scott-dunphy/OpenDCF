"""add mortgage loans, risk parameter sets and loan risk runs

Revision ID: a8d2f6b0c709
Revises: f7c1e5a9b608
Create Date: 2026-10-24 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a8d2f6b0c709"
down_revision = "f7c1e5a9b608"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "mortgage_loans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lien_position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sponsor", sa.String(255), nullable=True),
        sa.Column("recourse", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("origination_date", sa.Date(), nullable=False),
        sa.Column("original_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("maturity_date", sa.Date(), nullable=False),
        sa.Column("rate_type", sa.String(20), nullable=False, server_default="fixed"),
        sa.Column("coupon", sa.Numeric(10, 6), nullable=True),
        sa.Column("index_name", sa.String(30), nullable=True),
        sa.Column("spread", sa.Numeric(10, 6), nullable=True),
        sa.Column("index_floor", sa.Numeric(10, 6), nullable=True),
        sa.Column("index_cap", sa.Numeric(10, 6), nullable=True),
        sa.Column("amortization_months", sa.Integer(), nullable=True),
        sa.Column("io_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extension_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extension_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reported_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("balance_as_of_date", sa.Date(), nullable=True),
        sa.Column("delinquency_status", sa.String(20), nullable=False, server_default="current"),
        sa.Column("origination_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("origination_noi", sa.Numeric(18, 2), nullable=True),
        sa.Column("tape_noi", sa.Numeric(18, 2), nullable=True),
        sa.Column("tape_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("tape_value_date", sa.Date(), nullable=True),
        sa.Column("tape_occupancy", sa.Numeric(10, 6), nullable=True),
        sa.Column("tape_noi_growth", sa.Numeric(10, 6), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "risk_parameter_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("params_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("comment", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "loan_risk_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parameter_set_id", sa.String(36),
                  sa.ForeignKey("risk_parameter_sets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parameter_set_version", sa.Integer(), nullable=True),
        sa.Column("params_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("results_json", sa.Text(), nullable=True),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("loan_risk_runs")
    op.drop_table("risk_parameter_sets")
    op.drop_table("mortgage_loans")
