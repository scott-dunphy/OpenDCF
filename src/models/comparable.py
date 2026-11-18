from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class ComparableSale(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "comparable_sales"

    external_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    property_name: Mapped[str] = mapped_column(String(255))
    sale_date: Mapped[date] = mapped_column(Date, index=True)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    property_type: Mapped[str] = mapped_column(String(50), index=True)
    property_subtype: Mapped[str | None] = mapped_column(String(100))
    area: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    area_unit: Mapped[str] = mapped_column(String(10), default="sf")
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    market: Mapped[str | None] = mapped_column(String(100), index=True)
    submarket: Mapped[str | None] = mapped_column(String(100))
    year_built: Mapped[int | None] = mapped_column(Integer)
    year_renovated: Mapped[int | None] = mapped_column(Integer)
    occupancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    normalized_noi: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    amenities: Mapped[dict] = mapped_column(JSON, default=dict)
    is_distressed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_portfolio_sale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_partial_interest: Mapped[bool] = mapped_column(Boolean, default=False)
    financing_terms: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified")
    notes: Mapped[str | None] = mapped_column(Text)

    selections: Mapped[list["ComparableSelection"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )


class ComparableSelection(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "comparable_selections"
    __table_args__ = (UniqueConstraint("property_id", "sale_id"),)

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"))
    sale_id: Mapped[str] = mapped_column(String(36), ForeignKey("comparable_sales.id", ondelete="CASCADE"))
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("1"))
    adjustments: Mapped[dict] = mapped_column(JSON, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text)

    sale: Mapped[ComparableSale] = relationship(back_populates="selections")
