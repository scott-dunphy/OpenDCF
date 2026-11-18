from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, DecimalList, TimestampMixin, UUIDPrimaryKey


class PropertyExpense(Base, UUIDPrimaryKey, TimestampMixin):
    """Operating expense line item for a property."""
    __tablename__ = "property_expenses"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    # Owning valuation (docs/valuation-owned-inputs-plan.md); property_id groups it under its property
    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(50))  # standard or custom category label
    description: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    base_year_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # Year 1 amount, see amount_basis
    # "total" = $ for the property; "per_area" = $/SF/yr or $/unit/yr times property total_area
    amount_basis: Mapped[str] = mapped_column(String(20), default="total")
    # Share that varies with occupancy (0 = amount used as entered; >0 = amount stated at 100% occupancy)
    variable_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    growth_rate_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.03"))
    growth_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)  # year-by-year
    # Optional amounts by year (Year 1, 2, ...) in amount_basis; replaces base amount and growth for
    # those years, and later years grow from the last amount at the growth rate
    amount_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)

    is_recoverable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_gross_up_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    gross_up_vacancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # e.g. 0.95

    # Management fee: can be expressed as % of EGI instead of fixed amount
    is_pct_of_egi: Mapped[bool] = mapped_column(Boolean, default=False)
    pct_of_egi: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # e.g. 0.04

    property: Mapped["Property"] = relationship(viewonly=True)  # type: ignore[name-defined]
