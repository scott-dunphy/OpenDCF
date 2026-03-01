"""add result_avg_occupancy_pct to valuations

Revision ID: 9a4d1d0c61f5
Revises: 6f4f0325f8a1
Create Date: 2026-03-01 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a4d1d0c61f5'
down_revision: Union[str, None] = '6f4f0325f8a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('valuations'):
        return

    cols = {c['name'] for c in inspector.get_columns('valuations')}
    if 'result_avg_occupancy_pct' in cols:
        return

    with op.batch_alter_table('valuations') as batch:
        batch.add_column(sa.Column('result_avg_occupancy_pct', sa.Numeric(precision=10, scale=6), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('valuations'):
        return

    cols = {c['name'] for c in inspector.get_columns('valuations')}
    if 'result_avg_occupancy_pct' not in cols:
        return

    with op.batch_alter_table('valuations') as batch:
        batch.drop_column('result_avg_occupancy_pct')
