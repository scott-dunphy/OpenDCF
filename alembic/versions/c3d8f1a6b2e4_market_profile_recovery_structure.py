"""Recovery structure on market leasing profiles

Market leases (renewals, new tenants, vacant space leasing up) under a profile use its recovery
structure; blank keeps copying the expiring lease's recovery type (NNN for space never leased).

Revision ID: c3d8f1a6b2e4
Revises: e5b1c7a3f824
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d8f1a6b2e4"
down_revision = "e5b1c7a3f824"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("recovery_structure_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_market_leasing_profiles_recovery_structure_id", "recovery_structures",
            ["recovery_structure_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_constraint("fk_market_leasing_profiles_recovery_structure_id", type_="foreignkey")
        batch.drop_column("recovery_structure_id")
