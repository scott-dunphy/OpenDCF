"""add cap groups, calendar recoveries, market rent steps, vacancy exclusion switches, full-occupancy reversion

Revision ID: b3e8f1c7d425
Revises: a7d2e5f9b364
Create Date: 2026-10-24 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3e8f1c7d425"
down_revision = "a7d2e5f9b364"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("lease_expense_recoveries", "recovery_structure_items"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("cap_group", sa.String(50), nullable=True))
            batch.add_column(sa.Column("cap_growth_pct", sa.Numeric(10, 6), nullable=True))
    with op.batch_alter_table("leases") as batch:
        batch.add_column(sa.Column(
            "vacancy_exclusion_ends_at_rollover", sa.Boolean(), nullable=False, server_default=sa.true(),
        ))
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("lease_rent_steps", sa.Text(), nullable=True))
        batch.add_column(sa.Column(
            "exclude_from_general_vacancy", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column(
            "calendar_year_recoveries", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
        batch.add_column(sa.Column(
            "exit_noi_full_occupancy", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
        batch.add_column(sa.Column(
            "exit_stabilized_vacancy_pct", sa.Numeric(10, 6), nullable=False, server_default="0",
        ))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("exit_stabilized_vacancy_pct")
        batch.drop_column("exit_noi_full_occupancy")
        batch.drop_column("calendar_year_recoveries")
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("exclude_from_general_vacancy")
        batch.drop_column("lease_rent_steps")
    with op.batch_alter_table("leases") as batch:
        batch.drop_column("vacancy_exclusion_ends_at_rollover")
    for table in ("lease_expense_recoveries", "recovery_structure_items"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("cap_growth_pct")
            batch.drop_column("cap_group")
