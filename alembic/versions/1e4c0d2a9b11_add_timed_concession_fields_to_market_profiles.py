"""add timed concession fields to market profiles

Revision ID: 1e4c0d2a9b11
Revises: c7f31e19d4aa
Create Date: 2026-03-02 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1e4c0d2a9b11"
down_revision: Union[str, None] = "c7f31e19d4aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("market_leasing_profiles"):
        return

    cols = {c["name"] for c in inspector.get_columns("market_leasing_profiles")}
    with op.batch_alter_table("market_leasing_profiles") as batch:
        if "concession_timing_mode" not in cols:
            batch.add_column(
                sa.Column(
                    "concession_timing_mode",
                    sa.String(length=20),
                    nullable=False,
                    server_default="blended",
                )
            )
        if "concession_year1_months" not in cols:
            batch.add_column(sa.Column("concession_year1_months", sa.Numeric(10, 4), nullable=True))
        if "concession_year2_months" not in cols:
            batch.add_column(sa.Column("concession_year2_months", sa.Numeric(10, 4), nullable=True))
        if "concession_year3_months" not in cols:
            batch.add_column(sa.Column("concession_year3_months", sa.Numeric(10, 4), nullable=True))
        if "concession_year4_months" not in cols:
            batch.add_column(sa.Column("concession_year4_months", sa.Numeric(10, 4), nullable=True))
        if "concession_year5_months" not in cols:
            batch.add_column(sa.Column("concession_year5_months", sa.Numeric(10, 4), nullable=True))
        if "concession_stabilized_months" not in cols:
            batch.add_column(sa.Column("concession_stabilized_months", sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("market_leasing_profiles"):
        return

    cols = {c["name"] for c in inspector.get_columns("market_leasing_profiles")}
    with op.batch_alter_table("market_leasing_profiles") as batch:
        if "concession_stabilized_months" in cols:
            batch.drop_column("concession_stabilized_months")
        if "concession_year5_months" in cols:
            batch.drop_column("concession_year5_months")
        if "concession_year4_months" in cols:
            batch.drop_column("concession_year4_months")
        if "concession_year3_months" in cols:
            batch.drop_column("concession_year3_months")
        if "concession_year2_months" in cols:
            batch.drop_column("concession_year2_months")
        if "concession_year1_months" in cols:
            batch.drop_column("concession_year1_months")
        if "concession_timing_mode" in cols:
            batch.drop_column("concession_timing_mode")
