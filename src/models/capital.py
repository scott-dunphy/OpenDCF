from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class PropertyCapitalProject(Base, UUIDPrimaryKey, TimestampMixin):
    """A scheduled building improvement / capital expenditure project."""
    __tablename__ = "property_capital_projects"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    # Owning valuation (docs/valuation-owned-inputs-plan.md); property_id groups it under its property
    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    start_date: Mapped[date] = mapped_column(Date)
    duration_months: Mapped[int] = mapped_column(Integer)

    property: Mapped["Property"] = relationship(viewonly=True)  # type: ignore[name-defined]
