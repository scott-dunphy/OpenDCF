from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
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
    property_type: Mapped[str] = mapped_column(String(50))   # PropertyType enum value
    total_area: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    area_unit: Mapped[str] = mapped_column(String(10))       # AreaUnit enum value
    year_built: Mapped[int | None] = mapped_column(Integer)
    analysis_start_date: Mapped[date] = mapped_column(Date)
    analysis_period_months: Mapped[int] = mapped_column(Integer, default=120)
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, default=12)
    comment: Mapped[str | None] = mapped_column(Text)

    suites: Mapped[list["Suite"]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )
    market_leasing_profiles: Mapped[list["MarketLeasingProfile"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )
    property_expenses: Mapped[list["PropertyExpense"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )
    valuations: Mapped[list["Valuation"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )
    recovery_structures: Mapped[list["RecoveryStructure"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )
    capital_projects: Mapped[list["PropertyCapitalProject"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )
    other_income_items: Mapped[list["PropertyOtherIncome"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )
    tenants: Mapped[list["Tenant"]] = relationship(  # type: ignore[name-defined]
        back_populates="property", cascade="all, delete-orphan"
    )


class Suite(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "suites"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    suite_name: Mapped[str] = mapped_column(String(100))
    floor: Mapped[int | None] = mapped_column(Integer)
    area: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    space_type: Mapped[str] = mapped_column(String(100))  # e.g. "office", "retail", "1BR"
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(Text)
    market_leasing_profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("market_leasing_profiles.id", ondelete="SET NULL"),
        nullable=True, default=None
    )

    property: Mapped["Property"] = relationship(back_populates="suites")
    leases: Mapped[list["Lease"]] = relationship(  # type: ignore[name-defined]
        back_populates="suite", cascade="all, delete-orphan"
    )
    market_leasing_profile: Mapped["MarketLeasingProfile | None"] = relationship(  # type: ignore[name-defined]
        foreign_keys=[market_leasing_profile_id]
    )
