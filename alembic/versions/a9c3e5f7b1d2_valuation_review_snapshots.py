"""Valuation review lifecycle: review status, frozen snapshots, as-of portfolio runs

Revision ID: a9c3e5f7b1d2
Revises: f3b8d2a6c419
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "a9c3e5f7b1d2"
down_revision = "f3b8d2a6c419"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "valuation_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("valuation_id", sa.String(36), sa.ForeignKey("valuations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
        sa.Column("recovery_audit_json", sa.Text()),
        sa.Column("schema_revision", sa.String(32)),
        sa.Column("result_npv", sa.Numeric(18, 2)),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("submitted_by", sa.String(120), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submit_note", sa.Text()),
        sa.Column("approved_by", sa.String(120)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approve_note", sa.Text()),
        sa.Column("reopened_by", sa.String(120)),
        sa.Column("reopened_at", sa.DateTime(timezone=True)),
        sa.Column("reopen_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_valuation_snapshots_valuation_id", "valuation_snapshots", ["valuation_id"])
    op.add_column("portfolio_runs", sa.Column("as_of", sa.Date()))
    op.add_column("valuations", sa.Column("review_status", sa.String(20), nullable=False, server_default="draft"))
    op.add_column("valuations", sa.Column("snapshot_id", sa.String(36)))


def downgrade() -> None:
    with op.batch_alter_table("portfolio_runs") as batch:
        batch.drop_column("as_of")
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("snapshot_id")
        batch.drop_column("review_status")
    op.drop_index("ix_valuation_snapshots_valuation_id", "valuation_snapshots")
    op.drop_table("valuation_snapshots")
