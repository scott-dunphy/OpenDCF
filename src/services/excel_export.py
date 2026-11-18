"""
Full Excel export: multi-tab workbook for valuation results.

Tabs: Key Metrics, Assumptions, Annual Cash Flows, Tenant Detail,
      Debt Schedule, Rent Roll, Lease Expirations
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.engine.dcf import build_monthly_debt_detail
from src.engine.types import LoanParams, ValuationParams
from src.schemas.cashflow import (
    AnnualCashFlowSummary,
    KeyMetricsSummary,
    LeaseExpirationEntry,
    RentRollEntry,
    TenantCashFlowDetail,
)

# ── Styling constants ──────────────────────────────────────────────────
HEADER_FILL = PatternFill(fill_type="solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(size=16, bold=True)
SUBTITLE_FONT = Font(size=11, bold=True, color="1F4E78")
SECTION_FILL = PatternFill(fill_type="solid", fgColor="D6E4F0")
SECTION_FONT = Font(bold=True, color="1F4E78", size=10)
TOTAL_FONT = Font(bold=True, size=10)
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

CURRENCY_FMT = "$#,##0"
CURRENCY_DEC_FMT = "$#,##0.00"
PCT_FMT = "0.00%"
NUM_FMT = "#,##0.00"
DATE_FMT = "yyyy-mm-dd"

RIGHT = Alignment(horizontal="right", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
CENTER = Alignment(horizontal="center", vertical="center")


def _cell(ws, row, col, value, *, font=None, fill=None, alignment=None, number_format=None):
    c = ws.cell(row=row, column=col, value=value)
    c.border = BORDER
    if font:
        c.font = font
    if fill:
        c.fill = fill
    if alignment:
        c.alignment = alignment
    if number_format:
        c.number_format = number_format
    return c


def _header_row(ws, row, headers, *, start_col=1):
    for i, h in enumerate(headers):
        _cell(ws, row, start_col + i, h, font=HEADER_FONT, fill=HEADER_FILL, alignment=CENTER)


def _d(val) -> float | None:
    if val is None:
        return None
    return float(Decimal(str(val)))


# ── Public entry point ─────────────────────────────────────────────────

def build_full_export_workbook(
    *,
    property_name: str,
    property_type: str,
    total_area: float,
    area_unit: str,
    analysis_start_date: str,
    analysis_period_months: int,
    fiscal_year_end_month: int,
    valuation_name: str,
    valuation_params: dict,
    key_metrics: KeyMetricsSummary | None,
    annual_cash_flows: list[AnnualCashFlowSummary],
    tenant_cash_flows: list[TenantCashFlowDetail],
    rent_roll: list[RentRollEntry],
    lease_expirations: list[LeaseExpirationEntry],
) -> bytes:
    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    _build_key_metrics_sheet(wb, property_name, valuation_name, key_metrics)
    _build_assumptions_sheet(
        wb, property_name, property_type, total_area, area_unit,
        analysis_start_date, analysis_period_months, fiscal_year_end_month,
        valuation_name, valuation_params,
    )
    _build_annual_cf_sheet(wb, property_name, annual_cash_flows)
    _build_tenant_detail_sheet(wb, annual_cash_flows, tenant_cash_flows, area_unit)
    _build_debt_schedule_sheet(wb, valuation_params)
    _build_rent_roll_sheet(wb, rent_roll, area_unit, property_name, valuation_name, analysis_start_date)
    _build_lease_expiration_sheet(wb, lease_expirations, area_unit)

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()


# ── Key Metrics ────────────────────────────────────────────────────────

def _build_key_metrics_sheet(wb, property_name, valuation_name, km: KeyMetricsSummary | None):
    ws = wb.create_sheet("Key Metrics")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:D1")
    _cell(ws, 1, 1, "OpenDCF — Key Metrics", font=TITLE_FONT)
    _cell(ws, 2, 1, f"Property: {property_name}", font=SUBTITLE_FONT)
    _cell(ws, 3, 1, f"Valuation: {valuation_name}", font=SUBTITLE_FONT)
    _cell(ws, 3, 3, f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")

    if km is None:
        _cell(ws, 5, 1, "Valuation has not been run yet.")
        return

    r = 5
    metrics = [
        ("Investment Returns", None),
        ("Net Present Value (NPV)", _d(km.npv), CURRENCY_FMT),
        ("Internal Rate of Return (IRR)", _d(km.irr), PCT_FMT),
        ("Equity Multiple", _d(km.equity_multiple), "0.00x"),
        ("Going-In Cap Rate", _d(km.going_in_cap_rate), PCT_FMT),
        ("Exit Cap Rate", _d(km.exit_cap_rate), PCT_FMT),
        ("", None),
        ("Value Components", None),
        ("PV of Cash Flows", _d(km.pv_of_cash_flows), CURRENCY_FMT),
        ("PV of Terminal Value", _d(km.pv_of_terminal_value), CURRENCY_FMT),
        ("Terminal Value (Gross)", _d(km.terminal_gross_value), CURRENCY_FMT),
        ("Terminal NOI Basis", _d(km.terminal_noi_basis), CURRENCY_FMT),
        ("Exit Costs", _d(km.terminal_exit_costs_amount), CURRENCY_FMT),
        ("Transfer Tax", _d(km.terminal_transfer_tax_amount), CURRENCY_FMT),
        ("Terminal Value (Net)", _d(km.terminal_value), CURRENCY_FMT),
        ("", None),
        ("Property Metrics", None),
        ("Avg Occupancy", _d(km.avg_occupancy_pct), PCT_FMT),
        ("Weighted Avg Lease Term (yrs)", _d(km.weighted_avg_lease_term_years), "0.00"),
        ("", None),
        ("Year 1 Summary", None),
        ("Gross Potential Income", _d(km.year1_gpi), CURRENCY_FMT),
        ("Effective Gross Income", _d(km.year1_egi), CURRENCY_FMT),
        ("Net Operating Income", _d(km.year1_noi), CURRENCY_FMT),
        ("Cash Flow Before Debt", _d(km.year1_cfbd), CURRENCY_FMT),
    ]

    for item in metrics:
        if len(item) == 2:
            # Section header or blank
            label, _ = item
            if label:
                _cell(ws, r, 1, label, font=SECTION_FONT, fill=SECTION_FILL)
                _cell(ws, r, 2, "", fill=SECTION_FILL)
            r += 1
            continue
        label, val, fmt = item
        _cell(ws, r, 1, label, alignment=LEFT)
        _cell(ws, r, 2, val, alignment=RIGHT, number_format=fmt)
        r += 1

    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 30


# ── Assumptions ────────────────────────────────────────────────────────

def _build_assumptions_sheet(
    wb, property_name, property_type, total_area, area_unit,
    analysis_start_date, analysis_period_months, fiscal_year_end_month,
    valuation_name, vp: dict,
):
    ws = wb.create_sheet("Assumptions")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:D1")
    _cell(ws, 1, 1, "OpenDCF — Valuation Assumptions", font=TITLE_FONT)

    r = 3
    def section(label):
        nonlocal r
        _cell(ws, r, 1, label, font=SECTION_FONT, fill=SECTION_FILL)
        _cell(ws, r, 2, "", fill=SECTION_FILL)
        r += 1

    def row(label, val, fmt=None):
        nonlocal r
        _cell(ws, r, 1, label, alignment=LEFT)
        _cell(ws, r, 2, val, alignment=RIGHT, number_format=fmt)
        r += 1

    section("Property")
    row("Name", property_name)
    row("Type", property_type.replace("_", " ").title())
    row("Total Area", total_area, "#,##0")
    row("Area Unit", "Units" if area_unit == "unit" else "SF")
    row("Analysis Start", analysis_start_date)
    row("Analysis Period (months)", analysis_period_months)
    row("Fiscal Year End Month", fiscal_year_end_month)
    r += 1

    section("Valuation")
    row("Scenario", valuation_name)
    row("Discount Rate", _d(vp.get("discount_rate")), PCT_FMT)
    row("Basis of Value", str(vp.get("basis_of_value", "market_value")).replace("_", " ").title())
    row("Intended Use", vp.get("intended_use") or "Not specified")
    row("Risk Treatment", str(vp.get("risk_treatment", "deterministic")).replace("_", " ").title())
    row("Cash Flow / Rate Basis", str(vp.get("cash_flow_basis", "nominal")).title())
    row("Exit Cap Rate", _d(vp.get("exit_cap_rate")), PCT_FMT)
    ecy = vp.get("exit_cap_applied_to_year", -1)
    row("Exit Cap Applied To", "Forward Year (N+1)" if ecy == -1 else f"Year {ecy}")
    row("Exit Costs %", _d(vp.get("exit_costs_pct")), PCT_FMT)
    row("Transfer Tax Preset", str(vp.get("transfer_tax_preset", "none")))
    if vp.get("transfer_tax_custom_rate"):
        row("Custom Transfer Tax Rate", _d(vp["transfer_tax_custom_rate"]), PCT_FMT)
    row("Stabilized Gross-Up", "Yes" if vp.get("apply_stabilized_gross_up") else "No")
    if vp.get("stabilized_occupancy_pct"):
        row("Stabilized Occupancy", _d(vp["stabilized_occupancy_pct"]), PCT_FMT)
    row("Capital Reserves ($/unit/yr)", _d(vp.get("capital_reserves_per_unit")), CURRENCY_DEC_FMT)
    row("Mid-Year Convention", "Yes" if vp.get("use_mid_year_convention") else "No")
    row("Terminal Proceeds Timing", vp.get("terminal_timing", "end_of_period").replace("_", " ").title())
    r += 1

    # Debt
    if vp.get("loan_amount"):
        section("Debt")
        row("Loan Amount", _d(vp["loan_amount"]), CURRENCY_FMT)
        row("Interest Rate", _d(vp.get("interest_rate")), PCT_FMT)
        amort = vp.get("amortization_months")
        row("Amortization", f"{amort} months ({amort // 12} yrs)" if amort else "N/A")
        term = vp.get("loan_term_months")
        row("Loan Term", f"{term} months ({term // 12} yrs)" if term else "N/A")
        io = vp.get("io_period_months", 0)
        row("IO Period", f"{io} months" if io else "None")
    for i, a in enumerate(vp.get("additional_loans") or (), start=2):
        section(a.get("label") or f"Loan {i}")
        row("Loan Amount", _d(a["loan_amount"]), CURRENCY_FMT)
        row("Interest Rate", _d(a["interest_rate"]), PCT_FMT)
        amort = a.get("amortization_months")
        row("Amortization", f"{amort} months ({amort // 12} yrs)" if amort else "360 months")
        term = a.get("loan_term_months")
        row("Loan Term", f"{term} months ({term // 12} yrs)" if term else "Through the sale")
        io = a.get("io_period_months") or 0
        row("IO Period", f"{io} months" if io else "None")

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 28


# ── Annual Cash Flows ──────────────────────────────────────────────────

def _build_annual_cf_sheet(wb, property_name, cfs: list[AnnualCashFlowSummary]):
    ws = wb.create_sheet("Annual Cash Flows")
    ws.sheet_view.showGridLines = False

    ws.merge_cells(f"A1:{get_column_letter(1 + len(cfs))}1")
    _cell(ws, 1, 1, f"OpenDCF — Annual Cash Flow Summary — {property_name}", font=TITLE_FONT)

    if not cfs:
        _cell(ws, 3, 1, "No cash flow data available.")
        return

    # Line items definition: (label, key_or_callable, format, is_section, is_total)
    line_items = [
        ("Revenue", None, None, True, False),
        ("Gross Potential Rent", "gross_potential_rent", CURRENCY_FMT, False, False),
        ("Free Rent", "free_rent", CURRENCY_FMT, False, False),
        ("Absorption Vacancy", "absorption_vacancy", CURRENCY_FMT, False, False),
        ("Loss to Lease", "loss_to_lease", CURRENCY_FMT, False, False),
        ("Expense Recoveries", "expense_recoveries", CURRENCY_FMT, False, False),
        ("Percentage Rent", "percentage_rent", CURRENCY_FMT, False, False),
        ("Other Income", "other_income", CURRENCY_FMT, False, False),
        ("Gross Potential Income", "gross_potential_income", CURRENCY_FMT, False, True),
        ("", None, None, False, False),
        ("Vacancy & Credit Loss", None, None, True, False),
        ("General Vacancy", "general_vacancy_loss", CURRENCY_FMT, False, False),
        ("Credit Loss", "credit_loss", CURRENCY_FMT, False, False),
        ("Effective Gross Income", "effective_gross_income", CURRENCY_FMT, False, True),
        ("", None, None, False, False),
        ("Operating Expenses", None, None, True, False),
        ("Total Operating Expenses", "operating_expenses", CURRENCY_FMT, False, True),
        ("", None, None, False, False),
        ("Net Operating Income", "net_operating_income", CURRENCY_FMT, False, True),
        ("", None, None, False, False),
        ("Capital Items", None, None, True, False),
        ("Tenant Improvements", "tenant_improvements", CURRENCY_FMT, False, False),
        ("Leasing Commissions", "leasing_commissions", CURRENCY_FMT, False, False),
        ("Capital Reserves", "capital_reserves", CURRENCY_FMT, False, False),
        ("Building Improvements", "building_improvements", CURRENCY_FMT, False, False),
        ("", None, None, False, False),
        ("Cash Flow Before Debt", "cash_flow_before_debt", CURRENCY_FMT, False, True),
        ("", None, None, False, False),
        ("Debt Service", "debt_service", CURRENCY_FMT, False, False),
        ("Levered Cash Flow", "levered_cash_flow", CURRENCY_FMT, False, True),
    ]

    # Insert expense detail rows dynamically
    all_cats = set()
    for cf in cfs:
        all_cats.update(cf.expense_detail.keys())
    if all_cats:
        # Find the index of "Total Operating Expenses" and insert before it
        idx = next(i for i, (l, *_) in enumerate(line_items) if l == "Total Operating Expenses")
        for cat in sorted(all_cats):
            line_items.insert(idx, (f"  {cat.replace('_', ' ').title()}", f"expense_detail.{cat}", CURRENCY_FMT, False, False))
            idx += 1

    # Headers
    r = 3
    _cell(ws, r, 1, "", font=HEADER_FONT, fill=HEADER_FILL)
    for i, cf in enumerate(cfs):
        _cell(ws, r, 2 + i, f"Year {cf.year}", font=HEADER_FONT, fill=HEADER_FILL, alignment=CENTER)

    # Data rows
    r = 4
    for label, key, fmt, is_section, is_total in line_items:
        if not label:
            r += 1
            continue

        font = SECTION_FONT if is_section else (TOTAL_FONT if is_total else None)
        fill = SECTION_FILL if is_section else None
        _cell(ws, r, 1, label, font=font, fill=fill, alignment=LEFT)
        if is_section:
            for i in range(len(cfs)):
                _cell(ws, r, 2 + i, "", fill=SECTION_FILL)
        elif key:
            for i, cf in enumerate(cfs):
                if "." in key:
                    # expense_detail.category
                    parts = key.split(".", 1)
                    detail = getattr(cf, parts[0], {})
                    val = _d(detail.get(parts[1], 0))
                else:
                    val = _d(getattr(cf, key, 0))
                _cell(ws, r, 2 + i, val, alignment=RIGHT, number_format=fmt,
                      font=TOTAL_FONT if is_total else None)
        r += 1

    ws.column_dimensions["A"].width = 30
    for i in range(len(cfs)):
        ws.column_dimensions[get_column_letter(2 + i)].width = 16
    ws.freeze_panes = "B4"


# ── Tenant Detail ──────────────────────────────────────────────────────

def _build_tenant_detail_sheet(
    wb,
    annual_cfs: list[AnnualCashFlowSummary],
    tenants: list[TenantCashFlowDetail],
    area_unit: str,
):
    ws = wb.create_sheet("Tenant Detail")
    ws.sheet_view.showGridLines = False

    _cell(ws, 1, 1, "OpenDCF — Tenant Cash Flow Detail", font=TITLE_FONT)

    if not tenants:
        _cell(ws, 3, 1, "No tenant data available.")
        return

    num_years = max(len(t.annual_base_rent) for t in tenants) if tenants else 0
    area_label = "Units" if area_unit == "unit" else "SF"

    # Headers
    r = 3
    headers = ["Suite", "Tenant", "Space Type", f"Area ({area_label})", "Lease Start", "Lease End", "Scenario"]
    for yr in range(1, num_years + 1):
        headers.append(f"Yr {yr} Rent")
    for yr in range(1, num_years + 1):
        headers.append(f"Yr {yr} Recov")
    for yr in range(1, num_years + 1):
        headers.append(f"Yr {yr} TI/LC")
    _header_row(ws, r, headers)

    # Data
    for i, t in enumerate(tenants):
        row = r + 1 + i
        _cell(ws, row, 1, t.suite_name, alignment=LEFT)
        _cell(ws, row, 2, t.tenant_name or "Vacant", alignment=LEFT)
        _cell(ws, row, 3, t.space_type, alignment=LEFT)
        _cell(ws, row, 4, _d(t.area), alignment=RIGHT, number_format=NUM_FMT)
        _cell(ws, row, 5, t.lease_start.isoformat() if t.lease_start else "", alignment=CENTER)
        _cell(ws, row, 6, t.lease_end.isoformat() if t.lease_end else "", alignment=CENTER)
        _cell(ws, row, 7, t.scenario, alignment=LEFT)

        col = 8
        for yr in range(num_years):
            val = _d(t.annual_base_rent[yr]) if yr < len(t.annual_base_rent) else 0
            _cell(ws, row, col + yr, val, alignment=RIGHT, number_format=CURRENCY_FMT)
        col += num_years
        for yr in range(num_years):
            val = _d(t.annual_recoveries[yr]) if yr < len(t.annual_recoveries) else 0
            _cell(ws, row, col + yr, val, alignment=RIGHT, number_format=CURRENCY_FMT)
        col += num_years
        for yr in range(num_years):
            val = _d(t.annual_ti_lc[yr]) if yr < len(t.annual_ti_lc) else 0
            _cell(ws, row, col + yr, val, alignment=RIGHT, number_format=CURRENCY_FMT)

    # Column widths
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 12
    for c in range(8, 8 + num_years * 3):
        ws.column_dimensions[get_column_letter(c)].width = 14

    ws.freeze_panes = "H4"


# ── Debt Schedule ──────────────────────────────────────────────────────

def _build_debt_schedule_sheet(wb, vp: dict):
    ws = wb.create_sheet("Debt Schedule")
    ws.sheet_view.showGridLines = False

    _cell(ws, 1, 1, "OpenDCF — Debt Schedule", font=TITLE_FONT)

    loan_amount = vp.get("loan_amount")
    interest_rate = vp.get("interest_rate")
    first = bool(loan_amount) and interest_rate is not None
    additional = tuple(
        LoanParams(
            loan_amount=Decimal(str(a["loan_amount"])), interest_rate=Decimal(str(a["interest_rate"])),
            amortization_months=a.get("amortization_months"), loan_term_months=a.get("loan_term_months"),
            io_period_months=a.get("io_period_months") or 0,
        )
        for a in vp.get("additional_loans") or ()
    )
    if not first and not additional:
        _cell(ws, 3, 1, "No debt configured for this valuation.")
        return
    if additional:
        _cell(ws, 2, 1, f"All loans combined ({1 + len(additional) if first else len(additional)})")

    # The engine's schedule, so the sheet matches the valuation's debt service
    total_months = vp.get("analysis_period_months", 120)
    params = ValuationParams(
        discount_rate=Decimal(0), exit_cap_rate=Decimal(0), exit_cap_year=-1, exit_costs_pct=Decimal(0),
        capital_reserves_per_unit=Decimal(0), total_property_area=Decimal(0), use_mid_year_convention=False,
        loan_amount=Decimal(str(loan_amount)) if first else None,
        interest_rate=Decimal(str(interest_rate)) if first else None,
        amortization_months=vp.get("amortization_months"), loan_term_months=vp.get("loan_term_months"),
        io_period_months=vp.get("io_period_months") or 0,
        additional_loans=additional,
    )
    service, balances, _ = build_monthly_debt_detail(params, total_months)
    # The schedule ends when the last loan matures (each loan with a term)
    terms = ([params.loan_term_months] if first else []) + [a.loan_term_months for a in additional]
    last_maturity = max(terms) if terms and all(terms) else None

    # Build month-by-month schedule
    r = 3
    _header_row(ws, r, ["Month", "Beg Balance", "Interest", "Principal", "Payment", "End Balance"])

    balance = (params.loan_amount or Decimal(0)) + sum((a.loan_amount for a in additional), Decimal(0))
    row = r + 1
    annual_summaries = []
    yr_interest = Decimal(0)
    yr_principal = Decimal(0)
    yr_payment = Decimal(0)

    for m in range(1, total_months + 1):
        if last_maturity and m > last_maturity:
            break
        beg_bal = balance
        end_bal = balances[m - 1]
        payment = service[m - 1]
        principal = beg_bal - end_bal
        interest = payment - principal

        _cell(ws, row, 1, m, alignment=CENTER)
        _cell(ws, row, 2, float(beg_bal), alignment=RIGHT, number_format=CURRENCY_FMT)
        _cell(ws, row, 3, float(interest), alignment=RIGHT, number_format=CURRENCY_DEC_FMT)
        _cell(ws, row, 4, float(principal), alignment=RIGHT, number_format=CURRENCY_DEC_FMT)
        _cell(ws, row, 5, float(payment), alignment=RIGHT, number_format=CURRENCY_DEC_FMT)
        _cell(ws, row, 6, float(end_bal), alignment=RIGHT, number_format=CURRENCY_FMT)

        balance = end_bal
        yr_interest += interest
        yr_principal += principal
        yr_payment += payment

        if m % 12 == 0 or m == total_months or m == last_maturity:
            annual_summaries.append({
                "year": (m - 1) // 12 + 1,
                "interest": yr_interest,
                "principal": yr_principal,
                "payment": yr_payment,
                "end_balance": balance,
            })
            yr_interest = yr_principal = yr_payment = Decimal(0)

        row += 1

    # Annual summary section below
    row += 2
    _cell(ws, row, 1, "Annual Summary", font=SUBTITLE_FONT)
    row += 1
    _header_row(ws, row, ["Year", "Total Interest", "Total Principal", "Total Debt Service", "End Balance"])
    row += 1
    for s in annual_summaries:
        _cell(ws, row, 1, s["year"], alignment=CENTER)
        _cell(ws, row, 2, float(s["interest"]), alignment=RIGHT, number_format=CURRENCY_FMT)
        _cell(ws, row, 3, float(s["principal"]), alignment=RIGHT, number_format=CURRENCY_FMT)
        _cell(ws, row, 4, float(s["payment"]), alignment=RIGHT, number_format=CURRENCY_FMT)
        _cell(ws, row, 5, float(s["end_balance"]), alignment=RIGHT, number_format=CURRENCY_FMT)
        row += 1

    for c, w in {1: 10, 2: 18, 3: 16, 4: 16, 5: 16, 6: 18}.items():
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A4"


# ── Rent Roll ──────────────────────────────────────────────────────────

def _build_rent_roll_sheet(ws_or_wb, rent_roll, area_unit, property_name, valuation_name, analysis_start):
    """Build rent roll tab. Accepts Workbook (creates sheet) or existing worksheet."""
    if isinstance(ws_or_wb, Workbook):
        ws = ws_or_wb.create_sheet("Rent Roll")
    else:
        ws = ws_or_wb
    ws.sheet_view.showGridLines = False

    _cell(ws, 1, 1, f"OpenDCF — Rent Roll — {property_name}", font=TITLE_FONT)
    _cell(ws, 2, 1, f"Valuation: {valuation_name}")
    _cell(ws, 2, 5, f"Analysis Start: {analysis_start}")

    base_rent_label = "$/Unit/mo" if area_unit == "unit" else "$/SF/yr"
    headers = [
        "Suite", "Space Type", "Area", "Tenant", "Lease Start", "Lease End",
        "Lease Type", f"Base Rent ({base_rent_label})", "Annual Rent", "Recovery Type", "Escalation",
    ]
    r = 4
    _header_row(ws, r, headers)

    for i, rr in enumerate(rent_roll):
        row = r + 1 + i
        _cell(ws, row, 1, rr.suite_name, alignment=LEFT)
        _cell(ws, row, 2, rr.space_type, alignment=LEFT)
        _cell(ws, row, 3, _d(rr.area), alignment=RIGHT, number_format=NUM_FMT)
        _cell(ws, row, 4, rr.tenant_name or "", alignment=LEFT)
        _cell(ws, row, 5, rr.lease_start.isoformat() if rr.lease_start else "", alignment=CENTER)
        _cell(ws, row, 6, rr.lease_end.isoformat() if rr.lease_end else "", alignment=CENTER)
        _cell(ws, row, 7, rr.lease_type or "", alignment=LEFT)
        _cell(ws, row, 8, _d(rr.base_rent_per_unit), alignment=RIGHT, number_format=CURRENCY_DEC_FMT)
        _cell(ws, row, 9, _d(rr.annual_rent), alignment=RIGHT, number_format=CURRENCY_FMT)
        _cell(ws, row, 10, rr.recovery_type or "", alignment=LEFT)
        _cell(ws, row, 11, rr.escalation_type or "", alignment=LEFT)

    widths = {1: 16, 2: 14, 3: 12, 4: 24, 5: 12, 6: 12, 7: 12, 8: 16, 9: 14, 10: 14, 11: 14}
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A5"


# ── Lease Expirations ──────────────────────────────────────────────────

def _build_lease_expiration_sheet(wb, expirations: list[LeaseExpirationEntry], area_unit: str):
    ws = wb.create_sheet("Lease Expirations")
    ws.sheet_view.showGridLines = False

    _cell(ws, 1, 1, "OpenDCF — Lease Expiration Schedule", font=TITLE_FONT)

    if not expirations:
        _cell(ws, 3, 1, "No lease expirations within analysis period.")
        return

    area_label = "Units" if area_unit == "unit" else "SF"
    rent_label = "$/Unit" if area_unit == "unit" else "$/SF"
    headers = ["Year", "Expiring Leases", f"Expiring Area ({area_label})", "% of Total", f"Avg Rent ({rent_label})"]
    r = 3
    _header_row(ws, r, headers)

    for i, exp in enumerate(expirations):
        row = r + 1 + i
        _cell(ws, row, 1, exp.year, alignment=CENTER)
        _cell(ws, row, 2, exp.expiring_leases, alignment=CENTER)
        _cell(ws, row, 3, _d(exp.expiring_area), alignment=RIGHT, number_format=NUM_FMT)
        _cell(ws, row, 4, _d(exp.pct_of_total_gla), alignment=RIGHT, number_format=PCT_FMT)
        _cell(ws, row, 5, _d(exp.weighted_avg_rent_per_sf), alignment=RIGHT, number_format=CURRENCY_DEC_FMT)

    for c, w in {1: 10, 2: 16, 3: 20, 4: 14, 5: 16}.items():
        ws.column_dimensions[get_column_letter(c)].width = w
