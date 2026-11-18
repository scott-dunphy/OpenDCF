"""
Investment returns against an actual purchase price, direct capitalization,
and discount-rate x exit-cap sensitivity grids.
All arithmetic uses Decimal for precision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from src.engine.dcf import irr_details, irr_from_series, modified_irr, xirr_details
from src.engine.transfer_tax import calculate_transfer_tax_amount
from src.engine.types import AnnualPropertyCashFlow, InvestmentReturns, ValuationParams


def _ratio(num: Decimal, den: Decimal) -> Decimal | None:
    return num / den if den != Decimal(0) else None


def compute_investment_returns(
    annual_cfs: list[AnnualPropertyCashFlow],
    terminal_net_value: Decimal,
    dcf_value: Decimal,
    params: ValuationParams,
    debt_balances: list[Decimal],
    debt_balloons: list[Decimal] | None = None,
    monthly_cfs: list[AnnualPropertyCashFlow] | None = None,
) -> InvestmentReturns | None:
    """
    Unlevered and levered returns for an acquisition at params.purchase_price.

    Unlevered series: -(price + acquisition costs) at close, CFBD each year,
    plus the net sale proceeds in the final year.
    Levered series: -(equity) at close, levered CF each year, plus net sale
    proceeds less the loan balance outstanding at sale in the final year.
    With monthly_cfs (monthly discounting), IRR and XIRR are measured on the dated
    monthly series so they agree with the monthly-discounted value.
    """
    price = params.purchase_price
    if price is None or price <= Decimal(0) or not annual_cfs:
        return None

    acq_costs = price * params.acquisition_costs_pct
    total_investment = price + acq_costs
    first_loan = params.loan_amount or Decimal(0)
    loan = first_loan + sum((a.loan_amount for a in params.additional_loans), Decimal(0))
    loan_fees = first_loan * params.loan_fees_pct + sum(
        (a.loan_amount * a.loan_fees_pct for a in params.additional_loans), Decimal(0))
    equity = total_investment - loan + loan_fees
    payoff = debt_balances[-1] if debt_balances else Decimal(0)

    n = len(annual_cfs)
    unlevered = [-total_investment]
    levered = [-equity]
    for i, cf in enumerate(annual_cfs):
        u = cf.cash_flow_before_debt
        lv = cf.levered_cash_flow
        if i == n - 1:
            u += terminal_net_value
            lv += terminal_net_value - payoff
        unlevered.append(u)
        levered.append(lv)

    year1_noi = annual_cfs[0].net_operating_income
    has_debt = loan > Decimal(0)
    if monthly_cfs:
        m = len(monthly_cfs)
        unlevered_m = [-total_investment]
        levered_m = [-equity]
        for i, cf in enumerate(monthly_cfs):
            final = i == m - 1
            unlevered_m.append(cf.cash_flow_before_debt + (terminal_net_value if final else Decimal(0)))
            levered_m.append(cf.levered_cash_flow + (terminal_net_value - payoff if final else Decimal(0)))
        monthly_dates = [monthly_cfs[0].period_start] + [cf.period_end for cf in monthly_cfs]
        unlevered_xirr_result = xirr_details(unlevered_m, monthly_dates)
        levered_xirr_result = xirr_details(levered_m, monthly_dates) if has_debt else None
        unlevered_irr_result = unlevered_xirr_result
        levered_irr_result = levered_xirr_result
    else:
        unlevered_irr_result = irr_details(unlevered)
        levered_irr_result = irr_details(levered) if has_debt else None
        return_dates = [annual_cfs[0].period_start] + [cf.period_end for cf in annual_cfs]
        unlevered_xirr_result = xirr_details(unlevered, return_dates)
        levered_xirr_result = xirr_details(levered, return_dates) if has_debt else None

    # Coverage and cash-on-cash use scheduled service only; a balloon repaid at
    # maturity is a refinancing event, not operating debt service.
    balloons = debt_balloons or [Decimal(0)] * n
    dscrs: list[Decimal] = []
    coc: list[Decimal] = []
    for cf, balloon in zip(annual_cfs, balloons):
        service = -cf.debt_service - balloon
        if has_debt and service > Decimal(0):
            dscrs.append(cf.net_operating_income / service)
        if equity > Decimal(0):
            coc.append((cf.levered_cash_flow + balloon) / equity)

    return InvestmentReturns(
        purchase_price=price,
        acquisition_costs=acq_costs,
        total_investment=total_investment,
        npv_at_price=dcf_value - total_investment,
        going_in_cap_rate=year1_noi / price,
        unlevered_irr=unlevered_irr_result.rate,
        unlevered_equity_multiple=_ratio(sum(unlevered[1:], Decimal(0)), total_investment),
        loan_amount=loan,
        loan_fees=loan_fees,
        equity_invested=equity,
        loan_payoff_at_sale=payoff,
        levered_irr=levered_irr_result.rate if levered_irr_result else None,
        levered_equity_multiple=(
            _ratio(sum(levered[1:], Decimal(0)), equity) if has_debt and equity > 0 else None
        ),
        year1_cash_on_cash=coc[0] if coc else None,
        avg_cash_on_cash=(sum(coc, Decimal(0)) / Decimal(len(coc))) if coc else None,
        year1_dscr=dscrs[0] if dscrs else None,
        min_dscr=min(dscrs) if dscrs else None,
        year1_debt_yield=_ratio(year1_noi, loan) if has_debt else None,
        loan_to_value=_ratio(loan, price) if has_debt else None,
        unlevered_cash_flows=unlevered,
        levered_cash_flows=levered,
        unlevered_irr_status=unlevered_irr_result.status,
        unlevered_irr_roots=list(unlevered_irr_result.roots),
        unlevered_mirr=modified_irr(unlevered, params.discount_rate, params.discount_rate),
        unlevered_xirr=unlevered_xirr_result.rate,
        unlevered_xirr_status=unlevered_xirr_result.status,
        unlevered_xirr_roots=list(unlevered_xirr_result.roots),
        levered_irr_status=(levered_irr_result.status if levered_irr_result else "not_applicable"),
        levered_irr_roots=(list(levered_irr_result.roots) if levered_irr_result else []),
        levered_mirr=(
            modified_irr(levered, params.discount_rate, params.discount_rate) if has_debt else None
        ),
        levered_xirr=(levered_xirr_result.rate if levered_xirr_result else None),
        levered_xirr_status=(
            levered_xirr_result.status if levered_xirr_result else "not_applicable"
        ),
        levered_xirr_roots=(list(levered_xirr_result.roots) if levered_xirr_result else []),
    )


def direct_cap_value(year1_noi: Decimal, cap_rate: Decimal | None) -> Decimal | None:
    """Direct capitalization value: Year 1 NOI / cap rate."""
    if cap_rate is None or cap_rate <= Decimal(0):
        return None
    return year1_noi / cap_rate


# =========================================================================
# Sensitivity
# =========================================================================

@dataclass
class SensitivityGrid:
    discount_rates: list[Decimal]
    exit_cap_rates: list[Decimal]
    values: list[list[Decimal]]           # [discount_rate_idx][exit_cap_idx]
    irr_by_exit_cap: list[Decimal | None]  # unlevered IRR at purchase price (None if no price)
    terminal_values: list[Decimal] = field(default_factory=list)  # net reversion per exit cap


def sensitivity_grid(
    cash_flows_before_debt: list[Decimal],
    terminal_noi_basis: Decimal,
    exit_costs_pct: Decimal,
    transfer_tax_preset: str,
    transfer_tax_custom_rate: Decimal | None,
    capital_deduction: Decimal,
    discount_rates: list[Decimal],
    exit_cap_rates: list[Decimal],
    use_mid_year: bool = False,
    terminal_timing: str = "end_of_period",
    total_investment: Decimal | None = None,
) -> SensitivityGrid:
    """
    Present value at each discount rate x exit cap pair, holding cash flows and
    the terminal NOI basis fixed (the published DCF software "PV matrix").
    """
    n = len(cash_flows_before_debt)
    terminals: list[Decimal] = []
    for cap in exit_cap_rates:
        gross = terminal_noi_basis / cap if cap > 0 else Decimal(0)
        tax = calculate_transfer_tax_amount(
            gross_sale_price=gross,
            preset_code=transfer_tax_preset,
            custom_rate=transfer_tax_custom_rate,
        )
        terminals.append(gross - gross * exit_costs_pct - tax - capital_deduction)

    offset = Decimal("0.5") if use_mid_year else Decimal(0)
    if terminal_timing not in {"end_of_period", "mid_year"}:
        raise ValueError("terminal_timing must be 'end_of_period' or 'mid_year'")
    terminal_offset = (
        Decimal("0.5") if use_mid_year and terminal_timing == "mid_year" else Decimal(0)
    )
    values: list[list[Decimal]] = []
    for rate in discount_rates:
        pv_cfs = sum(
            (cf / (Decimal(1) + rate) ** (Decimal(i + 1) - offset)
             for i, cf in enumerate(cash_flows_before_debt)),
            Decimal(0),
        )
        disc_n = (Decimal(1) + rate) ** (Decimal(n) - terminal_offset)
        values.append([pv_cfs + tv / disc_n for tv in terminals])

    irrs: list[Decimal | None] = []
    for tv in terminals:
        if total_investment is None or n == 0:
            irrs.append(None)
            continue
        series = [-total_investment] + list(cash_flows_before_debt)
        series[-1] += tv
        irrs.append(irr_from_series(series))

    return SensitivityGrid(
        discount_rates=discount_rates,
        exit_cap_rates=exit_cap_rates,
        values=values,
        irr_by_exit_cap=irrs,
        terminal_values=terminals,
    )
