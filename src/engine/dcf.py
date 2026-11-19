"""
DCF valuation: terminal value, discounting, IRR, key metrics.
All arithmetic uses Decimal for precision.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.engine.transfer_tax import calculate_transfer_tax_amount
from src.engine.types import AnnualPropertyCashFlow, LoanParams, TerminalValueBreakdown, ValuationParams


# =========================================================================
# Debt service
# =========================================================================

def _monthly_payment(principal: Decimal, monthly_rate: Decimal, n_months: int) -> Decimal:
    """Standard amortizing payment formula."""
    if monthly_rate == Decimal(0):
        return principal / Decimal(str(n_months))
    r = monthly_rate
    n = Decimal(str(n_months))
    return principal * (r * (Decimal(1) + r) ** n) / ((Decimal(1) + r) ** n - Decimal(1))


def build_debt_schedule(params: ValuationParams, num_years: int) -> list[Decimal]:
    """
    Returns annual debt service for each analysis year (1-based list).
    Handles IO period + amortizing period.

    The amortizing payment is calculated once at the start of the amortization
    period and remains fixed throughout (standard fully-amortizing mortgage).
    """
    return build_debt_schedule_detail(params, num_years)[0]


def build_monthly_debt_detail(
    params: ValuationParams, num_months: int
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
    """
    Returns (debt service, end-of-month loan balance, balloon repaid) for each
    analysis month, summed over the first loan and any additional loans. Balance is
    zero after maturity; the balloon is included in that month's service and also
    reported separately.
    """
    service = [Decimal(0)] * num_months
    balances = [Decimal(0)] * num_months
    balloons = [Decimal(0)] * num_months
    loans = list(params.additional_loans)
    if params.loan_amount is not None and params.interest_rate is not None:
        loans.insert(0, LoanParams(
            params.loan_amount, params.interest_rate, params.amortization_months,
            params.loan_term_months, params.io_period_months or 0,
        ))
    for loan in loans:
        for i, (s, b, p) in enumerate(zip(*_loan_monthly_detail(loan, num_months))):
            service[i] += s
            balances[i] += b
            balloons[i] += p
    return service, balances, balloons


def _loan_monthly_detail(
    params: LoanParams, num_months: int
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
    """(debt service, end-of-month balance, balloon repaid) of one loan for each analysis month."""
    loan = params.loan_amount
    monthly_rate = params.interest_rate / Decimal(12)
    amort_months = params.amortization_months or 360
    io_months = params.io_period_months or 0
    term_months = params.loan_term_months

    # Calculate fixed amortizing payment once (balance at IO end = original loan)
    fixed_payment = _monthly_payment(loan, monthly_rate, amort_months)

    service: list[Decimal] = []
    balances: list[Decimal] = []
    balloons: list[Decimal] = []
    balance = loan

    for month_num in range(1, num_months + 1):
        month_service = Decimal(0)
        month_balloon = Decimal(0)
        if term_months is None or month_num <= term_months:
            maturity_month = term_months is not None and month_num == term_months
            interest = balance * monthly_rate
            if month_num <= io_months:
                # Interest only
                if maturity_month:
                    # Balloon payoff at loan maturity.
                    month_service = interest + balance
                    month_balloon = balance
                    balance = Decimal(0)
                else:
                    month_service = interest
            else:
                # Amortizing — fixed payment, variable principal/interest split
                if maturity_month:
                    # Final payment includes all remaining principal; the part
                    # beyond the scheduled payment is the balloon.
                    month_service = interest + balance
                    month_balloon = max(Decimal(0), interest + balance - fixed_payment)
                    balance = Decimal(0)
                elif balance > 0:
                    # The last payment only covers what remains; nothing is due once repaid.
                    principal = min(fixed_payment - interest, balance)
                    balance -= principal
                    month_service = interest + principal
        # After maturity the debt is repaid: no scheduled service.
        service.append(month_service)
        balances.append(balance)
        balloons.append(month_balloon)

    return service, balances, balloons


def build_debt_schedule_detail(
    params: ValuationParams, num_years: int, num_months: int | None = None
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
    """
    Returns (annual debt service, end-of-year loan balance, balloon repaid) for each
    analysis year. Balance is zero after maturity; the balloon is included in that
    year's service and also reported separately so coverage ratios can exclude it.
    `num_months` (default num_years * 12) lets the final year be partial.
    """
    total_months = num_months if num_months is not None else num_years * 12
    service, balances, balloons = build_monthly_debt_detail(params, total_months)
    annual_debt_service: list[Decimal] = []
    year_end_balances: list[Decimal] = []
    annual_balloons: list[Decimal] = []
    for y in range(num_years):
        months = slice(y * 12, min(y * 12 + 12, total_months))
        annual_debt_service.append(sum(service[months], Decimal(0)))
        year_end_balances.append(balances[min(y * 12 + 11, total_months - 1)])
        annual_balloons.append(sum(balloons[months], Decimal(0)))
    return annual_debt_service, year_end_balances, annual_balloons


# =========================================================================
# Terminal value
# =========================================================================

def calculate_terminal_value(
    annual_cfs: list[AnnualPropertyCashFlow],
    params: ValuationParams,
    forward_year_noi: Decimal | None = None,
) -> Decimal:
    """
    Terminal value = NOI / exit_cap_rate - exit costs - transfer taxes.

    exit_cap_year == -1: use forward year NOI (projected year N+1 NOI).
    exit_cap_year > 0: use that specific year's NOI.

    The forward_year_noi argument allows the caller to supply the
    N+1 projected NOI; if None, we use the last year's NOI as a conservative proxy.
    """
    return calculate_terminal_value_breakdown(annual_cfs, params, forward_year_noi).net_value


def calculate_terminal_value_breakdown(
    annual_cfs: list[AnnualPropertyCashFlow],
    params: ValuationParams,
    forward_year_noi: Decimal | None = None,
    forward_year_capital: Decimal = Decimal(0),
    forward_year_leasing_costs: Decimal = Decimal(0),
    forward_year_free_rent: Decimal = Decimal(0),
) -> TerminalValueBreakdown:
    """
    Build terminal value components:
      gross = NOI (+ free rent addback) / exit_cap_rate
      net = gross - exit_costs - transfer_tax - capital_deduction

    forward_year_capital is the (positive) Year N+1 TI/LC/building improvement
    spend; it is deducted only when params.exit_deduct_forward_capital is set.
    forward_year_leasing_costs (TI/LC only) and forward_year_free_rent are positive
    Year N+1 amounts for the granular adjustments. capital_deduction is the total of
    the forward deductions applied; TI/LC is deducted once when both capital flags are
    set. With exit_costs_on_adjusted_gross, exit costs apply to gross less that total.
    The free rent addback does not apply to a terminal NOI override.
    """
    free_rent = Decimal(0)
    if params.terminal_noi_override is not None:
        noi = params.terminal_noi_override
    elif params.exit_cap_year == -1:
        noi = forward_year_noi if forward_year_noi is not None else annual_cfs[-1].net_operating_income
        free_rent = forward_year_free_rent
    else:
        idx = params.exit_cap_year - 1
        row = annual_cfs[idx] if 0 <= idx < len(annual_cfs) else annual_cfs[-1]
        noi = row.net_operating_income
        free_rent = -row.free_rent
    if params.exit_add_back_free_rent:
        noi += free_rent

    if params.exit_cap_rate == Decimal(0):
        return TerminalValueBreakdown(
            noi_basis=noi,
            gross_value=Decimal(0),
            exit_costs_amount=Decimal(0),
            transfer_tax_amount=Decimal(0),
            net_value=Decimal(0),
        )

    gross_value = noi / params.exit_cap_rate
    capital_deduction = Decimal(0)
    if params.exit_deduct_forward_capital:
        capital_deduction = forward_year_capital
    elif params.exit_deduct_forward_leasing_costs:
        capital_deduction = forward_year_leasing_costs
    if params.exit_deduct_forward_free_rent:
        capital_deduction += forward_year_free_rent
    cost_base = gross_value - capital_deduction if params.exit_costs_on_adjusted_gross else gross_value
    exit_costs = cost_base * params.exit_costs_pct
    transfer_tax = calculate_transfer_tax_amount(
        gross_sale_price=gross_value,
        preset_code=params.transfer_tax_preset,
        custom_rate=params.transfer_tax_custom_rate,
    )
    net_value = gross_value - exit_costs - transfer_tax - capital_deduction
    return TerminalValueBreakdown(
        noi_basis=noi,
        gross_value=gross_value,
        exit_costs_amount=exit_costs,
        transfer_tax_amount=transfer_tax,
        net_value=net_value,
        capital_deduction_amount=capital_deduction,
    )


# =========================================================================
# DCF discounting
# =========================================================================

def discount_cash_flows(
    annual_cfs: list[AnnualPropertyCashFlow],
    terminal_value: Decimal,
    discount_rate: Decimal,
    use_mid_year: bool = False,
    terminal_timing: str = "end_of_period",
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Discount all operating cash flows and the terminal value to PV.

    Returns: (pv_of_cash_flows, pv_of_terminal_value, total_npv)

    End-of-period convention: each year's CF is discounted at t = year.
    Mid-year convention applies to operating cash flow at t = year - 0.5.
    Terminal proceeds default to the end of the hold. ``mid_year`` is available
    only for legacy appraisal parity.
    """
    pv_cfs = Decimal(0)
    for i, cf in enumerate(annual_cfs):
        year = i + 1
        t = Decimal(str(year)) - (Decimal("0.5") if use_mid_year else Decimal(0))
        pv_cfs += cf.cash_flow_before_debt / (Decimal(1) + discount_rate) ** t

    if terminal_timing not in {"end_of_period", "mid_year"}:
        raise ValueError("terminal_timing must be 'end_of_period' or 'mid_year'")
    terminal_offset = (
        Decimal("0.5") if use_mid_year and terminal_timing == "mid_year" else Decimal(0)
    )
    n = Decimal(str(len(annual_cfs))) - terminal_offset
    pv_terminal = terminal_value / (Decimal(1) + discount_rate) ** n
    npv = pv_cfs + pv_terminal
    return pv_cfs, pv_terminal, npv


def discount_monthly_cash_flows(
    monthly_cfs: list[AnnualPropertyCashFlow],
    terminal_value: Decimal,
    annual_discount_rate: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Discount monthly property cash flows at the equivalent monthly rate.

    Cash flow for month one is discounted one month. Terminal proceeds occur at the end of
    the final analysis month. The quoted annual rate remains effective: compounding the monthly
    rate for twelve months equals the quoted annual rate.
    """
    one_plus_rate = (Decimal(1) + annual_discount_rate) ** (Decimal(1) / Decimal(12))
    pv_cfs = sum(
        (cf.cash_flow_before_debt / one_plus_rate ** month for month, cf in enumerate(monthly_cfs, 1)),
        Decimal(0),
    )
    pv_terminal = terminal_value / one_plus_rate ** len(monthly_cfs)
    return pv_cfs, pv_terminal, pv_cfs + pv_terminal


# =========================================================================
# IRR
# =========================================================================

@dataclass(frozen=True)
class IrrResult:
    """IRR calculation with enough information to avoid silently selecting a root."""

    roots: tuple[Decimal, ...]
    status: str
    selected: Decimal | None = None  # Norstrom-selected positive root when roots are multiple

    @property
    def rate(self) -> Decimal | None:
        return self.roots[0] if len(self.roots) == 1 else self.selected


def _irr_result(roots: tuple[Decimal, ...], cfs: list[float]) -> IrrResult:
    """Classify roots. With multiple roots, select the positive one only when Norstrom's
    criterion guarantees it is unique: cumulative cash flow starts negative and changes
    sign exactly once (e.g. a small negative final-year flow on an otherwise ordinary deal)."""
    if not roots:
        return IrrResult((), "no_root")
    if len(roots) == 1:
        return IrrResult(roots, "unique")
    running = 0.0
    signs: list[bool] = []
    for cf in cfs:
        running += cf
        if running != 0:
            signs.append(running > 0)
    sign_changes = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    positive = [r for r in roots if r > 0]
    if signs and not signs[0] and sign_changes == 1 and len(positive) == 1:
        return IrrResult(roots, "multiple", positive[0])
    return IrrResult(roots, "multiple")

def calculate_irr(
    annual_cfs: list[AnnualPropertyCashFlow],
    terminal_value: Decimal,
    initial_investment: Decimal | None = None,
) -> Decimal | None:
    """
    Calculate unlevered IRR using Newton-Raphson.

    Cash flow series:
      Year 0: -initial_investment (if provided; otherwise, no year-0 CF)
      Years 1..N-1: cash_flow_before_debt
      Year N: cash_flow_before_debt + terminal_value

    Returns None if IRR cannot be computed (e.g. all-positive or non-convergent).
    """
    series: list[Decimal] = []
    if initial_investment is not None:
        series.append(-initial_investment)

    for i, cf in enumerate(annual_cfs):
        val = cf.cash_flow_before_debt
        if i == len(annual_cfs) - 1:
            val += terminal_value
        series.append(val)

    return irr_from_series(series)


def irr_from_series(cash_flows: list[Decimal]) -> Decimal | None:
    """
    IRR of an annual cash flow series where index 0 is time 0.

    Returns a rate only when there is exactly one detected real root greater than -100%.
    Use ``irr_details`` when callers need to distinguish no root from multiple roots.
    """
    return irr_details(cash_flows).rate


def _roots_by_bracketing(npv_at_rate, scale: float) -> tuple[Decimal, ...]:
    """Find rate roots on (-1, +infinity) by bisection on a log(1+r) grid."""
    # Dense near ordinary investment returns, but broad enough for extreme valid roots.
    xs = [(-18.0 + i * 0.01) for i in range(3201)]  # rates about -100% through 1.3 million %
    roots: list[float] = []
    x0 = xs[0]
    f0 = npv_at_rate(math.expm1(x0))
    tolerance = max(1e-9, scale * 1e-12)
    for x1 in xs[1:]:
        f1 = npv_at_rate(math.expm1(x1))
        if math.isfinite(f0) and math.isfinite(f1):
            if abs(f0) <= tolerance:
                roots.append(math.expm1(x0))
            elif f0 * f1 < 0:
                lo, hi, flo = x0, x1, f0
                for _ in range(100):
                    mid = (lo + hi) / 2
                    fm = npv_at_rate(math.expm1(mid))
                    if abs(fm) <= tolerance or hi - lo < 1e-13:
                        lo = hi = mid
                        break
                    if flo * fm <= 0:
                        hi = mid
                    else:
                        lo, flo = mid, fm
                roots.append(math.expm1((lo + hi) / 2))
        x0, f0 = x1, f1

    unique: list[Decimal] = []
    for root in sorted(roots):
        value = Decimal(str(round(root, 10)))
        if not unique or abs(value - unique[-1]) > Decimal("0.0000001"):
            unique.append(value)
    return tuple(unique)


def irr_details(cash_flows: list[Decimal]) -> IrrResult:
    """Return every detected annual IRR and an explicit root-status diagnostic."""
    cfs = [float(c) for c in cash_flows]
    if not cfs or not (any(c > 0 for c in cfs) and any(c < 0 for c in cfs)):
        return IrrResult((), "no_sign_change")

    def npv(rate: float) -> float:
        try:
            return sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cfs))
        except (OverflowError, ZeroDivisionError):
            return math.copysign(math.inf, cfs[-1])

    return _irr_result(_roots_by_bracketing(npv, sum(abs(c) for c in cfs)), cfs)


def xirr_details(cash_flows: list[Decimal], dates: list[date]) -> IrrResult:
    """Date-based IRR using actual/365 year fractions and bracketed root finding."""
    if len(cash_flows) != len(dates):
        raise ValueError("cash_flows and dates must have the same length")
    if not dates:
        return IrrResult((), "no_sign_change")
    cfs = [float(c) for c in cash_flows]
    if not (any(c > 0 for c in cfs) and any(c < 0 for c in cfs)):
        return IrrResult((), "no_sign_change")
    base = dates[0]
    years = [(d - base).days / 365.0 for d in dates]
    if any(t < 0 for t in years):
        raise ValueError("dates must not precede the first date")

    def xnpv(rate: float) -> float:
        try:
            return sum(cf / ((1.0 + rate) ** t) for cf, t in zip(cfs, years, strict=True))
        except (OverflowError, ZeroDivisionError):
            return math.copysign(math.inf, cfs[-1])

    return _irr_result(_roots_by_bracketing(xnpv, sum(abs(c) for c in cfs)), cfs)


def xirr(cash_flows: list[Decimal], dates: list[date]) -> Decimal | None:
    """Return XIRR only when the dated cash flows have one detected root."""
    return xirr_details(cash_flows, dates).rate


def modified_irr(
    cash_flows: list[Decimal], finance_rate: Decimal, reinvestment_rate: Decimal
) -> Decimal | None:
    """MIRR for periodic cash flows; useful when conventional IRR is ambiguous."""
    if len(cash_flows) < 2 or finance_rate <= Decimal("-1") or reinvestment_rate <= Decimal("-1"):
        return None
    n = len(cash_flows) - 1
    pv_negative = sum(
        (cf / (Decimal(1) + finance_rate) ** i for i, cf in enumerate(cash_flows) if cf < 0),
        Decimal(0),
    )
    fv_positive = sum(
        (cf * (Decimal(1) + reinvestment_rate) ** (n - i)
         for i, cf in enumerate(cash_flows) if cf > 0),
        Decimal(0),
    )
    if pv_negative == 0 or fv_positive <= 0:
        return None
    return (fv_positive / -pv_negative) ** (Decimal(1) / Decimal(n)) - Decimal(1)


# =========================================================================
# Key metrics
# =========================================================================

def going_in_cap_rate(year1_noi: Decimal, purchase_price: Decimal) -> Decimal:
    if purchase_price == Decimal(0):
        return Decimal(0)
    return year1_noi / purchase_price


def equity_multiple(
    total_levered_distributions: Decimal,
    initial_equity: Decimal,
) -> Decimal | None:
    if initial_equity == Decimal(0):
        return None
    return total_levered_distributions / initial_equity
