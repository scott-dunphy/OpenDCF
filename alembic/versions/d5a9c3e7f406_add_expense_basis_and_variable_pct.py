"""add expense amount basis and fixed/variable split

Revision ID: d5a9c3e7f406
Revises: c4f8b2d6e305
Create Date: 2026-10-24 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5a9c3e7f406"
down_revision = "c4f8b2d6e305"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("property_expenses") as batch:
        batch.add_column(sa.Column("amount_basis", sa.String(20), nullable=False, server_default="total"))
        batch.add_column(sa.Column("variable_pct", sa.Numeric(10, 6), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("property_expenses") as batch:
        batch.drop_column("variable_pct")
        batch.drop_column("amount_basis")
