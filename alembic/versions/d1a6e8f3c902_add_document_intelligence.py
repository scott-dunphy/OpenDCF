"""add document intelligence and provenance

Revision ID: d1a6e8f3c902
Revises: 9f4c2d8a6b71
"""
from alembic import op
import sqlalchemy as sa

revision = "d1a6e8f3c902"
down_revision = "9f4c2d8a6b71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("ai_permission_mode", sa.String(20), nullable=False,
                                   server_default="confirm"))
    op.create_table(
        "source_documents",
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("document_type", sa.String(64)), sa.Column("relevant", sa.Boolean()),
        sa.Column("confidence", sa.Float()), sa.Column("reason", sa.Text()),
        sa.Column("family_key", sa.String(255)), sa.Column("amendment_number", sa.Integer()),
        sa.Column("document_date", sa.Date()), sa.Column("as_of_date", sa.Date()),
        sa.Column("extraction_model", sa.String(128)), sa.Column("extraction_json", sa.Text()),
        sa.Column("error_message", sa.Text()), sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("sha256"), sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_source_documents_sha256", "source_documents", ["sha256"])
    op.create_index("ix_source_documents_family_key", "source_documents", ["family_key"])
    op.create_table(
        "valuation_documents",
        sa.Column("valuation_id", sa.String(36), sa.ForeignKey("valuations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("valuation_id", "document_id"),
    )
    op.create_index("ix_valuation_documents_valuation_id", "valuation_documents", ["valuation_id"])
    op.create_index("ix_valuation_documents_document_id", "valuation_documents", ["document_id"])
    op.create_table(
        "extracted_facts",
        sa.Column("valuation_id", sa.String(36), sa.ForeignKey("valuations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_path", sa.String(255), nullable=False), sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()), sa.Column("page_number", sa.Integer()),
        sa.Column("source_quote", sa.Text()), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_extracted_facts_valuation_id", "extracted_facts", ["valuation_id"])
    op.create_index("ix_extracted_facts_document_id", "extracted_facts", ["document_id"])
    op.create_index("ix_extracted_facts_field_path", "extracted_facts", ["field_path"])
    op.create_table(
        "ai_model_actions",
        sa.Column("valuation_id", sa.String(36), sa.ForeignKey("valuations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("assistant_message", sa.Text(), nullable=False),
        sa.Column("action_type", sa.String(24), nullable=False),
        sa.Column("proposal_json", sa.Text()), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_model_actions_valuation_id", "ai_model_actions", ["valuation_id"])


def downgrade() -> None:
    op.drop_table("ai_model_actions")
    op.drop_table("extracted_facts")
    op.drop_table("valuation_documents")
    op.drop_table("source_documents")
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("ai_permission_mode")
