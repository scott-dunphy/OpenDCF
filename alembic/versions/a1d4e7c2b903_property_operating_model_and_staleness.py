"""Property-owned marina/seniors operating model, valuation hold period, input staleness

Revision ID: a1d4e7c2b903
Revises: f3c8a0b5e124
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "a1d4e7c2b903"
down_revision = "f3c8a0b5e124"
branch_labels = None
depends_on = None

_BLOBS = {"marina": "marina_assumptions_json", "seniors_housing": "seniors_housing_assumptions_json"}


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("marina_assumptions_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("seniors_housing_assumptions_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("inputs_updated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("analysis_period_months_override", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))

    conn = op.get_bind()
    # Completed valuations count as run at their last update
    conn.execute(sa.text("UPDATE valuations SET last_run_at = updated_at WHERE status = 'completed'"))
    # Move each marina / seniors property's operating model from its most recently updated
    # valuation onto the property; valuations holding the same model drop their copy.
    # Valuations whose copy differs keep it, but the property's model now drives every run.
    for ptype, col in _BLOBS.items():
        props = conn.execute(sa.text("SELECT id FROM properties WHERE property_type = :t"), {"t": ptype}).all()
        for (pid,) in props:
            row = conn.execute(
                sa.text(
                    f"SELECT {col} FROM valuations WHERE property_id = :p AND {col} IS NOT NULL "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"p": pid},
            ).first()
            if row is None:
                continue
            conn.execute(sa.text(f"UPDATE properties SET {col} = :b WHERE id = :p"), {"b": row[0], "p": pid})
            conn.execute(
                sa.text(f"UPDATE valuations SET {col} = NULL WHERE property_id = :p AND {col} = :b"),
                {"b": row[0], "p": pid},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for col in _BLOBS.values():
        conn.execute(sa.text(
            f"UPDATE valuations SET {col} = (SELECT {col} FROM properties p WHERE p.id = valuations.property_id) "
            f"WHERE {col} IS NULL"
        ))
    with op.batch_alter_table("valuations") as batch:
        batch.drop_column("last_run_at")
        batch.drop_column("analysis_period_months_override")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("inputs_updated_at")
        batch.drop_column("seniors_housing_assumptions_json")
        batch.drop_column("marina_assumptions_json")
