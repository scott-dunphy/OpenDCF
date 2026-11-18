"""Recovery structures get a modified gross expense stop ($/SF/yr)

The structure's stop applies to its default recovery type; a category override's stop applies to
that category alone. Modified gross overrides that entered their stop as the floor (which the
engine read as the stop) move it to the new column.

Revision ID: b4e2c7a9d3f1
Revises: d8f3b6a2c9e1
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "b4e2c7a9d3f1"
down_revision = "d8f3b6a2c9e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("recovery_structures", "recovery_structure_items"):
        with op.batch_alter_table(name) as batch:
            batch.add_column(sa.Column("expense_stop_per_sf", sa.Numeric(18, 6), nullable=True))
    op.execute(
        "UPDATE recovery_structure_items SET expense_stop_per_sf = floor_per_sf_annual, "
        "floor_per_sf_annual = NULL WHERE recovery_type = 'modified_gross' AND floor_per_sf_annual IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE recovery_structure_items SET floor_per_sf_annual = expense_stop_per_sf "
        "WHERE recovery_type = 'modified_gross' AND expense_stop_per_sf IS NOT NULL"
    )
    for name in ("recovery_structure_items", "recovery_structures"):
        with op.batch_alter_table(name) as batch:
            batch.drop_column("expense_stop_per_sf")
