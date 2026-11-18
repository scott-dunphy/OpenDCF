"""add LC per SF, leasing cost growth, reserves growth, vacancy on gross revenue

Revision ID: e5b9c3d7f142
Revises: d7a3b5c9e214
Create Date: 2026-10-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5b9c3d7f142"
down_revision = "d7a3b5c9e214"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("new_tenant_lc_per_sf", sa.Numeric(18, 6), nullable=False, server_default="0"))
        batch.add_column(sa.Column("renewal_lc_per_sf", sa.Numeric(18, 6), nullable=False, server_default="0"))
        batch.add_column(sa.Column("leasing_cost_growth_rate", sa.Numeric(10, 6), nullable=False, server_default="0"))
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("capital_reserves_growth_rate", sa.Numeric(10, 6), nullable=False, server_default="0"))
        batch.add_column(sa.Column(
            "vacancy_on_gross_revenue", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("vacancy_on_gross_revenue")
        batch.drop_column("capital_reserves_growth_rate")
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("leasing_cost_growth_rate")
        batch.drop_column("renewal_lc_per_sf")
        batch.drop_column("new_tenant_lc_per_sf")
