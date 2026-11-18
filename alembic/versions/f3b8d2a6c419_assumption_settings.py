"""Assumptions library settings: editable quality directions

Revision ID: f3b8d2a6c419
Revises: e5c1a9f3b2d7
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b8d2a6c419"
down_revision = "e5c1a9f3b2d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assumption_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("directions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("assumption_settings")
