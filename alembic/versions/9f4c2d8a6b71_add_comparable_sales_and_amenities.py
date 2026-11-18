"""add comparable sales, selections, and property amenities

Revision ID: 9f4c2d8a6b71
Revises: 7e2a9c4f1d63
Create Date: 2026-11-14 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9f4c2d8a6b71"
down_revision = "7e2a9c4f1d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("amenities", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "comparable_sales",
        sa.Column("external_id", sa.String(100), nullable=True, unique=True),
        sa.Column("property_name", sa.String(255), nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("sale_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("property_type", sa.String(50), nullable=False),
        sa.Column("property_subtype", sa.String(100), nullable=True),
        sa.Column("area", sa.Numeric(18, 4), nullable=False),
        sa.Column("area_unit", sa.String(10), nullable=False, server_default="sf"),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(50), nullable=True),
        sa.Column("market", sa.String(100), nullable=True),
        sa.Column("submarket", sa.String(100), nullable=True),
        sa.Column("year_built", sa.Integer(), nullable=True),
        sa.Column("year_renovated", sa.Integer(), nullable=True),
        sa.Column("occupancy_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("normalized_noi", sa.Numeric(18, 2), nullable=True),
        sa.Column("amenities", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_distressed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_portfolio_sale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_partial_interest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("financing_terms", sa.Text(), nullable=True),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="unverified"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_comparable_sales_sale_date", "comparable_sales", ["sale_date"])
    op.create_index("ix_comparable_sales_property_type", "comparable_sales", ["property_type"])
    op.create_index("ix_comparable_sales_market", "comparable_sales", ["market"])
    op.create_table(
        "comparable_selections",
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sale_id", sa.String(36), sa.ForeignKey("comparable_sales.id", ondelete="CASCADE"), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("weight", sa.Numeric(10, 6), nullable=False, server_default="1"),
        sa.Column("adjustments", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("property_id", "sale_id"),
    )


def downgrade() -> None:
    op.drop_table("comparable_selections")
    op.drop_index("ix_comparable_sales_market", table_name="comparable_sales")
    op.drop_index("ix_comparable_sales_property_type", table_name="comparable_sales")
    op.drop_index("ix_comparable_sales_sale_date", table_name="comparable_sales")
    op.drop_table("comparable_sales")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("amenities")
