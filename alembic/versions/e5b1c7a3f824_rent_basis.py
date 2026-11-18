"""Rent basis on leases and market leasing profiles: per area, or a total amount

Lets 0 SF space (antennas, signage) carry a lease whose rent is the whole $ amount.

Revision ID: e5b1c7a3f824
Revises: b7e2c4d9a1f3
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "e5b1c7a3f824"
down_revision = "b7e2c4d9a1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("leases", "market_leasing_profiles"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("rent_basis", sa.String(20), nullable=False, server_default="per_area"))


def downgrade() -> None:
    for table in ("leases", "market_leasing_profiles"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("rent_basis")
