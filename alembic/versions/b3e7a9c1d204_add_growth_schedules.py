"""add year-by-year growth schedules and valuation CPI

Revision ID: b3e7a9c1d204
Revises: 9d4a1e6f3c03
Create Date: 2026-10-24 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3e7a9c1d204"
down_revision = "9d4a1e6f3c03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("rent_growth_schedule", sa.Text(), nullable=True))
    with op.batch_alter_table("property_expenses") as batch:
        batch.add_column(sa.Column("growth_schedule", sa.Text(), nullable=True))
    with op.batch_alter_table("property_other_income") as batch:
        batch.add_column(sa.Column("growth_schedule", sa.Text(), nullable=True))
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("cpi_rate", sa.Numeric(10, 6), nullable=True))
        batch.add_column(sa.Column("cpi_schedule", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("cpi_schedule")
        batch.drop_column("cpi_rate")
    with op.batch_alter_table("property_other_income") as batch:
        batch.drop_column("growth_schedule")
    with op.batch_alter_table("property_expenses") as batch:
        batch.drop_column("growth_schedule")
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("rent_growth_schedule")
