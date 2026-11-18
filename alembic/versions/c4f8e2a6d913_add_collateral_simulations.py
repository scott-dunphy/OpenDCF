"""add collateral simulations; move parameter sets to the driver scenario model

Revision ID: c4f8e2a6d913
Revises: b9e3a7c1d810
Create Date: 2026-10-24 23:00:00.000000
"""
import json
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4f8e2a6d913"
down_revision = "b9e3a7c1d810"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collateral_simulations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("valuation_id", sa.String(36), sa.ForeignKey("valuations.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("analysis_start", sa.Date(), nullable=False),
        sa.Column("horizon_months", sa.Integer(), nullable=False),
        sa.Column("num_paths", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("parameter_set_id", sa.String(36), nullable=True),
        sa.Column("parameter_set_version", sa.Integer(), nullable=True),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("inputs_hash", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Numeric(6, 4), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("paths_blob", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Saved parameter sets: drop the NOI-shock settings, add the driver settings at their defaults,
    # and keep the result as a new version
    from src.engine.loan_risk.params import RETIRED_KEYS, RiskParameters

    defaults = RiskParameters().to_dict()
    conn = op.get_bind()
    sets = conn.execute(sa.text("SELECT id, name, version, params_json FROM risk_parameter_sets")).fetchall()
    for set_id, name, version, params_json in sets:
        old = json.loads(params_json or "{}")
        new = {**defaults, **{k: v for k, v in old.items() if k in defaults and k not in RETIRED_KEYS}}
        if new == old:
            continue
        comment = "Moved to the driver scenario model (full property valuation on every path)"
        conn.execute(sa.text("UPDATE risk_parameter_sets SET params_json = :p, version = :v WHERE id = :id"),
                     {"p": json.dumps(new), "v": version + 1, "id": set_id})
        conn.execute(sa.text(
            "INSERT INTO risk_parameter_set_versions (id, parameter_set_id, version, name, comment, params_json, "
            "created_at) VALUES (:id, :sid, :v, :n, :c, :p, CURRENT_TIMESTAMP)"
        ), {"id": str(uuid.uuid4()), "sid": set_id, "v": version + 1, "n": name, "c": comment,
            "p": json.dumps(new)})


def downgrade() -> None:
    op.drop_table("collateral_simulations")
