"""add appraisal reconstruction staging

Revision ID: e2b7f9a4d013
Revises: d1a6e8f3c902
"""

from alembic import op
import sqlalchemy as sa

revision = "e2b7f9a4d013"
down_revision = "d1a6e8f3c902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appraisal_reconstructions",
        sa.Column(
            "source_valuation_id",
            sa.String(36),
            sa.ForeignKey("valuations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            sa.String(36),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("unresolved_json", sa.Text(), nullable=False),
        sa.Column(
            "rebuilt_property_id",
            sa.String(36),
            sa.ForeignKey("properties.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "rebuilt_valuation_id",
            sa.String(36),
            sa.ForeignKey("valuations.id", ondelete="SET NULL"),
        ),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_appraisal_reconstructions_source_valuation_id",
        "appraisal_reconstructions",
        ["source_valuation_id"],
    )
    op.create_index(
        "ix_appraisal_reconstructions_source_document_id",
        "appraisal_reconstructions",
        ["source_document_id"],
    )


def downgrade() -> None:
    op.drop_table("appraisal_reconstructions")
