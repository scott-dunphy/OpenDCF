"""Excel export debt schedule sheet."""
from decimal import Decimal

from openpyxl import Workbook

from src.services.excel_export import _build_debt_schedule_sheet


def _annual_rows(ws):
    """Rows of the Annual Summary table: (year, interest, principal, debt service, end balance)."""
    start = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "Annual Summary") + 2
    return [tuple(ws.cell(r, c).value for c in range(1, 6)) for r in range(start, ws.max_row + 1)]


def _sheet(**vp):
    wb = Workbook()
    _build_debt_schedule_sheet(wb, {"analysis_period_months": 96, **vp})
    return wb["Debt Schedule"]


def test_zero_interest_loan_is_scheduled():
    ws = _sheet(loan_amount=Decimal("1200000"), interest_rate=Decimal("0"), amortization_months=120)
    assert ws.cell(3, 1).value == "Month"
    rows = _annual_rows(ws)
    assert rows[0][3] == 120000 and rows[0][1] == 0


def test_no_payments_after_loan_is_repaid():
    # 60-month amortization, no maturity, 8-year analysis: years 6-8 carry nothing
    rows = _annual_rows(_sheet(loan_amount=Decimal("1000000"), interest_rate=Decimal("0.06"), amortization_months=60))
    assert len(rows) == 8
    assert abs(rows[4][4]) < 0.01
    assert all(r[3] == 0 for r in rows[5:])


def test_additional_loans_are_combined():
    one = _annual_rows(_sheet(loan_amount=Decimal("1000000"), interest_rate=Decimal("0.06"), amortization_months=360))
    ws = _sheet(loan_amount=Decimal("1000000"), interest_rate=Decimal("0.06"), amortization_months=360,
                additional_loans=[{"label": "Mezz", "loan_amount": "500000", "interest_rate": "0.10",
                                   "io_period_months": 120, "loan_term_months": 120}])
    both = _annual_rows(ws)
    assert ws.cell(2, 1).value == "All loans combined (2)"
    # Interest only at 10% on $500,000: $50,000 more interest and service, the same principal
    assert abs(both[0][1] - one[0][1] - 50000) < 0.01
    assert abs(both[0][2] - one[0][2]) < 0.01
    assert abs(both[0][4] - one[0][4] - 500000) < 0.01


def test_additional_loan_only():
    rows = _annual_rows(_sheet(additional_loans=[{"loan_amount": "500000", "interest_rate": "0.10", "io_period_months": 120}]))
    assert abs(rows[0][3] - 50000) < 0.01
