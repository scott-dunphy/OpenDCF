from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPrimaryKey


class AuditLog(Base, UUIDPrimaryKey):
    """
    Append-only record of every create, update and delete of an input row
    (properties, leases, expenses, valuations, loans, parameter sets, ...).
    Written by the session flush hook in src.services.audit.
    """
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)

    entity_type: Mapped[str] = mapped_column(String(64))           # table name
    entity_id: Mapped[str] = mapped_column(String(36))
    property_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(10))                 # create | update | delete
    changes_json: Mapped[str] = mapped_column(Text)                 # {field: [before, after]}
    source: Mapped[str | None] = mapped_column(String(255))         # e.g. "PUT /api/v1/loans/..."
    # Python-side default: microsecond resolution keeps entries in order (SQLite's now() is per second)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), index=True
    )


class RiskParameterSetVersion(Base, UUIDPrimaryKey):
    """Every saved version of a risk parameter set, kept for reproducibility."""
    __tablename__ = "risk_parameter_set_versions"

    parameter_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("risk_parameter_sets.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    params_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
