"""Valuations record the engine version their results were calculated with

Existing results stay NULL (calculated before versioning), so they show as needing a re-run.

Revision ID: e6a2d9c4f7b1
Revises: c7f1a3e5b2d8
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "e6a2d9c4f7b1"
down_revision = "c7f1a3e5b2d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("result_engine_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("result_engine_version")
