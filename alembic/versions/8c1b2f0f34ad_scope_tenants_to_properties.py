"""scope_tenants_to_properties

Revision ID: 8c1b2f0f34ad
Revises: f2c3a94c6d21
Create Date: 2026-03-02 16:10:00.000000

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8c1b2f0f34ad"
down_revision: Union[str, None] = "f2c3a94c6d21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("property_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_tenants_property_id_properties",
            "properties",
            ["property_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_tenants_property_id", ["property_id"], unique=False)

    conn = op.get_bind()

    tenant_rows = conn.execute(sa.text("""
        SELECT id, name, credit_rating, industry, contact_name, contact_email, notes, comment
        FROM tenants
    """)).mappings().all()
    if not tenant_rows:
        return

    tenant_by_id = {str(r["id"]): r for r in tenant_rows}

    lease_rows = conn.execute(sa.text("""
        SELECT l.id AS lease_id, l.tenant_id AS tenant_id, s.property_id AS property_id
        FROM leases l
        JOIN suites s ON s.id = l.suite_id
        WHERE l.tenant_id IS NOT NULL
    """)).mappings().all()

    tenant_props: dict[str, set[str]] = {}
    for row in lease_rows:
        tenant_id = str(row["tenant_id"])
        property_id = str(row["property_id"])
        tenant_props.setdefault(tenant_id, set()).add(property_id)

    for tenant_id, properties in tenant_props.items():
        if not properties:
            continue
        property_ids = sorted(properties)
        canonical_property_id = property_ids[0]

        conn.execute(
            sa.text("UPDATE tenants SET property_id = :property_id WHERE id = :tenant_id"),
            {"property_id": canonical_property_id, "tenant_id": tenant_id},
        )

        # If a legacy tenant was used across multiple properties, clone the tenant
        # per property and remap leases so each tenant row is property-scoped.
        for prop_id in property_ids[1:]:
            source = tenant_by_id.get(tenant_id)
            if source is None:
                continue

            clone_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                    INSERT INTO tenants (
                        id, property_id, name, credit_rating, industry,
                        contact_name, contact_email, notes, comment
                    ) VALUES (
                        :id, :property_id, :name, :credit_rating, :industry,
                        :contact_name, :contact_email, :notes, :comment
                    )
                """),
                {
                    "id": clone_id,
                    "property_id": prop_id,
                    "name": source["name"],
                    "credit_rating": source["credit_rating"],
                    "industry": source["industry"],
                    "contact_name": source["contact_name"],
                    "contact_email": source["contact_email"],
                    "notes": source["notes"],
                    "comment": source["comment"],
                },
            )

            conn.execute(
                sa.text("""
                    UPDATE leases
                    SET tenant_id = :clone_id
                    WHERE tenant_id = :tenant_id
                      AND suite_id IN (
                          SELECT id FROM suites WHERE property_id = :property_id
                      )
                """),
                {"clone_id": clone_id, "tenant_id": tenant_id, "property_id": prop_id},
            )


def downgrade() -> None:
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.drop_index("ix_tenants_property_id")
        batch_op.drop_constraint("fk_tenants_property_id_properties", type_="foreignkey")
        batch_op.drop_column("property_id")
