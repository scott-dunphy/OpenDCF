"""add lease-up assumptions to suites

Revision ID: f7c1e5a9b608
Revises: e6b0d4f8a507
Create Date: 2026-10-24 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7c1e5a9b608"
down_revision = "e6b0d4f8a507"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("suites") as batch:
        batch.add_column(sa.Column("absorption_start_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("lease_up_months", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("suites") as batch:
        batch.drop_column("lease_up_months")
        batch.drop_column("absorption_start_date")
