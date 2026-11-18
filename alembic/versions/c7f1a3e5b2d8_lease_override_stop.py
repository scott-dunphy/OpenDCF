"""Per-lease recovery overrides get a modified gross expense stop ($/SF/yr)

Mirrors recovery structure items: modified gross lease overrides that entered their stop as the
floor (which the engine read as the stop) move it to the new column.

Revision ID: c7f1a3e5b2d8
Revises: b4e2c7a9d3f1
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "c7f1a3e5b2d8"
down_revision = "b4e2c7a9d3f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("lease_expense_recoveries") as batch:
        batch.add_column(sa.Column("expense_stop_per_sf", sa.Numeric(18, 6), nullable=True))
    op.execute(
        "UPDATE lease_expense_recoveries SET expense_stop_per_sf = floor_per_sf_annual, "
        "floor_per_sf_annual = NULL WHERE recovery_type = 'modified_gross' AND floor_per_sf_annual IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE lease_expense_recoveries SET floor_per_sf_annual = expense_stop_per_sf "
        "WHERE recovery_type = 'modified_gross' AND expense_stop_per_sf IS NOT NULL"
    )
    with op.batch_alter_table("lease_expense_recoveries") as batch:
        batch.drop_column("expense_stop_per_sf")
