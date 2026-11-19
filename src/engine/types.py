"""
Engine-internal dataclasses. No SQLAlchemy, no Pydantic, no external deps.
All financial amounts are Decimal. All dates are datetime.date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class FiscalYear:
    year_number: int          # 1-based
    start_date: date
    end_date: date


@dataclass(frozen=True)
class AnalysisPeriod:
    start_date: date
    end_date: date
    num_months: int
    fiscal_year_end_month: int
    fiscal_years: tuple[FiscalYear, ...]


@dataclass(frozen=True)
class RentStepInput:
    effective_date: date
    rent_per_unit: Decimal


@dataclass(frozen=True)
class FreeRentPeriodInput:
    start_date: date
    end_date: date
    applies_to_base_rent: bool
    applies_to_recoveries: bool


@dataclass(frozen=True)
class RecoveryPoolInput:
    """Expense lines recovered together over one share denominator.

    denominator: "property_area" (property area less excluded suites), "fixed_area" (fixed_area),
    or "occupied_area" (leased area of the included suites, at least minimum_occupancy_pct of it).
    Excluded suites (anchors, outparcels) leave the denominator; their leases recover on their own
    terms and, with deduct_excluded_recoveries, what they pay comes off the pool first.
    """
    pool_id: str
    name: str
    expense_categories: tuple[str, ...]
    denominator: str = "property_area"
    fixed_area: Decimal | None = None
    minimum_occupancy_pct: Decimal | None = None
    excluded_suite_ids: tuple[str, ...] = ()
    deduct_excluded_recoveries: bool = False


@dataclass(frozen=True)
class ExpenseRecoveryOverride:
    expense_category: str
    recovery_type: str
    base_year_stop_amount: Decimal | None
    cap_per_sf_annual: Decimal | None
    floor_per_sf_annual: Decimal | None
    admin_fee_pct: Decimal | None
    # Overrides with the same cap group share one cap on their combined recovery (e.g. CAM and
    # management fee); the group's cap_per_sf_annual / cap_growth_pct come from any member
    cap_group: str | None = None
    # Recovery may grow at most this much a year from the year the lease starts
    cap_growth_pct: Decimal | None = None
    # Modified gross: this category alone recovers its $/SF above this stop
    expense_stop_per_sf: Decimal | None = None
    # Share of the category's expense (after gross-up and pool deductions) that is recoverable, before
    # the stop, pro rata share and cap/floor (e.g. 0.6 recovers 60% of janitorial)
    recoverable_pct: Decimal = Decimal(1)


@dataclass(frozen=True)
class LeaseInput:
    lease_id: str
    suite_id: str
    tenant_name: str | None
    area: Decimal
    start_date: date
    end_date: date
    base_rent_per_unit: Decimal    # $/SF/yr for commercial, $/unit/mo for residential
    rent_payment_frequency: str    # "monthly", "quarterly", "annual"
    escalation_type: str           # flat, pct_annual, cpi, fixed_step
    escalation_pct: Decimal | None
    cpi_floor: Decimal | None
    cpi_cap: Decimal | None
    rent_steps: tuple[RentStepInput, ...]
    free_rent_periods: tuple[FreeRentPeriodInput, ...]
    recovery_type: str
    pro_rata_share: Decimal | None   # if None, computed from area / total_area
    base_year_stop_amount: Decimal | None
    expense_stop_per_sf: Decimal | None
    recovery_overrides: tuple[ExpenseRecoveryOverride, ...]
    pct_rent_breakpoint: Decimal | None
    pct_rent_rate: Decimal | None
    base_year: int | None = None
    renewal_probability_override: Decimal | None = None
    renewal_rent_spread_override: Decimal | None = None
    projected_annual_sales_per_sf: Decimal | None = None
    exclude_from_general_vacancy: bool = False   # credit tenant: no general vacancy / credit loss
    # published DCF software "Exclude upon rollover": the exclusion ends when the lease expires; False carries it
    # to the market leases that follow in the suite
    vacancy_exclusion_ends_at_rollover: bool = True
    # fixed_step only: a mid-month step splits the month by days instead of starting next month
    prorate_rent_steps: bool = False
    # What happens at expiry: market (probability blend), renew, vacate, option, reabsorb
    upon_expiration: str = "market"
    option_rent_per_unit: Decimal | None = None  # None = market rent x (1 + renewal spread)
    option_term_months: int | None = None
    option_ti_per_sf: Decimal = Decimal(0)
    option_lc_pct: Decimal = Decimal(0)
    # Committed (contractual, unpaid) leasing costs on an in-place lease, $ total
    committed_ti_amount: Decimal = Decimal(0)
    committed_lc_amount: Decimal = Decimal(0)
    # "per_area": rent is $ per SF (or unit) x area; "total": rent is the whole lease's $ amount
    # (per year, or per month when monthly), e.g. an antenna or signage lease on 0 SF
    rent_basis: str = "per_area"
    # Recovery cap growth is measured from the year this date falls in (None = start_date): an
    # exercised option continues the original lease's caps
    recovery_cap_start: date | None = None

    @property
    def rent_area(self) -> Decimal:
        """What the rent rate is multiplied by."""
        return rent_area(self.area, self.rent_basis)


def rent_area(area: Decimal, rent_basis: str) -> Decimal:
    """Area for rent: the suite's area, or 1 when the rent is a total amount."""
    return Decimal(1) if rent_basis == "total" else area


@dataclass(frozen=True)
class SuiteInput:
    suite_id: str
    suite_name: str
    area: Decimal
    space_type: str
    # Lease-up for vacant space (also used when a lease is reabsorbed). Active when either is set.
    absorption_start_date: date | None = None  # leasing begins; default = vacancy start
    lease_up_months: int | None = None         # months from leasing start to commencement; default = MLA downtime

    @property
    def has_lease_up(self) -> bool:
        return self.absorption_start_date is not None or self.lease_up_months is not None


@dataclass(frozen=True)
class OtherIncomeInput:
    income_id: str
    category: str
    base_amount: Decimal
    growth_rate: Decimal
    growth_schedule: tuple[Decimal, ...] = ()   # year-by-year rates; last carries forward
    amount_schedule: tuple[Decimal, ...] = ()   # explicit annual dollars; later years grow from the last at the growth rate


@dataclass(frozen=True)
class CapitalProjectInput:
    project_id: str
    description: str
    total_amount: Decimal
    start_date: date
    duration_months: int


@dataclass(frozen=True)
class MarketAssumptions:
    space_type: str
    market_rent_per_unit: Decimal
    rent_growth_rate: Decimal

    new_lease_term_months: int
    new_ti_per_sf: Decimal
    new_lc_pct: Decimal
    new_free_rent_months: int
    downtime_months: int

    renewal_probability: Decimal
    renewal_term_months: int
    renewal_ti_per_sf: Decimal
    renewal_lc_pct: Decimal
    renewal_free_rent_months: int
    renewal_rent_adjustment_pct: Decimal  # vs market: -0.05 = 5% below market

    general_vacancy_pct: Decimal
    credit_loss_pct: Decimal
    rent_payment_frequency: str = "annual"  # "annual" ($/SF/yr) or "monthly" ($/unit/mo)
    rent_basis: str = "per_area"  # "total": market rent is the whole space's $ amount
    concession_timing_mode: str = "blended"
    concession_year1_months: Decimal | None = None
    concession_year2_months: Decimal | None = None
    concession_year3_months: Decimal | None = None
    concession_year4_months: Decimal | None = None
    concession_year5_months: Decimal | None = None
    concession_stabilized_months: Decimal | None = None
    rent_growth_schedule: tuple[Decimal, ...] = ()  # year-by-year rates; last carries forward
    next_space_type: str | None = None  # MLA chaining: profile used when a lease under this one expires
    # Year-by-year values (last carries forward); empty = the single field above every year.
    # Used by collateral Monte Carlo paths.
    general_vacancy_schedule: tuple[Decimal, ...] = ()
    credit_loss_schedule: tuple[Decimal, ...] = ()
    renewal_probability_schedule: tuple[Decimal, ...] = ()   # by analysis year of the expiry
    downtime_schedule: tuple[int, ...] = ()                  # by analysis year of the expiry
    new_free_rent_schedule: tuple[Decimal, ...] = ()         # months, by analysis year the lease starts
    renewal_free_rent_schedule: tuple[Decimal, ...] = ()
    # Leasing commissions per SF, on top of the % of lease rent
    new_lc_per_sf: Decimal = Decimal(0)
    renewal_lc_per_sf: Decimal = Decimal(0)
    # Annual growth of TI and LC $/SF from Year 1 to the year the lease starts
    leasing_cost_growth_rate: Decimal = Decimal(0)
    leasing_cost_growth_schedule: tuple[Decimal, ...] = ()
    # "probability_tree": renewal and new tenant modeled as weighted branches;
    # "blended": one lease with probability-weighted terms (published DCF software market leasing)
    rollover_method: str = "probability_tree"
    # Annual increase on market leases; None = the market rent growth rate in the year the lease starts
    lease_escalation_pct: Decimal | None = None
    # Fixed annual increase on market leases, $/unit (published DCF software "$0.50/SF/yr"); replaces lease_escalation_pct
    lease_escalation_per_unit: Decimal | None = None
    # Leasing commissions count the escalated rent (published DCF software step rent) or base rent only (published DCF software CPI rent)
    lc_includes_escalations: bool = True
    # Leasing commission % for each lease year (year 1 = the first 12 months from lease start),
    # e.g. (0.06,) * 5 + (0.03,) * 5 = 6% of years 1-5 and 3% of years 6-10; the last rate
    # carries forward. Replaces new_lc_pct / renewal_lc_pct when set.
    new_lc_pct_by_lease_year: tuple[Decimal, ...] = ()
    renewal_lc_pct_by_lease_year: tuple[Decimal, ...] = ()
    # Renewal rent: "market" (market rent x (1 + renewal adjustment)), or the greater / lesser of
    # that and the expiring lease's last contract rent ("greater_of_prior" / "lesser_of_prior")
    renewal_rent_rule: str = "market"
    # Market leases starting mid-month after downtime start on the 1st of the next month instead;
    # the extra days stay vacant. Renewals in the probability tree (no downtime) are not moved.
    round_start_to_month: bool = False
    # Rent increases at given months of a market lease, on top of the annual escalation:
    # ((61, 0.10),) = up 10% from lease month 61 (published DCF software changing base rent)
    lease_rent_steps: tuple[tuple[int, Decimal], ...] = ()
    # Every lease in suites under this profile is excluded from general vacancy and credit loss
    exclude_from_general_vacancy: bool = False
    # Recovery terms of market leases (the profile's recovery structure). None = each market lease
    # copies the expiring lease's recovery type (NNN for space never leased), with no overrides.
    recovery_type: str | None = None
    recovery_overrides: tuple[ExpenseRecoveryOverride, ...] = ()
    # Modified gross stop ($/SF/yr) of the profile's recovery structure; None = the market lease's
    # base year resets to its start year (see renewal_engine._reset_stop)
    expense_stop_per_sf: Decimal | None = None


@dataclass(frozen=True)
class ExpenseInput:
    expense_id: str
    category: str
    base_amount: Decimal          # total $ for year 1
    growth_rate: Decimal          # annual, e.g. 0.03
    is_recoverable: bool
    is_gross_up_eligible: bool
    gross_up_vacancy_pct: Decimal | None
    is_pct_of_egi: bool
    pct_of_egi: Decimal | None
    growth_schedule: tuple[Decimal, ...] = ()   # year-by-year rates; last carries forward
    # Share of the expense that varies with occupancy. 0 = amount used as entered (legacy);
    # > 0 = amount is stated at 100% occupancy and the variable share scales with occupancy.
    variable_pct: Decimal = Decimal(0)
    amount_schedule: tuple[Decimal, ...] = ()   # explicit annual dollars; later years grow from the last at the growth rate
    # Memo line (e.g. amortized capital billed to tenants): recoveries can include it, but it is not
    # deducted as an operating expense. Applies to fixed-amount lines only.
    is_memo: bool = False


@dataclass(frozen=True)
class LoanParams:
    """A loan besides the valuation's first loan (e.g. a second mortgage or mezzanine loan), funded at close."""
    loan_amount: Decimal
    interest_rate: Decimal
    amortization_months: int | None = None   # None = 360
    loan_term_months: int | None = None      # None = outstanding through the analysis
    io_period_months: int = 0
    loan_fees_pct: Decimal = Decimal(0)      # of the loan amount, paid at close


@dataclass(frozen=True)
class ValuationParams:
    discount_rate: Decimal
    exit_cap_rate: Decimal
    exit_cap_year: int             # -1 = forward year
    exit_costs_pct: Decimal
    capital_reserves_per_unit: Decimal
    total_property_area: Decimal
    use_mid_year_convention: bool
    loan_amount: Decimal | None
    interest_rate: Decimal | None
    amortization_months: int | None
    loan_term_months: int | None
    io_period_months: int
    # Sale proceeds normally occur at the end of the hold even when operating cash flow uses
    # mid-year discounting. ``mid_year`` is retained for legacy appraisal parity.
    terminal_timing: str = "end_of_period"
    # Present-value timing. ``annual`` preserves the legacy year-end/mid-year calculation;
    # ``monthly`` discounts the monthly property waterfall using the equivalent monthly rate.
    discounting_convention: str = "annual"
    # Frequency used to calculate and floor general vacancy. Monthly calculation can produce
    # a larger annual loss when individual months are already fully offset by modeled downtime.
    vacancy_calculation_frequency: str = "annual"
    # Optional appraiser-disclosed NOI for the year immediately following the hold.
    # This preserves a reported reversion input when annual schedules are rounded.
    terminal_noi_override: Decimal | None = None
    transfer_tax_preset: str = "none"
    transfer_tax_custom_rate: Decimal | None = None
    apply_stabilized_gross_up: bool = True
    stabilized_occupancy_pct: Decimal | None = None
    # Acquisition / returns
    purchase_price: Decimal | None = None      # None = solve returns at the DCF value
    acquisition_costs_pct: Decimal = Decimal(0)  # of purchase price
    loan_fees_pct: Decimal = Decimal(0)          # of loan amount, paid at close
    direct_cap_rate: Decimal | None = None       # applied to Year 1 NOI
    exit_deduct_forward_capital: bool = False    # deduct Year N+1 TI/LC/capex from sale
    # Terminal value adjustments (published DCF software resale adjustments). Free rent and
    # TI/LC come from the year whose NOI is capitalized (Year N+1 when exit_cap_year == -1).
    exit_add_back_free_rent: bool = False            # add free rent to the capitalized NOI
    exit_deduct_forward_free_rent: bool = False      # deduct Year N+1 free rent from sale
    exit_deduct_forward_leasing_costs: bool = False  # deduct Year N+1 TI/LC (no capex) from sale
    exit_costs_on_adjusted_gross: bool = False       # selling costs on gross less those deductions
    # General vacancy is a target for total vacancy; modeled downtime/absorption counts toward it
    reduce_general_vacancy_by_downtime: bool = False
    # Capital reserves grow at this rate from Year 1
    capital_reserves_growth_rate: Decimal = Decimal(0)
    # General vacancy and credit loss apply to gross revenue (rent, recoveries, percentage rent
    # and other income) instead of rent only
    vacancy_on_gross_revenue: bool = False
    # Credit loss applies to tenant revenue (rent after free rent, recoveries and percentage rent),
    # not other income; general vacancy keeps its base
    credit_loss_on_tenant_revenue: bool = False
    # Tenants reimburse each calendar year's expenses (published DCF software calendar reimbursement), not the
    # analysis year's; differs only when the analysis year does not end in December
    calendar_year_recoveries: bool = False
    # Reversion NOI adjusted for full occupancy (published DCF software): in the year capitalized, space vacant
    # between leases earns market rent and pays its recoveries, and general vacancy is the
    # stabilized rate below
    exit_noi_full_occupancy: bool = False
    exit_stabilized_vacancy_pct: Decimal = Decimal(0)
    # Loans besides the first; debt service, balances and fees are the sum of all loans
    additional_loans: tuple[LoanParams, ...] = ()


@dataclass(frozen=True)
class TerminalValueBreakdown:
    noi_basis: Decimal
    gross_value: Decimal
    exit_costs_amount: Decimal
    transfer_tax_amount: Decimal
    net_value: Decimal
    capital_deduction_amount: Decimal = Decimal(0)


@dataclass
class InvestmentReturns:
    """Returns measured against an actual purchase price (unlevered and levered)."""
    purchase_price: Decimal
    acquisition_costs: Decimal
    total_investment: Decimal            # price + acquisition costs
    npv_at_price: Decimal                # DCF value - total investment
    going_in_cap_rate: Decimal           # Year 1 NOI / purchase price
    unlevered_irr: Decimal | None
    unlevered_equity_multiple: Decimal | None
    loan_amount: Decimal
    loan_fees: Decimal
    equity_invested: Decimal
    loan_payoff_at_sale: Decimal
    levered_irr: Decimal | None
    levered_equity_multiple: Decimal | None
    year1_cash_on_cash: Decimal | None
    avg_cash_on_cash: Decimal | None
    year1_dscr: Decimal | None
    min_dscr: Decimal | None
    year1_debt_yield: Decimal | None
    loan_to_value: Decimal | None
    unlevered_cash_flows: list[Decimal] = field(default_factory=list)  # index 0 = closing
    levered_cash_flows: list[Decimal] = field(default_factory=list)
    unlevered_irr_status: str = "not_calculated"
    unlevered_irr_roots: list[Decimal] = field(default_factory=list)
    unlevered_mirr: Decimal | None = None
    unlevered_xirr: Decimal | None = None
    unlevered_xirr_status: str = "not_calculated"
    unlevered_xirr_roots: list[Decimal] = field(default_factory=list)
    levered_irr_status: str = "not_calculated"
    levered_irr_roots: list[Decimal] = field(default_factory=list)
    levered_mirr: Decimal | None = None
    levered_xirr: Decimal | None = None
    levered_xirr_status: str = "not_calculated"
    levered_xirr_roots: list[Decimal] = field(default_factory=list)


# =========================================================================
# Output types
# =========================================================================

@dataclass(frozen=True)
class FeeShare:
    """A lease's terms for one % of EGI line in one month (amounts are for the month)."""
    share: Decimal                    # share of the line's fee, admin fee included
    gross_up: bool = True             # grossed up like the line (not in an occupied-area pool)
    floor: Decimal | None = None      # least the lease pays toward the line ($)
    cap: Decimal | None = None        # most the lease pays toward the line ($)
    cap_group: str | None = None      # shares MonthlySlice.mgmt_fee_caps[cap_group] with the group's other fee lines
    pool: str | None = None           # deducting pool it is shared in: its share is of the fee less what excluded tenants pay
    pays_into: str | None = None      # deducting pool that excludes the suite: what it pays comes off that pool
    # Pool with excluded suites: the line's gross-up factor at the included suites' occupancy for the
    # recovery year (None: the waterfall grosses up at property occupancy)
    gross_factor: Decimal | None = None
    deduction: Decimal = Decimal(0)   # deducting pool: what excluded base-year / modified gross leases pay ($/month)


@dataclass
class MonthlySlice:
    """One month of cash flow for a single lease or vacant period on a suite."""
    month_index: int         # 0-based from analysis start
    period_start: date
    period_end: date
    suite_id: str
    lease_id: str
    tenant_name: str | None
    base_rent: Decimal       # full rent (before free rent adjustment)
    free_rent_adjustment: Decimal  # negative amount (abatement)
    effective_rent: Decimal  # base_rent + free_rent_adjustment
    expense_recovery: Decimal
    percentage_rent: Decimal
    ti_cost: Decimal         # negative when incurred
    lc_cost: Decimal         # negative when incurred
    is_vacant: bool
    scenario_label: str      # "in_place", "renewal", "new_tenant", "vacant"
    scenario_weight: Decimal  # probability weight (1.0 for in-place)
    expense_recovery_detail: dict[str, Decimal] = field(default_factory=dict)  # category -> monthly recovery
    # The tenant's terms for each % of EGI line (management fee and others) it reimburses a share of
    # this month, by category; the waterfall solves the fee, which depends on EGI
    mgmt_fee_shares: dict[str, FeeShare] = field(default_factory=dict)
    # Room this month for the fee lines in each cap group with a $/SF cap (what the group's other
    # members leave of the cap), by cap group
    mgmt_fee_caps: dict[str, Decimal] = field(default_factory=dict)
    # Share of the month a vacant slice covers (a lease ending or starting mid-month)
    month_fraction: Decimal = Decimal(1)


@dataclass
class RecoveryAuditEntry:
    """
    One monthly, per-expense-line recovery calculation entry for audit/verification.
    Amount fields are unweighted unless otherwise noted.
    """
    year: int
    period_start: date
    period_end: date
    suite_id: str
    lease_id: str
    tenant_name: str | None
    expense_category: str
    recovery_type: str
    annual_expense_before_gross_up: Decimal
    annual_expense_after_gross_up: Decimal
    actual_occupancy_pct: Decimal
    gross_up_reference_occupancy_pct: Decimal | None
    gross_up_factor: Decimal
    pro_rata_share_pct: Decimal
    base_year_stop_amount: Decimal | None
    expense_stop_per_sf: Decimal | None
    cap_per_sf_annual: Decimal | None
    floor_per_sf_annual: Decimal | None
    admin_fee_pct: Decimal | None
    annual_recovery_before_proration: Decimal
    monthly_recovery_before_free_rent: Decimal
    proration_factor: Decimal
    is_recovery_free_rent_abatement: bool
    monthly_recovery_after_free_rent: Decimal
    scenario_weight: Decimal
    weighted_monthly_recovery: Decimal
    recovery_pool: str | None = None
    share_denominator_area: Decimal | None = None
    pool_deduction: Decimal = Decimal(0)
    # Modified gross: the pooled $/SF the stop is tested against (None when measured alone)
    modified_gross_pool_per_sf: Decimal | None = None


@dataclass
class SuiteAnnualCashFlow:
    """Per-suite, per-year summary used for tenant detail report."""
    suite_id: str
    suite_name: str
    space_type: str
    area: Decimal
    year: int
    tenant_name: str | None
    scenario: str
    base_rent: Decimal
    effective_rent: Decimal
    free_rent: Decimal         # free rent concessions (negative)
    expense_recovery: Decimal
    turnover_vacancy: Decimal  # market rent lost during vacant months (negative)
    loss_to_lease: Decimal    # contract vs market shortfall (negative)
    ti_cost: Decimal          # tenant improvements (negative)
    lc_cost: Decimal          # leasing commissions (negative)
    ti_lc_cost: Decimal      # combined TI + LC (negative)


@dataclass
class AnnualPropertyCashFlow:
    year: int
    period_start: date
    period_end: date

    gross_potential_rent: Decimal      # base rent at full contract rate
    free_rent: Decimal                 # free rent concessions (negative)
    absorption_vacancy: Decimal       # turnover vacancy (negative)
    loss_to_lease: Decimal             # contract vs market shortfall (negative)
    expense_recoveries: Decimal
    percentage_rent: Decimal
    other_income: Decimal
    gross_potential_income: Decimal

    general_vacancy_loss: Decimal
    credit_loss: Decimal
    effective_gross_income: Decimal

    operating_expenses: Decimal   # negative

    net_operating_income: Decimal

    tenant_improvements: Decimal  # negative
    leasing_commissions: Decimal  # negative
    capital_reserves: Decimal     # negative
    building_improvements: Decimal  # negative, scheduled CapEx projects

    cash_flow_before_debt: Decimal

    debt_service: Decimal         # negative or zero
    levered_cash_flow: Decimal

    expense_detail: dict[str, Decimal] = field(default_factory=dict)  # category → amount (negative)
    other_income_detail: dict[str, Decimal] = field(default_factory=dict)  # category → amount


@dataclass
class EngineResult:
    annual_cash_flows: list[AnnualPropertyCashFlow]
    suite_annual_details: list[SuiteAnnualCashFlow]
    npv: Decimal
    irr: Decimal | None
    terminal_value: Decimal
    pv_cash_flows: Decimal
    pv_terminal: Decimal
    going_in_cap_rate: Decimal
    avg_occupancy_pct: Decimal
    equity_multiple: Decimal | None
    terminal_noi_basis: Decimal = Decimal(0)
    terminal_gross_value: Decimal = Decimal(0)
    terminal_exit_costs_amount: Decimal = Decimal(0)
    terminal_transfer_tax_amount: Decimal = Decimal(0)
    terminal_transfer_tax_preset: str = "none"
    terminal_capital_deduction_amount: Decimal = Decimal(0)
    direct_cap_value: Decimal | None = None
    returns: InvestmentReturns | None = None
    recovery_audit: list[RecoveryAuditEntry] = field(default_factory=list)
    # Same waterfall by month (year = analysis year of the month); filled when requested
    monthly_cash_flows: list[AnnualPropertyCashFlow] = field(default_factory=list)
    # Self storage only: per analysis year occupancy, rates, customer movement (see engine.self_storage)
    storage_detail: list[dict] | None = None
