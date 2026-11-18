"""
Generate an import template laid out like an XL4ADW input workbook: a header
block in column A (VIEW, ACTION, ...), field names on the COL row, an EXAMPLE
row, and data from the row after COL. Column names follow XL4ADW naming where
the guide documents it and are all recognized by the importer.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

TEMPLATE_SHEETS: dict[str, list[tuple[str, object]]] = {
    "PropertyAssets": [
        ("Property_ExternalID", "P-1001"), ("Name", "Example Office Center"), ("PropertyType_ID", "Office"),
        ("Address", "100 Main St"), ("City", "Dallas"), ("State", "TX"), ("ZipCode", "75201"),
        ("Market", "Dallas-Fort Worth"), ("AnalysisBegin", "2026-01-01"), ("AnalysisLength_PD", "10Y0M0W0D"),
        ("BuildingArea", 50000), ("YearBuilt", 2005), ("PurchasePrice", 12500000), ("PortfolioName", "Fund I"),
    ],
    "MarketLeases": [
        ("Property_ExternalID", "P-1001"), ("ExternalID", "MLA-OFF"), ("Name", "Office"),
        ("MR_Amount_APM", 32), ("MR_Inflation_AEY", 0.03), ("TermLength_PD", "5Y0M0W0D"),
        ("RenewalProbability", 0.65), ("MonthsVacant", 6), ("TI_NewAmount_APM", 40), ("TI_RenewAmount_APM", 15),
        ("Amount_APM", 0.06), ("RenewAmount_APM", 0.03), ("RF_Amount_APM", 3), ("RF_RenewAmount_APM", 1),
        ("GeneralVacancy", 0.05), ("CreditLoss", 0.01),
    ],
    "Leases": [
        ("Property_ExternalID", "P-1001"), ("ExternalID", "L-1"), ("TenantName", "Acme Corp"),
        ("Suite", "100"), ("Area", 10000), ("LeaseBegin", "2023-01-01"), ("FixedExpiryDate", "2030-12-31"),
        ("BaseRent", 30), ("BaseRentUnit_ID", "$/Area/Year"), ("AnnualIncrease", 0.03),
        ("RecoveryStructure_ExtID", "NNN"), ("LeaseProfile_ExternalID", "MLA-OFF"), ("RentFree_APUL", ""),
        ("UponExpiration_ID", "Market"),
    ],
    "OperatingExpenses": [
        ("Property_ExternalID", "P-1001"), ("ExternalID", "E-1"), ("Name", "Real Estate Taxes"),
        ("Amount1_APM", "10000P"), ("Unit_ID", "$ Amount"), ("Amount1Inflation_AEM", 0.03),
        ("IsRecoverable", True),
    ],
    "OtherRevenues": [
        ("Property_ExternalID", "P-1001"), ("ExternalID", "R-1"), ("Name", "Parking"),
        ("Amount1_APM", "2000P"), ("Amount1Inflation_AEM", 0.03),
    ],
    "CapitalExpenses": [
        ("Property_ExternalID", "P-1001"), ("ExternalID", "C-1"), ("Name", "Roof replacement"),
        ("Amount1_ATL", "2027/06|150000;2027/07|150000;"),
    ],
    "Loans": [
        ("Property_ExternalID", "P-1001"), ("ExternalID", "D-1"), ("Amount", 7500000), ("InterestRate", 0.055),
        ("Amortization_PD", "30Y0M0W0D"), ("Term_PD", "10Y0M0W0D"), ("InterestOnly_PD", "2Y0M0W0D"),
        ("LoanFees", 0.01),
    ],
    "Valuation": [
        ("Property_ExternalID", "P-1001"), ("DiscountRate", 0.08), ("ExitCapRate", 0.065), ("SellingCosts", 0.02),
    ],
    "LoanTape": [
        ("LoanID", "LN-1001"), ("Property_ExternalID", "P-1001"), ("PropertyName", "Example Office Center"),
        ("PropertyType", "Office"), ("Market", "Dallas-Fort Worth"), ("NRA", 50000), ("LienPosition", 1),
        ("OriginationDate", "2021-06-15"), ("OriginalBalance", 8000000), ("MaturityDate", "2031-07-01"),
        ("RateType", "Fixed"), ("Coupon", 0.0425), ("Spread", ""), ("IndexFloor", ""),
        ("AmortizationMonths", 360), ("IOMonths", 36), ("Extensions", 0), ("ExtensionMonths", 0),
        ("CurrentBalance", 7900000), ("AsOfDate", "2025-09-30"), ("DelinquencyStatus", "Current"),
        ("OriginationValue", 12500000), ("OriginationNOI", 820000), ("CurrentNOI", 860000),
        ("CurrentValue", 12000000), ("ValueDate", "2025-06-30"), ("Occupancy", 0.92), ("ExitCapRate", 0.0725),
        ("PortfolioName", "Fund I"),
    ],
    "AssumptionProfiles": [
        ("Name", "Office — Dallas"), ("Portfolio", "Fund I"), ("PropertyType", "Office"),
        ("Market", "Dallas-Fort Worth"), ("discount_rate", 0.0775), ("exit_cap_rate", 0.07),
        ("market_rent_growth", 0.03), ("general_vacancy_pct", 0.07),
    ],
}

_HEADER_FILL = PatternFill("solid", fgColor="DDE7F0")


def build_template() -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, cols in TEMPLATE_SHEETS.items():
        ws = wb.create_sheet(name)
        meta = [
            ("HOSTINFO", "Ares import template"), ("PORTFOLIO", ""), ("SCENARIO", ""), ("TIMESTAMP", ""),
            ("USER", ""), ("VERSION", "XL4ADW layout"), ("VIEW", name),
        ]
        for r, (k, v) in enumerate(meta, start=1):
            ws.cell(row=r, column=1, value=k).font = Font(bold=True)
            ws.cell(row=r, column=2, value=v)
        ws.cell(row=8, column=1, value="EXAMPLE").font = Font(bold=True)
        ws.cell(row=9, column=1, value="ACTION").font = Font(bold=True)
        ws.cell(row=10, column=1, value="COL").font = Font(bold=True)
        for c, (header, example) in enumerate(cols, start=2):
            ws.cell(row=8, column=c, value=example)
            cell = ws.cell(row=10, column=c, value=header)
            cell.font = Font(bold=True)
            cell.fill = _HEADER_FILL
            ws.cell(row=11, column=c, value=example)
            ws.column_dimensions[cell.column_letter].width = max(14, len(header) + 2)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
