from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class PropertyOtherIncome(Base, UUIDPrimaryKey, TimestampMixin):
    """A revenue line item beyond base rent (parking, antenna, storage, etc.)."""
    __tablename__ = "property_other_income"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    category: Mapped[str] = mapped_column(String(100))  # free text
    description: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    base_year_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    growth_rate_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.03"))

    property: Mapped["Property"] = relationship(back_populates="other_income_items")  # type: ignore[name-defined]
