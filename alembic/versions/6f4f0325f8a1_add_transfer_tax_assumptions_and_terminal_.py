"""add transfer tax assumptions and terminal breakdown result fields

Revision ID: 6f4f0325f8a1
Revises: a9f1bde6c4f2
Create Date: 2026-03-01 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f4f0325f8a1'
down_revision: Union[str, None] = 'a9f1bde6c4f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VALUATIONS = 'valuations'


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_VALUATIONS):
        return

    cols = {c['name'] for c in inspector.get_columns(_VALUATIONS)}
    with op.batch_alter_table(_VALUATIONS) as batch:
        if 'transfer_tax_preset' not in cols:
            batch.add_column(sa.Column('transfer_tax_preset', sa.String(length=64), nullable=False, server_default='none'))
        if 'transfer_tax_custom_rate' not in cols:
            batch.add_column(sa.Column('transfer_tax_custom_rate', sa.Numeric(precision=10, scale=6), nullable=True))

        if 'result_terminal_noi_basis' not in cols:
            batch.add_column(sa.Column('result_terminal_noi_basis', sa.Numeric(precision=18, scale=2), nullable=True))
        if 'result_terminal_gross_value' not in cols:
            batch.add_column(sa.Column('result_terminal_gross_value', sa.Numeric(precision=18, scale=2), nullable=True))
        if 'result_terminal_exit_costs_amount' not in cols:
            batch.add_column(sa.Column('result_terminal_exit_costs_amount', sa.Numeric(precision=18, scale=2), nullable=True))
        if 'result_terminal_transfer_tax_amount' not in cols:
            batch.add_column(sa.Column('result_terminal_transfer_tax_amount', sa.Numeric(precision=18, scale=2), nullable=True))
        if 'result_terminal_transfer_tax_preset' not in cols:
            batch.add_column(sa.Column('result_terminal_transfer_tax_preset', sa.String(length=64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_VALUATIONS):
        return

    cols = {c['name'] for c in inspector.get_columns(_VALUATIONS)}
    with op.batch_alter_table(_VALUATIONS) as batch:
        if 'result_terminal_transfer_tax_preset' in cols:
            batch.drop_column('result_terminal_transfer_tax_preset')
        if 'result_terminal_transfer_tax_amount' in cols:
            batch.drop_column('result_terminal_transfer_tax_amount')
        if 'result_terminal_exit_costs_amount' in cols:
            batch.drop_column('result_terminal_exit_costs_amount')
        if 'result_terminal_gross_value' in cols:
            batch.drop_column('result_terminal_gross_value')
        if 'result_terminal_noi_basis' in cols:
            batch.drop_column('result_terminal_noi_basis')

        if 'transfer_tax_custom_rate' in cols:
            batch.drop_column('transfer_tax_custom_rate')
        if 'transfer_tax_preset' in cols:
            batch.drop_column('transfer_tax_preset')
