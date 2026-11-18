"""add recovery audit json to valuations

Revision ID: f2c3a94c6d21
Revises: b1f4f5f2f85e
Create Date: 2026-03-02 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2c3a94c6d21"
down_revision: Union[str, None] = "b1f4f5f2f85e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("valuations"):
        return

    cols = {c["name"] for c in inspector.get_columns("valuations")}
    with op.batch_alter_table("valuations") as batch:
        if "result_recovery_audit_json" not in cols:
            batch.add_column(sa.Column("result_recovery_audit_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("valuations"):
        return

    cols = {c["name"] for c in inspector.get_columns("valuations")}
    with op.batch_alter_table("valuations") as batch:
        if "result_recovery_audit_json" in cols:
            batch.drop_column("result_recovery_audit_json")

