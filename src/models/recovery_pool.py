from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class RecoveryPool(Base, UUIDPrimaryKey, TimestampMixin):
    """Expense lines recovered together over one share denominator (see engine.recovery_pools)."""
    __tablename__ = "recovery_pools"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    # Owning valuation (docs/valuation-owned-inputs-plan.md); property_id groups it under its property
    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    expense_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    # property_area (less excluded suites) | fixed_area | occupied_area
    denominator: Mapped[str] = mapped_column(String(20), default="property_area")
    fixed_area: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    minimum_occupancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    excluded_suite_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    deduct_excluded_recoveries: Mapped[bool] = mapped_column(Boolean, default=True)

    property: Mapped["Property"] = relationship(viewonly=True)  # type: ignore[name-defined]
