"""
DCF valuation: terminal value, discounting, IRR, key metrics.
All arithmetic uses Decimal for precision.
"""
from __future__ import annotations

from decimal import Decimal

from src.engine.transfer_tax import calculate_transfer_tax_amount
from src.engine.types import AnnualPropertyCashFlow, TerminalValueBreakdown, ValuationParams


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
    if params.loan_amount is None or params.interest_rate is None:
        return [Decimal(0)] * num_years

    loan = params.loan_amount
    monthly_rate = params.interest_rate / Decimal(12)
    amort_months = params.amortization_months or 360
    io_months = params.io_period_months or 0
    term_months = params.loan_term_months
    horizon_months = num_years * 12

    # Calculate fixed amortizing payment once (balance at IO end = original loan)
    fixed_payment = _monthly_payment(loan, monthly_rate, amort_months)

    annual_debt_service: list[Decimal] = []
    balance = loan

    for year in range(1, num_years + 1):
        year_service = Decimal(0)
        for m in range(1, 13):
            month_num = (year - 1) * 12 + m
            if month_num > horizon_months:
                break
            if term_months is not None and month_num > term_months:
                # Debt has matured; no scheduled service beyond maturity.
                continue

            maturity_month = term_months is not None and month_num == term_months
            if month_num <= io_months:
                # Interest only
                interest = balance * monthly_rate
                if maturity_month:
                    # Balloon payoff at loan maturity.
                    year_service += interest + balance
                    balance = Decimal(0)
                else:
                    year_service += interest
            else:
                # Amortizing — fixed payment, variable principal/interest split
                interest = balance * monthly_rate
                if maturity_month:
                    # Final payment includes all remaining principal.
                    year_service += interest + balance
                    balance = Decimal(0)
                else:
                    principal = fixed_payment - interest
                    balance = max(Decimal(0), balance - principal)
                    year_service += fixed_payment
        annual_debt_service.append(year_service)

    return annual_debt_service


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
) -> TerminalValueBreakdown:
    """
    Build terminal value components:
      gross = NOI / exit_cap_rate
      net = gross - exit_costs - transfer_tax
    """
    if params.exit_cap_year == -1:
        noi = forward_year_noi if forward_year_noi is not None else annual_cfs[-1].net_operating_income
    else:
        idx = params.exit_cap_year - 1
        if 0 <= idx < len(annual_cfs):
            noi = annual_cfs[idx].net_operating_income
        else:
            noi = annual_cfs[-1].net_operating_income

    if params.exit_cap_rate == Decimal(0):
        return TerminalValueBreakdown(
            noi_basis=noi,
            gross_value=Decimal(0),
            exit_costs_amount=Decimal(0),
            transfer_tax_amount=Decimal(0),
            net_value=Decimal(0),
        )

    gross_value = noi / params.exit_cap_rate
    exit_costs = gross_value * params.exit_costs_pct
    transfer_tax = calculate_transfer_tax_amount(
        gross_sale_price=gross_value,
        preset_code=params.transfer_tax_preset,
        custom_rate=params.transfer_tax_custom_rate,
    )
    net_value = gross_value - exit_costs - transfer_tax
    return TerminalValueBreakdown(
        noi_basis=noi,
        gross_value=gross_value,
        exit_costs_amount=exit_costs,
        transfer_tax_amount=transfer_tax,
        net_value=net_value,
    )


# =========================================================================
# DCF discounting
# =========================================================================

def discount_cash_flows(
    annual_cfs: list[AnnualPropertyCashFlow],
    terminal_value: Decimal,
    discount_rate: Decimal,
    use_mid_year: bool = False,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Discount all operating cash flows and the terminal value to PV.

    Returns: (pv_of_cash_flows, pv_of_terminal_value, total_npv)

    End-of-period convention: each year's CF is discounted at t = year.
    Mid-year convention: discounted at t = year - 0.5.
    """
    pv_cfs = Decimal(0)
    for i, cf in enumerate(annual_cfs):
        year = i + 1
        t = Decimal(str(year)) - (Decimal("0.5") if use_mid_year else Decimal(0))
        pv_cfs += cf.cash_flow_before_debt / (Decimal(1) + discount_rate) ** t

    n = Decimal(str(len(annual_cfs))) - (Decimal("0.5") if use_mid_year else Decimal(0))
    pv_terminal = terminal_value / (Decimal(1) + discount_rate) ** n
    npv = pv_cfs + pv_terminal
    return pv_cfs, pv_terminal, npv


# =========================================================================
# IRR
# =========================================================================

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
    cfs_float: list[float] = []
    if initial_investment is not None:
        cfs_float.append(-float(initial_investment))

    for i, cf in enumerate(annual_cfs):
        val = float(cf.cash_flow_before_debt)
        if i == len(annual_cfs) - 1:
            val += float(terminal_value)
        cfs_float.append(val)

    if not cfs_float:
        return None

    # Need at least one sign change
    has_positive = any(c > 0 for c in cfs_float)
    has_negative = any(c < 0 for c in cfs_float)
    if not (has_positive and has_negative):
        return None

    def npv_at_rate(rate: float) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in enumerate(cfs_float))

    def dnpv_at_rate(rate: float) -> float:
        return sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cfs_float))

    # Try multiple starting points to avoid local minima
    for guess in [0.10, 0.05, 0.15, 0.20, 0.01]:
        rate = guess
        try:
            for _ in range(300):
                npv = npv_at_rate(rate)
                dnpv = dnpv_at_rate(rate)
                if abs(dnpv) < 1e-14:
                    break
                new_rate = rate - npv / dnpv
                new_rate = max(new_rate, -0.99)
                if abs(new_rate - rate) < 1e-10:
                    rate = new_rate
                    break
                rate = new_rate
            if abs(npv_at_rate(rate)) < 0.01:  # within $0.01 of zero
                return Decimal(str(round(rate, 8)))
        except (ZeroDivisionError, OverflowError):
            continue

    return None


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
