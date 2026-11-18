"""add ownership_pct to properties

Revision ID: 5a9d3e7f0b12
Revises: 4b8e6f1a2c3d
Create Date: 2026-03-08 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5a9d3e7f0b12"
down_revision = "4b8e6f1a2c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("ownership_pct", sa.Numeric(8, 6), nullable=False, server_default="1.0"),
    )


def downgrade() -> None:
    op.drop_column("properties", "ownership_pct")
