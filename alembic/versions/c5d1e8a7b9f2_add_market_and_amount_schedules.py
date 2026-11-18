"""add year-by-year market leasing schedules, market lease $/unit escalation and amount schedules

Revision ID: c5d1e8a7b9f2
Revises: e6a2d9c4f7b1
Create Date: 2026-11-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c5d1e8a7b9f2"
down_revision = "e6a2d9c4f7b1"
branch_labels = None
depends_on = None

MARKET_SCHEDULES = (
    "general_vacancy_schedule", "credit_loss_schedule", "renewal_probability_schedule", "downtime_schedule",
    "new_free_rent_schedule", "renewal_free_rent_schedule", "leasing_cost_growth_schedule",
)


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        for name in MARKET_SCHEDULES:
            batch.add_column(sa.Column(name, sa.Text(), nullable=True))
        batch.add_column(sa.Column("lease_escalation_per_unit", sa.Numeric(18, 6), nullable=True))
    with op.batch_alter_table("property_expenses") as batch:
        batch.add_column(sa.Column("amount_schedule", sa.Text(), nullable=True))
    with op.batch_alter_table("property_other_income") as batch:
        batch.add_column(sa.Column("amount_schedule", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("property_other_income") as batch:
        batch.drop_column("amount_schedule")
    with op.batch_alter_table("property_expenses") as batch:
        batch.drop_column("amount_schedule")
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("lease_escalation_per_unit")
        for name in reversed(MARKET_SCHEDULES):
            batch.drop_column(name)
