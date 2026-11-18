from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey
from src.schemas.common import EscalationType, LeaseType, RecoveryType


class Tenant(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "tenants"

    property_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=True
    )
    # Owning valuation (docs/valuation-owned-inputs-plan.md); property_id groups it under its property
    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    credit_rating: Mapped[str | None] = mapped_column(String(20))
    industry: Mapped[str | None] = mapped_column(String(100))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)

    property: Mapped["Property | None"] = relationship(viewonly=True)  # type: ignore[name-defined]
    leases: Mapped[list["Lease"]] = relationship(back_populates="tenant")


class Lease(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "leases"

    suite_id: Mapped[str] = mapped_column(String(36), ForeignKey("suites.id"))
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=True)
    lease_type: Mapped[str] = mapped_column(String(30), default=LeaseType.IN_PLACE.value)

    lease_start_date: Mapped[date] = mapped_column(Date)
    lease_end_date: Mapped[date] = mapped_column(Date)

    # Base rent — $/SF/year for commercial, $/unit/month for multifamily/storage
    base_rent_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    rent_payment_frequency: Mapped[str] = mapped_column(String(20), default="annual")
    # "per_area" ($ x area) or "total" (the whole lease's $ amount, e.g. an antenna on 0 SF)
    rent_basis: Mapped[str] = mapped_column(String(20), default="per_area", server_default="per_area")

    # Escalation
    escalation_type: Mapped[str] = mapped_column(String(30), default=EscalationType.FLAT.value)
    escalation_pct_annual: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # e.g. 0.03
    cpi_floor: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cpi_cap: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Expense recovery
    recovery_type: Mapped[str] = mapped_column(String(30), default=RecoveryType.NNN.value)
    pro_rata_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # override auto-calc
    base_year: Mapped[int | None] = mapped_column(Integer)
    base_year_stop_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # $ total for base_year_stop
    expense_stop_per_sf: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))   # $/SF for modified_gross

    # Percentage rent (retail)
    pct_rent_breakpoint: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    pct_rent_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))   # e.g. 0.06
    projected_annual_sales_per_sf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))

    # Renewal override (if None, uses market leasing profile)
    renewal_probability: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    renewal_rent_spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    # Credit tenant: excluded from general vacancy and credit loss
    exclude_from_general_vacancy: Mapped[bool] = mapped_column(Boolean, default=False)
    # published DCF software "Exclude upon rollover": off carries the exclusion to the market leases that follow
    vacancy_exclusion_ends_at_rollover: Mapped[bool] = mapped_column(Boolean, default=True)

    # Upon expiration (market | renew | vacate | option | reabsorb) and option terms
    upon_expiration: Mapped[str] = mapped_column(String(20), default="market")
    option_rent_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))  # None = market
    option_term_months: Mapped[int | None] = mapped_column(Integer)
    option_ti_per_sf: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    option_lc_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))

    # Committed (contractual, unpaid) leasing costs, $ total
    committed_ti_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    committed_lc_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    comment: Mapped[str | None] = mapped_column(Text)
    recovery_structure_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("recovery_structures.id", ondelete="SET NULL"),
        nullable=True, default=None
    )

    suite: Mapped["Suite"] = relationship(back_populates="leases")  # type: ignore[name-defined]
    tenant: Mapped["Tenant | None"] = relationship(back_populates="leases")
    recovery_structure: Mapped["RecoveryStructure | None"] = relationship(  # type: ignore[name-defined]
        foreign_keys=[recovery_structure_id]
    )
    rent_steps: Mapped[list["RentStep"]] = relationship(
        back_populates="lease", cascade="all, delete-orphan"
    )
    free_rent_periods: Mapped[list["FreeRentPeriod"]] = relationship(
        back_populates="lease", cascade="all, delete-orphan"
    )
    expense_recovery_overrides: Mapped[list["LeaseExpenseRecovery"]] = relationship(
        back_populates="lease", cascade="all, delete-orphan"
    )


class RentStep(Base, UUIDPrimaryKey):
    """Explicit rent amount at a specific date (for FIXED_STEP escalation)."""
    __tablename__ = "rent_steps"

    lease_id: Mapped[str] = mapped_column(String(36), ForeignKey("leases.id"))
    effective_date: Mapped[date] = mapped_column(Date)
    rent_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    comment: Mapped[str | None] = mapped_column(Text)

    lease: Mapped["Lease"] = relationship(back_populates="rent_steps")


class FreeRentPeriod(Base, UUIDPrimaryKey):
    """Period of rent abatement at lease commencement (or mid-lease)."""
    __tablename__ = "free_rent_periods"

    lease_id: Mapped[str] = mapped_column(String(36), ForeignKey("leases.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    applies_to_base_rent: Mapped[bool] = mapped_column(Boolean, default=True)
    applies_to_recoveries: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str | None] = mapped_column(Text)

    lease: Mapped["Lease"] = relationship(back_populates="free_rent_periods")


class LeaseExpenseRecovery(Base, UUIDPrimaryKey):
    """Per-lease override of expense recovery terms for a specific expense category."""
    __tablename__ = "lease_expense_recoveries"

    lease_id: Mapped[str] = mapped_column(String(36), ForeignKey("leases.id"))
    expense_category: Mapped[str] = mapped_column(String(50))
    recovery_type: Mapped[str] = mapped_column(String(30))
    base_year_stop_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cap_per_sf_annual: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    floor_per_sf_annual: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    admin_fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # e.g. 0.15
    # Categories sharing a cap group share one cap; recovery growth capped from the lease start year
    cap_group: Mapped[str | None] = mapped_column(String(50))
    cap_growth_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    # Modified gross: this category alone recovers its $/SF above this stop
    expense_stop_per_sf: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    comment: Mapped[str | None] = mapped_column(Text)

    lease: Mapped["Lease"] = relationship(back_populates="expense_recovery_overrides")
