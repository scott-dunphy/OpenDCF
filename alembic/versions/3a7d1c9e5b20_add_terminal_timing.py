"""add terminal proceeds timing

Revision ID: 3a7d1c9e5b20
Revises: c8e4f2a1d609
Create Date: 2026-11-14 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3a7d1c9e5b20"
down_revision = "c8e4f2a1d609"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing mid-year valuations retain their historical terminal timing. New valuations
    # default to the economically correct end-of-hold sale timing.
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column(
            "terminal_timing", sa.String(length=20), nullable=False, server_default="end_of_period"
        ))
    op.execute(
        "UPDATE valuations SET terminal_timing = 'mid_year' WHERE use_mid_year_convention = 1"
    )


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("terminal_timing")
