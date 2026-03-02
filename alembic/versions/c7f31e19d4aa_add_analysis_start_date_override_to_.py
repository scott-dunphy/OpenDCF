"""add analysis start date override to valuations

Revision ID: c7f31e19d4aa
Revises: 8c1b2f0f34ad
Create Date: 2026-03-02 18:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7f31e19d4aa"
down_revision: Union[str, None] = "8c1b2f0f34ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("valuations"):
        return

    cols = {c["name"] for c in inspector.get_columns("valuations")}
    with op.batch_alter_table("valuations") as batch:
        if "analysis_start_date_override" not in cols:
            batch.add_column(sa.Column("analysis_start_date_override", sa.Date(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("valuations"):
        return

    cols = {c["name"] for c in inspector.get_columns("valuations")}
    with op.batch_alter_table("valuations") as batch:
        if "analysis_start_date_override" in cols:
            batch.drop_column("analysis_start_date_override")
