"""add portfolio ownership interests and scenario probabilities

Revision ID: f3c8a0b5e124
Revises: e2b7f9a4d013
"""

from alembic import op
import sqlalchemy as sa

revision = "f3c8a0b5e124"
down_revision = "e2b7f9a4d013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("latitude", sa.Numeric(10, 7)))
        batch.add_column(sa.Column("longitude", sa.Numeric(10, 7)))
    with op.batch_alter_table("portfolio_properties") as batch:
        batch.add_column(
            sa.Column("ownership_pct", sa.Numeric(8, 6), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("effective_from", sa.Date()))
        batch.add_column(sa.Column("effective_to", sa.Date()))
        batch.add_column(sa.Column("acquisition_cost", sa.Numeric(18, 2)))
        batch.add_column(sa.Column("commitment", sa.Numeric(18, 2)))
        batch.add_column(sa.Column("currency", sa.String(3), nullable=False, server_default="USD"))
    # Preserve existing behavior by copying the property's current ownership into each membership.
    op.execute(
        sa.text("""
        UPDATE portfolio_properties
        SET ownership_pct = COALESCE(
            (SELECT ownership_pct FROM properties WHERE properties.id = portfolio_properties.property_id), 1
        )
    """)
    )
    with op.batch_alter_table("portfolio_scenarios") as batch:
        batch.add_column(sa.Column("probability_pct", sa.Float()))


def downgrade() -> None:
    with op.batch_alter_table("portfolio_scenarios") as batch:
        batch.drop_column("probability_pct")
    with op.batch_alter_table("portfolio_properties") as batch:
        batch.drop_column("currency")
        batch.drop_column("commitment")
        batch.drop_column("acquisition_cost")
        batch.drop_column("effective_to")
        batch.drop_column("effective_from")
        batch.drop_column("ownership_pct")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("longitude")
        batch.drop_column("latitude")
