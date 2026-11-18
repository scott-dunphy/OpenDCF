"""Market leasing profiles belong to valuations; suites name a market space type

Each existing valuation gets its own copy of its property's profiles (the first valuation keeps
the original rows and ids). A property with profiles but no valuation gets a draft
"Market leasing (migrated)" valuation to keep them. A suite's explicit profile becomes the
name of that profile's space type.

Revision ID: b7e2c4d9a1f3
Revises: a9c3e5f7b1d2
Create Date: 2026-11-14
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "b7e2c4d9a1f3"
down_revision = "a9c3e5f7b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    with op.batch_alter_table("suites") as batch:
        batch.add_column(sa.Column("market_space_type", sa.String(100), nullable=True))
    conn.execute(sa.text(
        "UPDATE suites SET market_space_type = (SELECT m.space_type FROM market_leasing_profiles m "
        "WHERE m.id = suites.market_leasing_profile_id) WHERE market_leasing_profile_id IS NOT NULL"
    ))
    with op.batch_alter_table("suites") as batch:
        batch.drop_column("market_leasing_profile_id")

    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("inputs_updated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.add_column(sa.Column("valuation_id", sa.String(36), nullable=True))

    profiles = conn.execute(sa.text("SELECT * FROM market_leasing_profiles")).mappings().all()
    valuations = conn.execute(sa.text(
        "SELECT id, property_id FROM valuations ORDER BY created_at, id")).mappings().all()
    by_property: dict[str, list[str]] = {}
    for v in valuations:
        by_property.setdefault(v["property_id"], []).append(v["id"])
    table = sa.table("market_leasing_profiles", *(sa.column(k) for k in (profiles[0].keys() if profiles else [])))
    for property_id in {p["property_id"] for p in profiles}:
        rows = [p for p in profiles if p["property_id"] == property_id]
        owners = by_property.get(property_id, [])
        if not owners:
            # Keep the profiles on a placeholder draft valuation (market-typical defaults to edit)
            placeholder = str(uuid.uuid4())
            conn.execute(sa.text(
                "INSERT INTO valuations (id, property_id, name, status, discount_rate, exit_cap_rate, "
                "exit_cap_applied_to_year, exit_costs_pct, transfer_tax_preset, apply_stabilized_gross_up, "
                "capital_reserves_per_unit, use_mid_year_convention, description) VALUES (:id, :p, "
                "'Market leasing (migrated)', 'draft', 0.08, 0.065, -1, 0.02, 'none', 1, 0, 0, "
                "'Created when market leasing moved onto valuations; set the rates before relying on it')"
            ), {"id": placeholder, "p": property_id})
            owners = [placeholder]
        conn.execute(sa.text("UPDATE market_leasing_profiles SET valuation_id = :v WHERE property_id = :p"),
                     {"v": owners[0], "p": property_id})
        for valuation_id in owners[1:]:
            new_ids = {r["id"]: str(uuid.uuid4()) for r in rows}
            conn.execute(sa.insert(table), [
                {**dict(r), "id": new_ids[r["id"]], "valuation_id": valuation_id,
                 "next_profile_id": new_ids.get(r["next_profile_id"]) if r["next_profile_id"] else None}
                for r in rows
            ])

    with op.batch_alter_table("market_leasing_profiles") as batch:
        batch.alter_column("valuation_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key("fk_market_leasing_profiles_valuation_id", "valuations",
                                 ["valuation_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_market_leasing_profiles_valuation_id", ["valuation_id"])


def downgrade() -> None:
    raise NotImplementedError("Valuation-owned market profiles cannot be merged back per property")
