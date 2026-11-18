from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey
from src.schemas.common import AreaUnit, PropertyType


class Property(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "properties"

    name: Mapped[str] = mapped_column(String(255))
    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    zip_code: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    market: Mapped[str | None] = mapped_column(
        String(100)
    )  # e.g. MSA; used for assumption matching
    external_id: Mapped[str | None] = mapped_column(
        String(100)
    )  # source system id (e.g. PUBLISHED Property_ExternalID)
    property_type: Mapped[str] = mapped_column(String(50))  # PropertyType enum value
    total_area: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    area_unit: Mapped[str] = mapped_column(String(10))  # AreaUnit enum value
    year_built: Mapped[int | None] = mapped_column(Integer)
    analysis_start_date: Mapped[date] = mapped_column(Date)
    analysis_period_months: Mapped[int] = mapped_column(Integer, default=120)
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, default=12)
    ownership_pct: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("1.0"))
    comment: Mapped[str | None] = mapped_column(Text)
    amenities: Mapped[dict] = mapped_column(JSON, default=dict)
    # Legacy: operating models now live on each valuation (docs/valuation-owned-inputs-plan.md)
    marina_assumptions_json: Mapped[str | None] = mapped_column(Text)
    seniors_housing_assumptions_json: Mapped[str | None] = mapped_column(Text)
    # Self storage unit mix, rates, churn, ECRI and ancillary income (src.schemas.self_storage)
    self_storage_assumptions_json: Mapped[str | None] = mapped_column(Text)
    # Census CBSA (src/services/cbsa.py), filled from the ZIP when not chosen; keys the assumptions library
    cbsa_code: Mapped[str | None] = mapped_column(String(5))
    # 1-5 (5 = best, 3 = market base): positions library values inside their low/high ranges
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    # Legacy: staleness is tracked per valuation (valuations.inputs_updated_at)
    inputs_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Modeling inputs below are owned by the property's valuations (deleted with them); read-only here
    suites: Mapped[list["Suite"]] = relationship(
        viewonly=True
    )
    # Owned by the property's valuations (deleted with them); read-only from here
    market_leasing_profiles: Mapped[list["MarketLeasingProfile"]] = relationship(  # type: ignore[name-defined]
        viewonly=True
    )
    property_expenses: Mapped[list["PropertyExpense"]] = relationship(  # type: ignore[name-defined]
        viewonly=True
    )
    valuations: Mapped[list["Valuation"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )
    recovery_structures: Mapped[list["RecoveryStructure"]] = relationship(  # type: ignore[name-defined]
        viewonly=True
    )
    recovery_pools: Mapped[list["RecoveryPool"]] = relationship(  # type: ignore[name-defined]
        viewonly=True
    )
    capital_projects: Mapped[list["PropertyCapitalProject"]] = relationship(  # type: ignore[name-defined]
        viewonly=True
    )
    other_income_items: Mapped[list["PropertyOtherIncome"]] = relationship(  # type: ignore[name-defined]
        viewonly=True
    )
    tenants: Mapped[list["Tenant"]] = relationship(  # type: ignore[name-defined]
        viewonly=True
    )



@event.listens_for(Property, "before_insert")
def _fill_cbsa(_mapper, _connection, target: Property) -> None:
    """Every new property gets a census market when its address identifies one."""
    if not target.cbsa_code:
        from src.services.cbsa import for_property

        target.cbsa_code = for_property(target.zip_code, target.market, target.city, target.state)

class Suite(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "suites"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    # Owning valuation (docs/valuation-owned-inputs-plan.md); property_id groups it under its property
    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    suite_name: Mapped[str] = mapped_column(String(100))
    floor: Mapped[int | None] = mapped_column(Integer)
    area: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    space_type: Mapped[str] = mapped_column(String(100))  # e.g. "office", "retail", "1BR"
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(Text)
    # Re-lease under another space type's market assumptions (in every valuation); None = own type
    market_space_type: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    # Lease-up for vacant space (also applies when a lease is reabsorbed). Active when either is set.
    absorption_start_date: Mapped[date | None] = mapped_column(Date)  # leasing begins
    lease_up_months: Mapped[int | None] = mapped_column(
        Integer
    )  # months to commencement; None = MLA downtime

    property: Mapped["Property"] = relationship(viewonly=True)
    leases: Mapped[list["Lease"]] = relationship(  # type: ignore[name-defined]
        back_populates="suite", cascade="all, delete-orphan"
    )
