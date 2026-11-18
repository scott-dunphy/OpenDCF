"""add market leasing rollover method

Revision ID: f6c1d4e8a253
Revises: e5b9c3d7f142
Create Date: 2026-10-24 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6c1d4e8a253"
down_revision = "e5b9c3d7f142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column(
            "rollover_method", sa.String(20), nullable=False, server_default="probability_tree",
        ))


def downgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("rollover_method")
