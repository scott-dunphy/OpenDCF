"""Every valuation owns its whole model (docs/valuation-owned-inputs-plan.md)

Suites (with leases and their children), tenants, expenses, other income, capital projects,
recovery structures and recovery pools get a valuation_id. Per property:

- the latest draft valuation takes the live rows (ids unchanged); when the property has no draft,
  a "Working model (migrated)" draft is created to hold them;
- every other draft gets a copy of the live rows;
- every frozen valuation (in review / approved) gets a copy of the rows in its snapshot, falling
  back to the live rows if the snapshot cannot be rebuilt.

Each valuation also takes the property's analysis start and hold period (as its own) and the
property's marina / seniors / self storage operating model.

Revision ID: d8f3b6a2c9e1
Revises: f2a9c4e7d1b6
Create Date: 2026-11-14
"""
import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "d8f3b6a2c9e1"
down_revision = "f2a9c4e7d1b6"
branch_labels = None
depends_on = None

OWNED = ("tenants", "suites", "property_expenses", "property_other_income", "property_capital_projects",
         "recovery_structures", "recovery_pools")
MODELS = ("marina_assumptions_json", "seniors_housing_assumptions_json", "self_storage_assumptions_json")


def _reflected(conn, name: str) -> sa.Table:
    """The table as it is at this revision (later migrations add columns to the models)."""
    return sa.Table(name, sa.MetaData(), autoload_with=conn)


def _live_tables(conn, property_id: str) -> dict[str, list[dict]]:
    t = {name: _reflected(conn, name) for name in (*OWNED, "leases", "rent_steps", "free_rent_periods",
                                                   "lease_expense_recoveries", "recovery_structure_items")}

    def rows(name, where):
        return [dict(r) for r in conn.execute(sa.select(t[name]).where(where)).mappings()]

    out = {name: rows(name, t[name].c.property_id == property_id) for name in OWNED}
    suite_ids = [r["id"] for r in out["suites"]]
    out["leases"] = rows("leases", t["leases"].c.suite_id.in_(suite_ids)) if suite_ids else []
    lease_ids = [r["id"] for r in out["leases"]]
    for child in ("rent_steps", "free_rent_periods", "lease_expense_recoveries"):
        out[child] = rows(child, t[child].c.lease_id.in_(lease_ids)) if lease_ids else []
    structure_ids = [r["id"] for r in out["recovery_structures"]]
    out["recovery_structure_items"] = rows(
        "recovery_structure_items", t["recovery_structure_items"].c.recovery_structure_id.in_(structure_ids)
    ) if structure_ids else []
    return out


def _own_profiles(conn, valuation_id: str) -> list[dict]:
    t = _reflected(conn, "market_leasing_profiles")
    return [dict(r) for r in conn.execute(sa.select(t).where(t.c.valuation_id == valuation_id)).mappings()]


def _give_copy(conn, valuation_id: str, property_id: str, tables: dict[str, list[dict]]) -> None:
    """Insert a copy of `tables` owned by the valuation, replacing its profiles with re-pointed copies."""
    from src.services.valuation_clone import OWNED_TABLES, remap

    tables = {**tables, "market_leasing_profiles": _own_profiles(conn, valuation_id)}
    copied = remap(tables, valuation_id, property_id)
    conn.execute(sa.text("DELETE FROM market_leasing_profiles WHERE valuation_id = :v"), {"v": valuation_id})
    for name in OWNED_TABLES:
        if copied[name]:
            table = _reflected(conn, name)
            known = set(table.c.keys())
            conn.execute(sa.insert(table), [{k: v for k, v in r.items() if k in known} for r in copied[name]])


def _snapshot_tables(conn, snapshot_id: str | None) -> dict[str, list[dict]] | None:
    from src.services.valuation_snapshot import frozen_tables

    if not snapshot_id:
        return None
    raw = conn.execute(sa.text("SELECT inputs_json FROM valuation_snapshots WHERE id = :s"),
                       {"s": snapshot_id}).scalar()
    return frozen_tables(json.loads(raw)) if raw else None


def _tidy_tenants(conn) -> None:
    """Every tenant belongs to the property of the leases that use it (copied per property when
    shared); tenants no property uses and no lease uses are removed."""
    rows = conn.execute(sa.text(
        "SELECT DISTINCT t.id AS tenant_id, t.property_id AS tenant_property, s.property_id AS lease_property "
        "FROM leases l JOIN suites s ON s.id = l.suite_id JOIN tenants t ON t.id = l.tenant_id "
        "WHERE t.property_id IS NULL OR t.property_id != s.property_id"
    )).mappings().all()
    for r in rows:
        if r["tenant_property"] is None:
            # First property to use it takes it; later ones (if any) copy it on the next pass
            done = conn.execute(sa.text("UPDATE tenants SET property_id = :p WHERE id = :t AND property_id IS NULL"),
                                {"p": r["lease_property"], "t": r["tenant_id"]}).rowcount
            if done:
                continue
        new_id = str(uuid.uuid4())
        conn.execute(sa.text(
            "INSERT INTO tenants (id, property_id, name, credit_rating, industry, contact_name, contact_email, "
            "notes, comment, created_at, updated_at) SELECT :n, :p, name, credit_rating, industry, contact_name, "
            "contact_email, notes, comment, created_at, updated_at FROM tenants WHERE id = :t"
        ), {"n": new_id, "p": r["lease_property"], "t": r["tenant_id"]})
        conn.execute(sa.text(
            "UPDATE leases SET tenant_id = :n WHERE tenant_id = :t AND suite_id IN "
            "(SELECT id FROM suites WHERE property_id = :p)"
        ), {"n": new_id, "t": r["tenant_id"], "p": r["lease_property"]})
    conn.execute(sa.text(
        "DELETE FROM tenants WHERE property_id IS NULL AND id NOT IN "
        "(SELECT tenant_id FROM leases WHERE tenant_id IS NOT NULL)"
    ))


def _new_draft(conn, property_id: str, template_id: str | None, name: str, description: str) -> str:
    new_id = str(uuid.uuid4())
    if template_id:
        columns = [c["name"] for c in sa.inspect(conn).get_columns("valuations")
                   if c["name"] not in {"id", "name", "description", "status", "review_status", "snapshot_id",
                                        "error_message", "last_run_at", "prior_valuation_id"}
                   and not c["name"].startswith("result_")]
        cols = ", ".join(columns)
        conn.execute(sa.text(
            f"INSERT INTO valuations (id, name, description, status, review_status, {cols}) "
            f"SELECT :id, :name, :d, 'draft', 'draft', {cols} FROM valuations WHERE id = :src"
        ), {"id": new_id, "name": name, "d": description, "src": template_id})
    else:
        conn.execute(sa.text(
            "INSERT INTO valuations (id, property_id, name, status, review_status, discount_rate, exit_cap_rate, "
            "exit_cap_applied_to_year, exit_costs_pct, transfer_tax_preset, apply_stabilized_gross_up, "
            "capital_reserves_per_unit, use_mid_year_convention, description) VALUES (:id, :p, :name, 'draft', "
            "'draft', 0.08, 0.065, -1, 0.02, 'none', 1, 0, 0, :d)"
        ), {"id": new_id, "p": property_id, "name": name, "d": description})
    return new_id


def upgrade() -> None:
    conn = op.get_bind()
    with op.batch_alter_table("valuations") as batch:
        batch.add_column(sa.Column("self_storage_assumptions_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("prior_valuation_id", sa.String(36), nullable=True))
    for name in OWNED:
        with op.batch_alter_table(name) as batch:
            batch.add_column(sa.Column("valuation_id", sa.String(36), nullable=True))

    _tidy_tenants(conn)

    properties = conn.execute(sa.text(
        "SELECT id, property_type, analysis_start_date, analysis_period_months, " + ", ".join(MODELS)
        + " FROM properties"
    )).mappings().all()
    for prop in properties:
        pid = prop["id"]
        valuations = conn.execute(sa.text(
            "SELECT id, review_status, snapshot_id FROM valuations WHERE property_id = :p ORDER BY created_at, id"
        ), {"p": pid}).mappings().all()
        has_rows = any(conn.execute(sa.text(f"SELECT 1 FROM {n} WHERE property_id = :p LIMIT 1"), {"p": pid}).scalar()
                       for n in OWNED)
        drafts = [v for v in valuations if v["review_status"] == "draft"]
        if drafts:
            owner = drafts[-1]["id"]
        elif valuations or has_rows:
            owner = _new_draft(
                conn, pid, valuations[-1]["id"] if valuations else None,
                "Working model (migrated)" if valuations else "Model (migrated)",
                "Holds the property's current inputs when each valuation took its own model"
                + ("" if valuations else "; set the rates before relying on it"),
            )
        else:
            continue

        # Each valuation takes the property's dates (as its own) and operating model
        conn.execute(sa.text(
            "UPDATE valuations SET "
            "analysis_start_date_override = COALESCE(analysis_start_date_override, :start), "
            "analysis_period_months_override = COALESCE(analysis_period_months_override, :period), "
            + ", ".join(f"{m} = COALESCE(:{m}, {m})" for m in MODELS)
            + " WHERE property_id = :p"
        ), {"start": prop["analysis_start_date"], "p": pid,
            # Marina / seniors hold comes from the operating model's hold_years unless a valuation sets one
            "period": None if prop["property_type"] in ("marina", "seniors_housing") else prop["analysis_period_months"],
            **{m: prop[m] for m in MODELS}})

        live = _live_tables(conn, pid)
        for v in valuations:
            if v["id"] == owner:
                continue
            frozen = _snapshot_tables(conn, v["snapshot_id"]) if v["review_status"] != "draft" else None
            if frozen is not None:
                nested = conn.begin_nested()
                try:
                    _give_copy(conn, v["id"], pid, frozen)
                    nested.commit()
                    continue
                except Exception as exc:  # noqa: BLE001 - fall back to the live rows
                    nested.rollback()
                    print(f"valuation {v['id']}: snapshot rows could not be copied ({exc!s:.120}); "
                          "copied the property's current rows instead")
            _give_copy(conn, v["id"], pid, live)
        for name in OWNED:
            conn.execute(sa.text(f"UPDATE {name} SET valuation_id = :v WHERE property_id = :p AND valuation_id IS NULL"),
                         {"v": owner, "p": pid})

    for name in OWNED:
        with op.batch_alter_table(name) as batch:
            batch.alter_column("valuation_id", existing_type=sa.String(36), nullable=False)
            batch.create_foreign_key(f"fk_{name}_valuation_id", "valuations", ["valuation_id"], ["id"],
                                     ondelete="CASCADE")
            batch.create_index(f"ix_{name}_valuation_id", ["valuation_id"])
    with op.batch_alter_table("valuations") as batch:
        batch.create_foreign_key("fk_valuations_prior_valuation_id", "valuations", ["prior_valuation_id"], ["id"],
                                 ondelete="SET NULL")


def downgrade() -> None:
    raise NotImplementedError("Valuation-owned inputs cannot be merged back per property")
