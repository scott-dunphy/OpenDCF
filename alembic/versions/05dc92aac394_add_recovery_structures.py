"""add recovery structures

Revision ID: 05dc92aac394
Revises: cdf6c450991d
Create Date: 2026-02-28 18:35:15.393694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05dc92aac394'
down_revision: Union[str, None] = 'cdf6c450991d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('recovery_structures',
    sa.Column('property_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('default_recovery_type', sa.String(length=30), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('recovery_structure_items',
    sa.Column('recovery_structure_id', sa.String(length=36), nullable=False),
    sa.Column('expense_category', sa.String(length=50), nullable=False),
    sa.Column('recovery_type', sa.String(length=30), nullable=False),
    sa.Column('base_year_stop_amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('cap_per_sf_annual', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('floor_per_sf_annual', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('admin_fee_pct', sa.Numeric(precision=10, scale=6), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['recovery_structure_id'], ['recovery_structures.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('leases') as batch_op:
        batch_op.add_column(sa.Column('recovery_structure_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            'fk_leases_recovery_structure',
            'recovery_structures',
            ['recovery_structure_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('leases') as batch_op:
        batch_op.drop_constraint('fk_leases_recovery_structure', type_='foreignkey')
        batch_op.drop_column('recovery_structure_id')
    op.drop_table('recovery_structure_items')
    op.drop_table('recovery_structures')
