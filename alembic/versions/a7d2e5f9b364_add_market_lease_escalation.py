"""add market lease escalation and LC-on-escalations switch

Revision ID: a7d2e5f9b364
Revises: f6c1d4e8a253
Create Date: 2026-10-24 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7d2e5f9b364"
down_revision = "f6c1d4e8a253"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("lease_escalation_pct", sa.Numeric(10, 6), nullable=True))
        batch.add_column(sa.Column(
            "lc_includes_escalations", sa.Boolean(), nullable=False, server_default=sa.true(),
        ))


def downgrade() -> None:
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.drop_column("lc_includes_escalations")
        batch.drop_column("lease_escalation_pct")
