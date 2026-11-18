"""add comment fields to inputs and assumptions

Revision ID: a9f1bde6c4f2
Revises: 3d3206d033aa
Create Date: 2026-03-01 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9f1bde6c4f2'
down_revision: Union[str, None] = '3d3206d033aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = [
        'properties',
        'suites',
        'tenants',
        'leases',
        'rent_steps',
        'free_rent_periods',
        'lease_expense_recoveries',
        'property_expenses',
        'property_other_income',
        'market_leasing_profiles',
        'property_capital_projects',
        'recovery_structures',
        'recovery_structure_items',
        'valuations',
    ]
    for table_name in tables:
        if not inspector.has_table(table_name):
            continue
        cols = {c["name"] for c in inspector.get_columns(table_name)}
        if "comment" in cols:
            continue
        op.add_column(table_name, sa.Column('comment', sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = [
        'valuations',
        'recovery_structure_items',
        'recovery_structures',
        'property_capital_projects',
        'market_leasing_profiles',
        'property_other_income',
        'property_expenses',
        'lease_expense_recoveries',
        'free_rent_periods',
        'rent_steps',
        'leases',
        'tenants',
        'suites',
        'properties',
    ]
    for table_name in tables:
        if not inspector.has_table(table_name):
            continue
        cols = {c["name"] for c in inspector.get_columns(table_name)}
        if "comment" not in cols:
            continue
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column('comment')
