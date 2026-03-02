from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey
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
    status: Mapped[str] = mapped_column(String(20), default=ValuationStatus.DRAFT.value)
    error_message: Mapped[str | None] = mapped_column(Text)

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
    use_mid_year_convention: Mapped[bool] = mapped_column(default=False)

    # === Optional Debt ===
    loan_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    amortization_months: Mapped[int | None] = mapped_column(Integer)
    loan_term_months: Mapped[int | None] = mapped_column(Integer)
    io_period_months: Mapped[int | None] = mapped_column(Integer, default=0)

    # === Results (populated after engine run) ===
    result_npv: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_irr: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    result_going_in_cap_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    result_exit_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_equity_multiple: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    result_avg_occupancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    result_terminal_noi_basis: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_gross_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_exit_costs_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_transfer_tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_terminal_transfer_tax_preset: Mapped[str | None] = mapped_column(String(64))
    result_cash_flows_json: Mapped[str | None] = mapped_column(Text)  # JSON blob
    result_tenant_cash_flows_json: Mapped[str | None] = mapped_column(Text)  # JSON blob
    result_recovery_audit_json: Mapped[str | None] = mapped_column(Text)  # JSON blob

    property: Mapped["Property"] = relationship(back_populates="valuations")  # type: ignore[name-defined]
