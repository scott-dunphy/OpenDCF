from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from src.models.base import Base, DecimalList, LoanList, TimestampMixin, UUIDPrimaryKey, json_safe_loans
from src.schemas.common import ValuationStatus


class Valuation(Base, UUIDPrimaryKey, TimestampMixin):
    """
    A DCF valuation run for a property.
    Stores both the input assumptions and the computed results.
    """
    __tablename__ = "valuations"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    analysis_start_date_override: Mapped[date | None] = mapped_column(Date)
    # Hold period for this valuation; None = the property's analysis_period_months
    analysis_period_months_override: Mapped[int | None] = mapped_column(Integer)
    basis_of_value: Mapped[str] = mapped_column(String(32), default="market_value")
    intended_use: Mapped[str | None] = mapped_column(String(255))
    risk_treatment: Mapped[str] = mapped_column(String(32), default="deterministic")
    cash_flow_basis: Mapped[str] = mapped_column(String(16), default="nominal")
    discount_rate_basis: Mapped[str] = mapped_column(String(16), default="nominal")
    status: Mapped[str] = mapped_column(String(20), default=ValuationStatus.DRAFT.value)
    # Review lifecycle (docs/valuation-lifecycle-plan.md): draft -> in_review -> approved. Anything
    # but draft is frozen: its inputs and results live in the snapshot named by snapshot_id.
    review_status: Mapped[str] = mapped_column(String(20), default="draft")
    snapshot_id: Mapped[str | None] = mapped_column(String(36))  # valuation_snapshots.id
    error_message: Mapped[str | None] = mapped_column(Text)
    ai_permission_mode: Mapped[str] = mapped_column(String(20), default="confirm")

    # === DCF Assumptions ===
    discount_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6))         # e.g. 0.08
    exit_cap_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6))         # e.g. 0.065
    # Which year's NOI to capitalize: -1 = forward year (last + 1), or specific year number
    exit_cap_applied_to_year: Mapped[int] = mapped_column(Integer, default=-1)
    exit_costs_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.02"))
    transfer_tax_preset: Mapped[str] = mapped_column(String(64), default="none")
    transfer_tax_custom_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    apply_stabilized_gross_up: Mapped[bool] = mapped_column(default=True)
    stabilized_occupancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    capital_reserves_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0.25")
    )  # $/SF/yr or $/unit/yr
    capital_reserves_growth_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    use_mid_year_convention: Mapped[bool] = mapped_column(default=False)
    terminal_timing: Mapped[str] = mapped_column(String(20), default="end_of_period")
    # CPI for CPI-escalated leases: single rate (None = 2.5%) or year-by-year table
    cpi_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cpi_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    # Count modeled downtime/absorption vacancy toward the general vacancy rate
    reduce_general_vacancy_by_downtime: Mapped[bool] = mapped_column(default=False)
    # Calculate and floor general vacancy annually or separately for each month
    vacancy_calculation_frequency: Mapped[str] = mapped_column(String(16), default="annual")
    # General vacancy and credit loss on gross revenue (rent + recoveries + other) instead of rent
    vacancy_on_gross_revenue: Mapped[bool] = mapped_column(default=False)
    # Credit loss on tenant revenue (rent, recoveries, percentage rent), not other income
    credit_loss_on_tenant_revenue: Mapped[bool] = mapped_column(default=False)
    # Recoveries billed on calendar years (expenses inflated on fiscal years)
    calendar_year_recoveries: Mapped[bool] = mapped_column(default=False)
    # Reversion NOI adjusted for full occupancy at the stabilized vacancy rate (published DCF software)
    exit_noi_full_occupancy: Mapped[bool] = mapped_column(default=False)
    exit_stabilized_vacancy_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))

    # === Optional Debt ===
    loan_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    amortization_months: Mapped[int | None] = mapped_column(Integer)
    loan_term_months: Mapped[int | None] = mapped_column(Integer)
    io_period_months: Mapped[int | None] = mapped_column(Integer, default=0)
    loan_fees_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    # Second mortgage, mezzanine, etc.: [{loan_amount, interest_rate, amortization_months,
    # loan_term_months, io_period_months, loan_fees_pct, label}], all funded at close
    additional_loans: Mapped[list[dict]] = mapped_column(LoanList, nullable=True, default=list)

    @validates("additional_loans")
    def _json_safe_loans(self, _key, value):
        # Audit entries serialize the attribute before it is stored
        return json_safe_loans(value)

    # === Acquisition / returns ===
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    acquisition_costs_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    direct_cap_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    exit_deduct_forward_capital: Mapped[bool] = mapped_column(default=False)
    exit_add_back_free_rent: Mapped[bool] = mapped_column(default=False)
    exit_deduct_forward_free_rent: Mapped[bool] = mapped_column(default=False)
    exit_deduct_forward_leasing_costs: Mapped[bool] = mapped_column(default=False)
    exit_costs_on_adjusted_gross: Mapped[bool] = mapped_column(default=False)

    # === Results (populated after engine run) ===
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Stamped when any of this valuation's inputs change (src.services.input_tracking)
    inputs_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # src.engine.ENGINE_VERSION the results were calculated with (NULL: before versioning)
    result_engine_version: Mapped[int | None] = mapped_column(Integer)
    result_npv: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_irr: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    result_going_in_cap_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    result_exit_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_pv_cash_flows: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    result_pv_terminal_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    result_equity_multiple: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    result_avg_occupancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    result_terminal_noi_basis: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_gross_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_exit_costs_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_transfer_tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_transfer_tax_preset: Mapped[str | None] = mapped_column(String(64))
    result_terminal_capital_deduction_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_direct_cap_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_levered_irr: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    result_returns_json: Mapped[str | None] = mapped_column(Text)
    # === Operating models (marina slips, seniors unit mix, self storage unit mix) ===
    marina_assumptions_json: Mapped[str | None] = mapped_column(Text)
    seniors_housing_assumptions_json: Mapped[str | None] = mapped_column(Text)
    self_storage_assumptions_json: Mapped[str | None] = mapped_column(Text)
    # Rolled forward from this valuation (POST /valuations/{id}/roll-forward)
    prior_valuation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="SET NULL")
    )

    # === Results (JSON blobs) ===
    result_cash_flows_json: Mapped[str | None] = mapped_column(Text)
    result_tenant_cash_flows_json: Mapped[str | None] = mapped_column(Text)
    result_recovery_audit_json: Mapped[str | None] = mapped_column(Text)

    property: Mapped["Property"] = relationship(back_populates="valuations", foreign_keys=[property_id])  # type: ignore[name-defined]
    market_leasing_profiles: Mapped[list["MarketLeasingProfile"]] = relationship(  # type: ignore[name-defined]
        back_populates="valuation", cascade="all, delete-orphan", passive_deletes=True
    )
    # The valuation's own model; property_id on these rows only groups them
    suites: Mapped[list["Suite"]] = relationship(  # type: ignore[name-defined]
        cascade="all, delete-orphan", foreign_keys="Suite.valuation_id"
    )
    tenants: Mapped[list["Tenant"]] = relationship(  # type: ignore[name-defined]
        cascade="all, delete-orphan", foreign_keys="Tenant.valuation_id"
    )
    property_expenses: Mapped[list["PropertyExpense"]] = relationship(  # type: ignore[name-defined]
        cascade="all, delete-orphan", foreign_keys="PropertyExpense.valuation_id"
    )
    other_income_items: Mapped[list["PropertyOtherIncome"]] = relationship(  # type: ignore[name-defined]
        cascade="all, delete-orphan", foreign_keys="PropertyOtherIncome.valuation_id"
    )
    capital_projects: Mapped[list["PropertyCapitalProject"]] = relationship(  # type: ignore[name-defined]
        cascade="all, delete-orphan", foreign_keys="PropertyCapitalProject.valuation_id"
    )
    recovery_structures: Mapped[list["RecoveryStructure"]] = relationship(  # type: ignore[name-defined]
        cascade="all, delete-orphan", foreign_keys="RecoveryStructure.valuation_id"
    )
    recovery_pools: Mapped[list["RecoveryPool"]] = relationship(  # type: ignore[name-defined]
        cascade="all, delete-orphan", foreign_keys="RecoveryPool.valuation_id"
    )


class ValuationSnapshot(Base, UUIDPrimaryKey, TimestampMixin):
    """A valuation frozen for review: every input row it ran on and the results it produced.
    Never changed after it is written except for its review trail."""

    __tablename__ = "valuation_snapshots"

    valuation_id: Mapped[str] = mapped_column(String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True)
    # in_review | approved | reopened
    status: Mapped[str] = mapped_column(String(20), default="in_review")
    inputs_json: Mapped[str] = mapped_column(Text)        # services/valuation_snapshot.capture
    results_json: Mapped[str] = mapped_column(Text)       # the results response as reviewed, less the recovery audit
    recovery_audit_json: Mapped[str | None] = mapped_column(Text)  # can be ~100k rows; read only when asked for
    schema_revision: Mapped[str | None] = mapped_column(String(32))  # alembic head when frozen
    result_npv: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # Date of value: the day before the analysis starts (start 2026-10-01 = value as of 2026-09-30)
    value_date: Mapped[date] = mapped_column(Date)
    engine_version: Mapped[str] = mapped_column(String(64))
    submitted_by: Mapped[str] = mapped_column(String(120))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submit_note: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approve_note: Mapped[str | None] = mapped_column(Text)
    reopened_by: Mapped[str | None] = mapped_column(String(120))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopen_reason: Mapped[str | None] = mapped_column(Text)
