from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey
from src.schemas.common import EscalationType, LeaseType, RecoveryType


class Tenant(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255))
    credit_rating: Mapped[str | None] = mapped_column(String(20))
    industry: Mapped[str | None] = mapped_column(String(100))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)

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
    rent_payment_frequency: Mapped[str] = mapped_column(String(20), default="monthly")

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
    comment: Mapped[str | None] = mapped_column(Text)

    lease: Mapped["Lease"] = relationship(back_populates="expense_recovery_overrides")
