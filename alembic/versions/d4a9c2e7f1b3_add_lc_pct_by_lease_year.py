"""Add leasing commission % by lease year to market leasing profiles

Revision ID: d4a9c2e7f1b3
Revises: b8e3f1a6c4d7
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "d4a9c2e7f1b3"
down_revision = "b8e3f1a6c4d7"
branch_labels = None
depends_on = None

COLUMNS = ("new_tenant_lc_pct_by_lease_year", "renewal_lc_pct_by_lease_year")


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        for name in COLUMNS:
            batch.drop_column(name)
