"""Assumptions library: CBSA and quality on properties; scope, ranges and provenance on profiles

Revision ID: e5c1a9f3b2d7
Revises: d2a7b9e4c518
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "e5c1a9f3b2d7"
down_revision = "d2a7b9e4c518"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("cbsa_code", sa.String(5), nullable=True))
        batch.add_column(sa.Column("quality_score", sa.Numeric(3, 1), nullable=True))
    with op.batch_alter_table("assumption_profiles") as batch:
        batch.add_column(sa.Column("cbsa_code", sa.String(5), nullable=True))
        batch.add_column(sa.Column("state", sa.String(2), nullable=True))
        batch.add_column(sa.Column("quality_score", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("as_of", sa.Date(), nullable=True))
        batch.add_column(sa.Column("source", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ranges_json", sa.Text(), nullable=False, server_default="{}"))

    # Backfill each property's CBSA from its ZIP, else an unambiguous market name, else city + state
    from src.services import cbsa

    conn = op.get_bind()
    props = sa.table("properties", sa.column("id"), sa.column("zip_code"), sa.column("market"),
                     sa.column("city"), sa.column("state"), sa.column("cbsa_code"))
    rows = conn.execute(sa.select(props.c.id, props.c.zip_code, props.c.market, props.c.city, props.c.state))
    for pid, zip_code, market, city, state in rows.fetchall():
        code = cbsa.for_property(zip_code, market, city, state)
        if code:
            conn.execute(props.update().where(props.c.id == pid).values(cbsa_code=code))


def downgrade() -> None:
    with op.batch_alter_table("assumption_profiles") as batch:
        for col in ("ranges_json", "source", "as_of", "quality_score", "state", "cbsa_code"):
            batch.drop_column(col)
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("quality_score")
        batch.drop_column("cbsa_code")
