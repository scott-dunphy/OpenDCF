"""add upon-expiration options, committed TI/LC and MLA chaining

Revision ID: e6b0d4f8a507
Revises: d5a9c3e7f406
Create Date: 2026-10-24 19:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e6b0d4f8a507"
down_revision = "d5a9c3e7f406"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leases") as batch:
        batch.add_column(sa.Column("upon_expiration", sa.String(20), nullable=False, server_default="market"))
        batch.add_column(sa.Column("option_rent_per_unit", sa.Numeric(18, 6), nullable=True))
        batch.add_column(sa.Column("option_term_months", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("option_ti_per_sf", sa.Numeric(18, 6), nullable=False, server_default="0"))
        batch.add_column(sa.Column("option_lc_pct", sa.Numeric(10, 6), nullable=False, server_default="0"))
        batch.add_column(sa.Column("committed_ti_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("committed_lc_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("next_profile_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_market_leasing_profiles_next_profile_id", "market_leasing_profiles",
            ["next_profile_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_constraint("fk_market_leasing_profiles_next_profile_id", type_="foreignkey")
        batch.drop_column("next_profile_id")
    with op.batch_alter_table("leases") as batch:
        batch.drop_column("committed_lc_amount")
        batch.drop_column("committed_ti_amount")
        batch.drop_column("option_lc_pct")
        batch.drop_column("option_ti_per_sf")
        batch.drop_column("option_term_months")
        batch.drop_column("option_rent_per_unit")
        batch.drop_column("upon_expiration")
