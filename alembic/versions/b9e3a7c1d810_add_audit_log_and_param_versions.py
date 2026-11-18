"""add audit log, risk parameter set versions and run inputs

Revision ID: b9e3a7c1d810
Revises: a8d2f6b0c709
Create Date: 2026-10-24 21:00:00.000000
"""
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b9e3a7c1d810"
down_revision = "a8d2f6b0c709"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("property_id", sa.String(36), nullable=True, index=True),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("changes_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
                  index=True),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    versions = op.create_table(
        "risk_parameter_set_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parameter_set_id", sa.String(36),
                  sa.ForeignKey("risk_parameter_sets.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    with op.batch_alter_table("loan_risk_runs") as batch:
        batch.add_column(sa.Column("inputs_json", sa.Text(), nullable=True))

    # Existing sets: keep their current version (earlier ones were overwritten)
    sets = op.get_bind().execute(sa.text(
        "SELECT id, version, name, comment, params_json FROM risk_parameter_sets"
    )).fetchall()
    if sets:
        op.bulk_insert(versions, [
            {"id": str(uuid.uuid4()), "parameter_set_id": s.id, "version": s.version, "name": s.name,
             "comment": s.comment, "params_json": s.params_json}
            for s in sets
        ])


def downgrade() -> None:
    with op.batch_alter_table("loan_risk_runs") as batch:
        batch.drop_column("inputs_json")
    op.drop_table("risk_parameter_set_versions")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")
