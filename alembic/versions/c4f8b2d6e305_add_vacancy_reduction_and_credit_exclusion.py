"""add general vacancy reduction toggle and credit-tenant exclusion

Revision ID: c4f8b2d6e305
Revises: b3e7a9c1d204
Create Date: 2026-10-24 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4f8b2d6e305"
down_revision = "b3e7a9c1d204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leases") as batch:
        batch.add_column(sa.Column(
            "exclude_from_general_vacancy", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column(
            "reduce_general_vacancy_by_downtime", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("reduce_general_vacancy_by_downtime")
    with op.batch_alter_table("leases") as batch:
        batch.drop_column("exclude_from_general_vacancy")
