"""add valuation gross-up controls

Revision ID: b1f4f5f2f85e
Revises: 9a4d1d0c61f5
Create Date: 2026-03-01 15:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1f4f5f2f85e'
down_revision: Union[str, None] = '9a4d1d0c61f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('valuations'):
        return

    cols = {c['name'] for c in inspector.get_columns('valuations')}
    with op.batch_alter_table('valuations') as batch:
        if 'apply_stabilized_gross_up' not in cols:
            batch.add_column(sa.Column('apply_stabilized_gross_up', sa.Boolean(), nullable=False, server_default=sa.true()))
        if 'stabilized_occupancy_pct' not in cols:
            batch.add_column(sa.Column('stabilized_occupancy_pct', sa.Numeric(precision=10, scale=6), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('valuations'):
        return

    cols = {c['name'] for c in inspector.get_columns('valuations')}
    with op.batch_alter_table('valuations') as batch:
        if 'stabilized_occupancy_pct' in cols:
            batch.drop_column('stabilized_occupancy_pct')
        if 'apply_stabilized_gross_up' in cols:
            batch.drop_column('apply_stabilized_gross_up')
