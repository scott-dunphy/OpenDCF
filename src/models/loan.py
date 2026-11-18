from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class MortgageLoan(Base, UUIDPrimaryKey, TimestampMixin):
    """
    A commercial mortgage loan held by the lender, secured by a property.
    Terms are as of origination; the schedule is rolled forward to each
    risk run's as-of date. Several loans (lien positions) can share a property.
    """
    __tablename__ = "mortgage_loans"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"))
    external_id: Mapped[str | None] = mapped_column(String(100), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    portfolio_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True
    )
    lien_position: Mapped[int] = mapped_column(Integer, default=1)        # 1 = senior
    sponsor: Mapped[str | None] = mapped_column(String(255))
    recourse: Mapped[bool] = mapped_column(Boolean, default=False)

    # Terms
    origination_date: Mapped[date] = mapped_column(Date)
    original_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    maturity_date: Mapped[date] = mapped_column(Date)
    rate_type: Mapped[str] = mapped_column(String(20), default="fixed")   # fixed | floating
    coupon: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    index_name: Mapped[str | None] = mapped_column(String(30))            # e.g. SOFR
    spread: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    index_floor: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    index_cap: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    amortization_months: Mapped[int | None] = mapped_column(Integer)     # null/0 = full IO
    io_months: Mapped[int] = mapped_column(Integer, default=0)
    extension_count: Mapped[int] = mapped_column(Integer, default=0)
    extension_months: Mapped[int] = mapped_column(Integer, default=0)

    # Loan tape (current)
    reported_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    balance_as_of_date: Mapped[date | None] = mapped_column(Date)
    delinquency_status: Mapped[str] = mapped_column(String(20), default="current")

    # At origination (reporting)
    origination_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    origination_noi: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))

    # Tape collateral, used when the property has no full model
    tape_noi: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))         # current annual NOI
    tape_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tape_value_date: Mapped[date | None] = mapped_column(Date)
    tape_occupancy: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    tape_noi_growth: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    tape_exit_cap_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))   # base cap rate for future values

    comment: Mapped[str | None] = mapped_column(Text)


class RiskParameterSet(Base, UUIDPrimaryKey, TimestampMixin):
    """Named, versioned Monte Carlo settings; runs keep a snapshot of the version used."""
    __tablename__ = "risk_parameter_sets"

    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    comment: Mapped[str | None] = mapped_column(Text)


class LoanRiskRun(Base, UUIDPrimaryKey, TimestampMixin):
    """A Monte Carlo run over the loan book (or one portfolio's loans) at an as-of date."""
    __tablename__ = "loan_risk_runs"

    name: Mapped[str | None] = mapped_column(String(255))
    as_of_date: Mapped[date] = mapped_column(Date)
    portfolio_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True
    )
    parameter_set_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("risk_parameter_sets.id", ondelete="SET NULL"), nullable=True
    )
    parameter_set_version: Mapped[int | None] = mapped_column(Integer)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | completed | failed
    progress: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal(0))
    error_message: Mapped[str | None] = mapped_column(Text)
    results_json: Mapped[str | None] = mapped_column(Text)
    # Loan terms and collateral exactly as used, so the run can be audited and reproduced
    inputs_json: Mapped[str | None] = mapped_column(Text)


class CollateralSimulation(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Monte Carlo valuation of one property: the full engine run on every simulated path.
    Reused by later valuation and loan risk runs while the property's inputs, the
    simulation settings and the horizon are unchanged (matched by inputs_hash).
    """
    __tablename__ = "collateral_simulations"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    valuation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(20), default="valuation")   # valuation | loan_risk
    analysis_start: Mapped[date] = mapped_column(Date)
    horizon_months: Mapped[int] = mapped_column(Integer)
    num_paths: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    parameter_set_id: Mapped[str | None] = mapped_column(String(36))
    parameter_set_version: Mapped[int | None] = mapped_column(Integer)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    inputs_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")   # queued | running | completed | failed
    progress: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal(0))
    error_message: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)
    paths_blob: Mapped[bytes | None] = mapped_column(LargeBinary)        # compressed numpy arrays per path
