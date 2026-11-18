from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, DecimalList, TimestampMixin, UUIDPrimaryKey


class PropertyOtherIncome(Base, UUIDPrimaryKey, TimestampMixin):
    """A revenue line item beyond base rent (parking, antenna, storage, etc.)."""
    __tablename__ = "property_other_income"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    # Owning valuation (docs/valuation-owned-inputs-plan.md); property_id groups it under its property
    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(100))  # free text
    description: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    base_year_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    growth_rate_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.03"))
    growth_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)  # year-by-year
    # Optional $ by year (Year 1, 2, ...); replaces base amount and growth for those years, and
    # later years grow from the last amount at the growth rate
    amount_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)

    property: Mapped["Property"] = relationship(viewonly=True)  # type: ignore[name-defined]
