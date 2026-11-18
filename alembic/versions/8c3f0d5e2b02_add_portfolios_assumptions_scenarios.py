"""add portfolios, assumption profiles, scenarios, runs and property market

Revision ID: 8c3f0d5e2b02
Revises: 7b2e9c4d1a01
Create Date: 2026-10-24 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8c3f0d5e2b02"
down_revision = "7b2e9c4d1a01"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("market", sa.String(100), nullable=True))

    op.create_table(
        "portfolios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "portfolio_properties",
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "assumption_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True),
        sa.Column("property_type", sa.String(50), nullable=True),
        sa.Column("market", sa.String(100), nullable=True),
        sa.Column("values_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("comment", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "portfolio_scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("overrides_json", sa.Text(), nullable=False, server_default="[]"),
        *_timestamps(),
    )
    op.create_table(
        "portfolio_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("results_json", sa.Text(), nullable=False, server_default="{}"),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("portfolio_runs")
    op.drop_table("portfolio_scenarios")
    op.drop_table("assumption_profiles")
    op.drop_table("portfolio_properties")
    op.drop_table("portfolios")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("market")
