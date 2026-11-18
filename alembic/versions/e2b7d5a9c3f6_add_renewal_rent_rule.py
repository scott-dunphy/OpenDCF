"""Add renewal rent rule (market, greater or lesser of prior rent) to market leasing profiles

Revision ID: e2b7d5a9c3f6
Revises: d4a9c2e7f1b3
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "e2b7d5a9c3f6"
down_revision = "d4a9c2e7f1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("renewal_rent_rule", sa.String(20), nullable=False, server_default="market"))


def downgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("renewal_rent_rule")
