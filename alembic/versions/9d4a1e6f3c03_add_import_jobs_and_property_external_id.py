"""add import jobs and property external id

Revision ID: 9d4a1e6f3c03
Revises: 8c3f0d5e2b02
Create Date: 2026-10-24 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9d4a1e6f3c03"
down_revision = "8c3f0d5e2b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("external_id", sa.String(100), nullable=True))
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="previewed"),
        sa.Column("report_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_property_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("portfolio_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("import_jobs")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("external_id")
