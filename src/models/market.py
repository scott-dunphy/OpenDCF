from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class MarketLeasingProfile(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Market leasing assumptions for a specific space type within a property.
    Used for speculative (post-expiry) lease projection.
    One profile per property per space_type.
    """
    __tablename__ = "market_leasing_profiles"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    space_type: Mapped[str] = mapped_column(String(100))  # must match Suite.space_type
    description: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)

    # Market rent
    market_rent_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 6))  # $/SF/yr or $/unit/mo
    rent_growth_rate_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6))  # annual, e.g. 0.03

    # New tenant assumptions
    new_lease_term_months: Mapped[int] = mapped_column(Integer, default=60)
    new_tenant_ti_per_sf: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    new_tenant_lc_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.06"))  # of total lease value
    new_tenant_free_rent_months: Mapped[int] = mapped_column(Integer, default=0)
    downtime_months: Mapped[int] = mapped_column(Integer, default=3)

    # Renewal assumptions
    renewal_probability: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.65"))
    renewal_lease_term_months: Mapped[int] = mapped_column(Integer, default=60)
    renewal_ti_per_sf: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    renewal_lc_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.03"))
    renewal_free_rent_months: Mapped[int] = mapped_column(Integer, default=0)
    renewal_rent_adjustment_pct: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=Decimal("0")
    )  # vs market, e.g. -0.05 = 5% below market

    # Structural vacancy
    general_vacancy_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.05"))
    credit_loss_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.01"))

    # Unit-type concession timing controls (multifamily/self-storage)
    concession_timing_mode: Mapped[str] = mapped_column(String(20), default="blended")
    concession_year1_months: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    concession_year2_months: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    concession_year3_months: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    concession_year4_months: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    concession_year5_months: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    concession_stabilized_months: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    property: Mapped["Property"] = relationship(back_populates="market_leasing_profiles")  # type: ignore[name-defined]
