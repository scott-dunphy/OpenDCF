from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class PropertyExpense(Base, UUIDPrimaryKey, TimestampMixin):
    """Operating expense line item for a property."""
    __tablename__ = "property_expenses"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    category: Mapped[str] = mapped_column(String(50))  # standard or custom category label
    description: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    base_year_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # total $ for year 1
    growth_rate_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.03"))

    is_recoverable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_gross_up_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    gross_up_vacancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # e.g. 0.95

    # Management fee: can be expressed as % of EGI instead of fixed amount
    is_pct_of_egi: Mapped[bool] = mapped_column(Boolean, default=False)
    pct_of_egi: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # e.g. 0.04

    property: Mapped["Property"] = relationship(back_populates="property_expenses")  # type: ignore[name-defined]
