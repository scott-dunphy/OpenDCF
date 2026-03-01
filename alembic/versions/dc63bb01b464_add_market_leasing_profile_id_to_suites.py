"""add market_leasing_profile_id to suites

Revision ID: dc63bb01b464
Revises: e3bc24a08a92
Create Date: 2026-02-28 11:46:33.125446

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc63bb01b464'
down_revision: Union[str, None] = 'e3bc24a08a92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite needs batch mode for FK constraints
    with op.batch_alter_table('suites') as batch_op:
        batch_op.add_column(sa.Column('market_leasing_profile_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            'fk_suites_market_leasing_profile',
            'market_leasing_profiles',
            ['market_leasing_profile_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('suites') as batch_op:
        batch_op.drop_constraint('fk_suites_market_leasing_profile', type_='foreignkey')
        batch_op.drop_column('market_leasing_profile_id')
