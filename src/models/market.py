from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, DecimalList, RentStepList, TimestampMixin, UUIDPrimaryKey


class MarketLeasingProfile(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Market leasing assumptions for one space type, owned by a valuation (each valuation has its
    own market view). Used for speculative (post-expiry) lease projection.
    One profile per valuation per space_type; property_id is the valuation's property.
    """
    __tablename__ = "market_leasing_profiles"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    space_type: Mapped[str] = mapped_column(String(100))  # must match Suite.space_type
    description: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)

    # Market rent
    market_rent_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 6))  # $/SF/yr or $/unit/mo
    rent_basis: Mapped[str] = mapped_column(String(20), default="per_area", server_default="per_area")
    rent_growth_rate_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6))  # annual, e.g. 0.03
    # MLA chaining: profile used when a speculative lease under this one expires
    next_profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("market_leasing_profiles.id", ondelete="SET NULL"), nullable=True
    )
    # Optional year-by-year growth (Year 1, 2, ...; last carries forward); replaces the single rate
    rent_growth_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    # Recovery terms for market leases under this profile; None = copy the expiring lease's
    recovery_structure_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("recovery_structures.id", ondelete="SET NULL"), nullable=True
    )

    # New tenant assumptions
    new_lease_term_months: Mapped[int] = mapped_column(Integer, default=60)
    new_tenant_ti_per_sf: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    new_tenant_lc_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.06"))  # of total lease value
    new_tenant_lc_per_sf: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))  # on top of the %
    # % of each lease year's rent (year 1 = first 12 months of the lease); replaces the single %
    new_tenant_lc_pct_by_lease_year: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    new_tenant_free_rent_months: Mapped[int] = mapped_column(Integer, default=0)
    downtime_months: Mapped[int] = mapped_column(Integer, default=3)

    # Renewal assumptions
    renewal_probability: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.65"))
    renewal_lease_term_months: Mapped[int] = mapped_column(Integer, default=60)
    renewal_ti_per_sf: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    renewal_lc_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.03"))
    renewal_lc_per_sf: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    renewal_lc_pct_by_lease_year: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    renewal_free_rent_months: Mapped[int] = mapped_column(Integer, default=0)
    renewal_rent_adjustment_pct: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=Decimal("0")
    )  # vs market, e.g. -0.05 = 5% below market
    # Annual growth of TI and LC $/SF from Year 1 to the year a lease starts
    leasing_cost_growth_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    # probability_tree (renewal and new tenant as weighted branches) or blended (published DCF software: one weighted lease)
    rollover_method: Mapped[str] = mapped_column(String(20), default="probability_tree")
    # market | greater_of_prior | lesser_of_prior: renewal rent vs the expiring lease's last rent
    renewal_rent_rule: Mapped[str] = mapped_column(String(20), default="market", server_default="market")
    # Mid-month market lease starts after downtime move to the 1st of the next month
    round_start_to_month: Mapped[bool] = mapped_column(default=False)
    # Annual increase on market leases; None = market rent growth in the year the lease starts
    lease_escalation_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    # Fixed annual increase on market leases, $/SF (or $/unit); replaces lease_escalation_pct when set
    lease_escalation_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    # LC on escalated rent (published DCF software step rent) or base rent only (published DCF software CPI rent)
    lc_includes_escalations: Mapped[bool] = mapped_column(default=True)
    # Rent increases at given lease months of market leases: [(61, 0.10)] = up 10% from month 61
    lease_rent_steps: Mapped[list] = mapped_column(RentStepList, nullable=True, default=list)
    # Leases in suites under this profile are excluded from general vacancy and credit loss
    exclude_from_general_vacancy: Mapped[bool] = mapped_column(default=False)
    # Optional year-by-year values (Year 1, 2, ...; last carries forward); each replaces its single field.
    # Vacancy and credit loss by analysis year; renewal probability and downtime by the year a lease
    # expires; free rent (months) by the year a market lease starts; leasing cost growth by year.
    general_vacancy_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    credit_loss_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    renewal_probability_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    downtime_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)  # months
    new_free_rent_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    renewal_free_rent_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)
    leasing_cost_growth_schedule: Mapped[list[Decimal]] = mapped_column(DecimalList, nullable=True, default=list)

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

    property: Mapped["Property"] = relationship(viewonly=True)  # type: ignore[name-defined]
    valuation: Mapped["Valuation"] = relationship(back_populates="market_leasing_profiles")  # type: ignore[name-defined]
