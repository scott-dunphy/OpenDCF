"""
PDF investment memo / underwriting package generator.

Uses fpdf2 for pure-Python PDF generation (no system dependencies).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO

from fpdf import FPDF

from src.schemas.cashflow import (
    AnnualCashFlowSummary,
    KeyMetricsSummary,
    LeaseExpirationEntry,
    RentRollEntry,
    TenantCashFlowDetail,
)

# ── Colors ─────────────────────────────────────────────────────────────
DARK_BLUE = (31, 78, 120)      # #1F4E78
LIGHT_BLUE = (214, 228, 240)   # #D6E4F0
WHITE = (255, 255, 255)
BLACK = (33, 33, 33)
GRAY = (128, 128, 128)
LIGHT_GRAY = (245, 245, 245)
GOLD = (199, 163, 95)          # accent


def _fmt_currency(val) -> str:
    if val is None:
        return "-"
    n = float(Decimal(str(val)))
    if abs(n) >= 1_000_000:
        return f"${n / 1_000_000:,.2f}M"
    elif abs(n) >= 1_000:
        return f"${n:,.0f}"
    else:
        return f"${n:,.2f}"


def _fmt_pct(val) -> str:
    if val is None:
        return "-"
    return f"{float(Decimal(str(val))) * 100:.2f}%"


def _fmt_num(val, decimals=2) -> str:
    if val is None:
        return "-"
    return f"{float(Decimal(str(val))):,.{decimals}f}"


class InvestmentMemoPDF(FPDF):
    """Custom PDF class with branded header/footer."""

    def __init__(self, property_name: str, valuation_name: str):
        super().__init__(orientation="P", unit="mm", format="letter")
        self.property_name = property_name
        self.valuation_name = valuation_name
        self.set_auto_page_break(auto=True, margin=20)
        self.core_fonts_encoding = "cp1252"  # dashes, curly quotes, euro sign

    def normalize_text(self, text: str) -> str:
        # Built-in fonts cover cp1252 only: other characters print as '?' rather than failing the report
        enc = self.core_fonts_encoding
        return super().normalize_text(text.encode(enc, errors="replace").decode(enc))

    def header(self):
        if self.page_no() == 1:
            return  # Cover page has its own header
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 6, f"OpenDCF  |  {self.property_name}  |  {self.valuation_name}", align="L")
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*GRAY)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*DARK_BLUE)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        # Underline
        self.set_draw_color(*GOLD)
        self.set_line_width(0.5)
        x = self.l_margin
        self.line(x, self.get_y(), x + 60, self.get_y())
        self.ln(4)

    def subsection_title(self, title: str):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*DARK_BLUE)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def metric_table(self, rows: list[tuple[str, str]], col_widths=(85, 45)):
        """Two-column label/value table."""
        self.set_font("Helvetica", "", 9)
        for i, (label, value) in enumerate(rows):
            bg = LIGHT_GRAY if i % 2 == 0 else WHITE
            self.set_fill_color(*bg)
            self.set_text_color(*BLACK)
            self.cell(col_widths[0], 6, f"  {label}", fill=True, align="L")
            self.set_font("Helvetica", "B", 9)
            self.cell(col_widths[1], 6, value, fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "", 9)

    def data_table(self, headers: list[str], rows: list[list[str]], col_widths: list[float]):
        """Generic data table with alternating rows."""
        # Header
        self.set_font("Helvetica", "B", 7)
        self.set_fill_color(*DARK_BLUE)
        self.set_text_color(*WHITE)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, h, fill=True, align="C")
        self.ln()

        # Rows
        self.set_font("Helvetica", "", 7)
        for ri, row in enumerate(rows):
            bg = LIGHT_GRAY if ri % 2 == 0 else WHITE
            self.set_fill_color(*bg)
            self.set_text_color(*BLACK)
            for ci, val in enumerate(row):
                align = "L" if ci == 0 else "R"
                self.cell(col_widths[ci], 5, val, fill=True, align=align)
            self.ln()


# ── Public entry point ─────────────────────────────────────────────────

def build_investment_memo(
    *,
    property_name: str,
    property_type: str,
    total_area: float,
    area_unit: str,
    city: str | None,
    state: str | None,
    analysis_start_date: str,
    analysis_period_months: int,
    valuation_name: str,
    valuation_params: dict,
    key_metrics: KeyMetricsSummary | None,
    annual_cash_flows: list[AnnualCashFlowSummary],
    tenant_cash_flows: list[TenantCashFlowDetail],
    rent_roll: list[RentRollEntry],
    lease_expirations: list[LeaseExpirationEntry],
) -> bytes:
    pdf = InvestmentMemoPDF(property_name, valuation_name)
    pdf.alias_nb_pages()

    _cover_page(pdf, property_name, property_type, total_area, area_unit,
                city, state, analysis_start_date, valuation_name)

    if key_metrics:
        _key_metrics_page(pdf, key_metrics, valuation_params)
        _annual_cf_page(pdf, annual_cash_flows, property_name)
        _rent_roll_page(pdf, rent_roll, area_unit)
        _lease_expiration_page(pdf, lease_expirations, area_unit)
        _tenant_detail_page(pdf, tenant_cash_flows, area_unit)

    out = BytesIO()
    pdf.output(out)
    out.seek(0)
    return out.getvalue()


# ── Cover Page ─────────────────────────────────────────────────────────

def _cover_page(pdf, property_name, property_type, total_area, area_unit,
                city, state, analysis_start, valuation_name):
    pdf.add_page()

    # Top accent bar
    pdf.set_fill_color(*DARK_BLUE)
    pdf.rect(0, 0, 220, 8, "F")

    # Branding
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*GOLD)
    pdf.cell(0, 8, "OPENDCF", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 8, "INVESTMENT MEMO", align="C", new_x="LMARGIN", new_y="NEXT")

    # Property name
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(*DARK_BLUE)
    pdf.multi_cell(0, 12, property_name, align="C")

    # Location
    pdf.ln(3)
    location = ", ".join(filter(None, [city, state]))
    if location:
        pdf.set_font("Helvetica", "", 14)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 8, location, align="C", new_x="LMARGIN", new_y="NEXT")

    # Divider
    pdf.ln(10)
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.4)
    mid = pdf.w / 2
    pdf.line(mid - 30, pdf.get_y(), mid + 30, pdf.get_y())
    pdf.ln(10)

    # Property details
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*BLACK)
    area_label = "Units" if area_unit == "unit" else "SF"
    details = [
        ("Property Type", property_type.replace("_", " ").title()),
        ("Total Area", f"{total_area:,.0f} {area_label}"),
        ("Analysis Start", analysis_start),
        ("Valuation Scenario", valuation_name),
    ]
    for label, val in details:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*GRAY)
        pdf.cell(80, 7, label, align="R")
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*BLACK)
        pdf.cell(80, 7, f"  {val}", align="L", new_x="LMARGIN", new_y="NEXT")

    # Footer
    pdf.set_y(-40)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "Confidential - For Investment Analysis Purposes Only", align="C")

    # Bottom accent bar
    pdf.set_fill_color(*DARK_BLUE)
    pdf.rect(0, pdf.h - 8, 220, 8, "F")


# ── Key Metrics ────────────────────────────────────────────────────────

def _key_metrics_page(pdf, km: KeyMetricsSummary, vp: dict):
    pdf.add_page()
    pdf.section_title("Executive Summary")

    pdf.subsection_title("Investment Returns")
    pdf.metric_table([
        ("Net Present Value (NPV)", _fmt_currency(km.npv)),
        ("Internal Rate of Return (IRR)", _fmt_pct(km.irr)),
        ("Equity Multiple", f"{_fmt_num(km.equity_multiple)}x" if km.equity_multiple else "-"),
        ("Going-In Cap Rate", _fmt_pct(km.going_in_cap_rate)),
        ("Exit Cap Rate", _fmt_pct(km.exit_cap_rate)),
    ])

    pdf.ln(4)
    pdf.subsection_title("Value Components")
    pdf.metric_table([
        ("PV of Cash Flows", _fmt_currency(km.pv_of_cash_flows)),
        ("PV of Terminal Value", _fmt_currency(km.pv_of_terminal_value)),
        ("Terminal Value (Net)", _fmt_currency(km.terminal_value)),
        ("Terminal NOI Basis", _fmt_currency(km.terminal_noi_basis)),
    ])

    pdf.ln(4)
    pdf.subsection_title("Property Metrics")
    pdf.metric_table([
        ("Avg Occupancy", _fmt_pct(km.avg_occupancy_pct)),
        ("Weighted Avg Lease Term", f"{_fmt_num(km.weighted_avg_lease_term_years)} years" if km.weighted_avg_lease_term_years else "-"),
    ])

    pdf.ln(4)
    pdf.subsection_title("Year 1 Summary")
    pdf.metric_table([
        ("Gross Potential Income", _fmt_currency(km.year1_gpi)),
        ("Effective Gross Income", _fmt_currency(km.year1_egi)),
        ("Net Operating Income", _fmt_currency(km.year1_noi)),
        ("Cash Flow Before Debt", _fmt_currency(km.year1_cfbd)),
    ])

    # Valuation assumptions
    pdf.ln(4)
    pdf.subsection_title("Valuation Assumptions")
    assumptions = [
        ("Discount Rate", _fmt_pct(vp.get("discount_rate"))),
        ("Exit Cap Rate", _fmt_pct(vp.get("exit_cap_rate"))),
        ("Exit Costs", _fmt_pct(vp.get("exit_costs_pct"))),
        ("Capital Reserves", _fmt_currency(vp.get("capital_reserves_per_unit")) + "/unit/yr"),
        ("Mid-Year Convention", "Yes" if vp.get("use_mid_year_convention") else "No"),
        ("Basis of Value", str(vp.get("basis_of_value", "market_value")).replace("_", " ").title()),
        ("Intended Use", vp.get("intended_use") or "Not specified"),
        ("Risk Treatment", str(vp.get("risk_treatment", "deterministic")).replace("_", " ").title()),
        ("Cash Flow / Rate Basis", str(vp.get("cash_flow_basis", "nominal")).title()),
        ("Terminal Proceeds Timing", vp.get("terminal_timing", "end_of_period").replace("_", " ").title()),
    ]
    if vp.get("loan_amount"):
        assumptions.extend([
            ("Loan Amount", _fmt_currency(vp["loan_amount"])),
            ("Interest Rate", _fmt_pct(vp.get("interest_rate"))),
        ])
    for i, a in enumerate(vp.get("additional_loans") or (), start=2):
        name = a.get("label") or f"Loan {i}"
        assumptions.append((name, f"{_fmt_currency(a['loan_amount'])} at {_fmt_pct(a['interest_rate'])}"))
    pdf.metric_table(assumptions)


# ── Annual Cash Flows ──────────────────────────────────────────────────

def _annual_cf_page(pdf, cfs: list[AnnualCashFlowSummary], property_name: str):
    if not cfs:
        return

    pdf.add_page("L")  # Landscape for wide tables
    pdf.section_title("Annual Cash Flow Summary")

    # Limit to 10 years for readability
    display_cfs = cfs[:10]
    num_years = len(display_cfs)

    headers = [""] + [f"Year {cf.year}" for cf in display_cfs]
    col_w = min(22, (pdf.w - 20 - 55) / num_years)
    col_widths = [55] + [col_w] * num_years

    line_items = [
        ("Gross Potential Rent", "gross_potential_rent"),
        ("Free Rent", "free_rent"),
        ("Expense Recoveries", "expense_recoveries"),
        ("Other Income", "other_income"),
        ("Gross Potential Income", "gross_potential_income"),
        ("General Vacancy", "general_vacancy_loss"),
        ("Credit Loss", "credit_loss"),
        ("Effective Gross Income", "effective_gross_income"),
        ("Operating Expenses", "operating_expenses"),
        ("Net Operating Income", "net_operating_income"),
        ("Tenant Improvements", "tenant_improvements"),
        ("Leasing Commissions", "leasing_commissions"),
        ("Capital Reserves", "capital_reserves"),
        ("Cash Flow Before Debt", "cash_flow_before_debt"),
        ("Debt Service", "debt_service"),
        ("Levered Cash Flow", "levered_cash_flow"),
    ]

    rows = []
    totals = {"gross_potential_income", "effective_gross_income", "net_operating_income",
              "cash_flow_before_debt", "levered_cash_flow"}
    for label, key in line_items:
        row = [label]
        for cf in display_cfs:
            val = getattr(cf, key, 0)
            row.append(_fmt_currency(val))
        rows.append(row)

    pdf.data_table(headers, rows, col_widths)

    if len(cfs) > 10:
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 5, f"Showing first 10 of {len(cfs)} years. Full data available in Excel export.")


# ── Rent Roll ──────────────────────────────────────────────────────────

def _rent_roll_page(pdf, rent_roll: list[RentRollEntry], area_unit: str):
    if not rent_roll:
        return

    pdf.add_page()
    pdf.section_title("Current Rent Roll")

    rent_label = "$/Unit/mo" if area_unit == "unit" else "$/SF/yr"
    headers = ["Suite", "Tenant", "Area", "Start", "End", f"Rent ({rent_label})", "Annual Rent", "Recovery"]
    col_widths = [24, 38, 18, 20, 20, 22, 22, 22]

    rows = []
    for rr in rent_roll:
        rows.append([
            rr.suite_name,
            rr.tenant_name or "Vacant",
            _fmt_num(rr.area, 0),
            rr.lease_start.isoformat() if rr.lease_start else "",
            rr.lease_end.isoformat() if rr.lease_end else "",
            _fmt_currency(rr.base_rent_per_unit) if rr.base_rent_per_unit else "-",
            _fmt_currency(rr.annual_rent) if rr.annual_rent else "-",
            (rr.recovery_type or "").upper(),
        ])

    pdf.data_table(headers, rows, col_widths)


# ── Lease Expirations ──────────────────────────────────────────────────

def _lease_expiration_page(pdf, expirations: list[LeaseExpirationEntry], area_unit: str):
    if not expirations:
        return

    pdf.add_page()
    pdf.section_title("Lease Expiration Schedule")

    area_label = "Units" if area_unit == "unit" else "SF"
    headers = ["Year", "Leases", f"Area ({area_label})", "% of Total", "Avg Rent"]
    col_widths = [20, 20, 30, 25, 25]

    rows = []
    for exp in expirations:
        rows.append([
            str(exp.year),
            str(exp.expiring_leases),
            _fmt_num(exp.expiring_area, 0),
            _fmt_pct(exp.pct_of_total_gla),
            _fmt_currency(exp.weighted_avg_rent_per_sf),
        ])

    pdf.data_table(headers, rows, col_widths)


# ── Tenant Detail ──────────────────────────────────────────────────────

def _tenant_detail_page(pdf, tenants: list[TenantCashFlowDetail], area_unit: str):
    if not tenants:
        return

    pdf.add_page("L")
    pdf.section_title("Tenant Cash Flow Detail")

    num_years = max(len(t.annual_base_rent) for t in tenants) if tenants else 0
    # Cap at 10 years for PDF readability
    show_years = min(num_years, 10)

    headers = ["Suite", "Tenant", "Area", "Scenario"]
    for yr in range(1, show_years + 1):
        headers.append(f"Yr {yr} Rent")
    col_w = min(20, (pdf.w - 20 - 72) / show_years) if show_years else 20
    col_widths = [22, 28, 14, 14] + [col_w] * show_years

    rows = []
    for t in tenants:
        row = [
            t.suite_name,
            t.tenant_name or "Vacant",
            _fmt_num(t.area, 0),
            t.scenario,
        ]
        for yr in range(show_years):
            val = t.annual_base_rent[yr] if yr < len(t.annual_base_rent) else 0
            row.append(_fmt_currency(val))
        rows.append(row)

    pdf.data_table(headers, rows, col_widths)

    if num_years > 10:
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 5, f"Showing first 10 of {num_years} years. Full data available in Excel export.")
