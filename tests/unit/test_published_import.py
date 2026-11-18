"""Unit tests for XL4ADW time series decoding and workbook mapping."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from src.schemas.imports import ImportOptions
from src.services.published_import.mapper import ImportMapper, map_expense_category, map_recovery
from src.services.published_import.timeseries import (
    parse_amount_list,
    parse_dated_list,
    parse_period_list,
    parse_period_months,
    parse_series,
)
from src.services.published_import.workbook import read_workbook, split_suffix

D = Decimal


class TestTimeSeries:
    def test_apm_perpetual(self):
        s = parse_amount_list("1000;0;0;0;2000;0P;")
        assert s.values[:5] == [D(1000), D(0), D(0), D(0), D(2000)]
        assert s.perpetual and s.at(50) == D(0)

    def test_apm_perpetual_tail_repeats(self):
        s = parse_amount_list("100;200P")
        assert s.sum_first(12) == D(100) + D(200) * 11

    def test_aem_zero_after_last(self):
        s = parse_series("1000;0;0;0;2000;", "_AEM")
        assert not s.perpetual and s.at(10) == D(0)

    def test_apcl(self):
        s = parse_period_list("1|200;4|300;6|400P;")
        assert s.values == [D(200)] * 3 + [D(300)] * 2 + [D(400)]
        assert s.at(20) == D(400)

    def test_atl(self):
        assert parse_dated_list("2010/01|1000;2010/02|0;") == [(date(2010, 1, 1), D(1000)), (date(2010, 2, 1), D(0))]

    def test_period(self):
        assert parse_period_months("5Y0M0W0D") == 60
        assert parse_period_months("2Y6M0W0D") == 30
        assert parse_period_months("10 years") == 120
        assert parse_period_months(36) == 36

    def test_split_suffix(self):
        assert split_suffix("MR_Amount_APM") == ("mramount", "_APM")
        assert split_suffix("LeaseProfile_ExternalID") == ("leaseprofile", "_EXTERNALID")
        assert split_suffix("TenantName") == ("tenantname", None)


class TestMappingRules:
    def test_recovery(self):
        assert map_recovery("Triple Net", "retail") == ("nnn", False)
        assert map_recovery("Base Year Stop", "office") == ("base_year_stop", False)
        assert map_recovery("Full Service Gross", "office") == ("full_service_gross", False)
        assert map_recovery("Modified Gross", "office") == ("modified_gross", False)
        assert map_recovery(None, "office") == ("base_year_stop", True)
        assert map_recovery("???", "industrial") == ("nnn", True)

    def test_expense_category(self):
        assert map_expense_category("Real Estate Taxes") == "real_estate_taxes"
        assert map_expense_category("CAM - Janitorial") == "cam"
        assert map_expense_category("Management Fee") == "management_fee"
        assert map_expense_category("Elevator Contract") == "Elevator Contract"


def _xl4adw_sheet(wb, name, headers, rows, actions=None, row_actions=None):
    ws = wb.create_sheet(name)
    for r, k in enumerate(["HOSTINFO", "PORTFOLIO", "SCENARIO", "TIMESTAMP", "USER", "VERSION", "VIEW"], 1):
        ws.cell(row=r, column=1, value=k)
    ws.cell(row=7, column=2, value=name)
    ws.cell(row=8, column=1, value="EXAMPLE")
    ws.cell(row=9, column=1, value="ACTION")
    for c, a in (actions or {}).items():
        ws.cell(row=9, column=headers.index(c) + 2, value=a)
    ws.cell(row=10, column=1, value="COL")
    for c, h in enumerate(headers, 2):
        ws.cell(row=10, column=c, value=h)
    for r, row in enumerate(rows, 11):
        if row_actions and row_actions.get(r - 11):
            ws.cell(row=r, column=1, value=row_actions[r - 11])
        for c, v in enumerate(row, 2):
            ws.cell(row=r, column=c, value=v)


def _to_bytes(wb) -> bytes:
    wb.remove(wb["Sheet"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestXl4adwWorkbook:
    def test_skip_rows_and_columns_and_rent_steps(self):
        wb = Workbook()
        _xl4adw_sheet(wb, "PropertyAssets",
                      ["Property_ExternalID", "Name", "PropertyType_ID", "AnalysisBegin", "AnalysisEndPlusOne"],
                      [["A1", "Strip Center", "Shopping Center", date(2026, 1, 1), date(2031, 1, 1)]])
        _xl4adw_sheet(wb, "AreaMeasures", ["Property_ExternalID", "Name", "Area"],
                      [["A1", "Building Area", 20000]])
        _xl4adw_sheet(
            wb, "Leases",
            ["Property_ExternalID", "TenantName", "Suite", "Area", "LeaseBegin", "FixedTerm_PD",
             "BaseRent_APCL", "RecoveryStructure_ExtID", "PR_SalesPercent", "Breakpoint", "PR_SalesAmount_APM",
             "RentFree_APUL", "Junk"],
            [
                ["A1", "Grocer", "A", 15000, date(2024, 1, 1), "10Y0M0W0D", "1|20;61|22P", "NNN",
                 0.05, 5000000, "500000P", "1|1;3|0", "x"],
                ["A1", "Skipped Co", "B", 5000, date(2024, 1, 1), "5Y0M0W0D", 25, "NNN", None, None, None, None, "y"],
            ],
            actions={"Junk": "SKIP"},
            row_actions={1: "SKIP"},
        )
        sheets = read_workbook(_to_bytes(wb))
        payload, reports = ImportMapper(sheets, ImportOptions(), "x.xlsx").build()
        lease_report = next(r for r in reports if r.recognized_as == "lease")
        assert "Junk" not in lease_report.unmapped_columns and "Junk" not in lease_report.mapped_columns
        p = payload.properties[0]
        assert p.property_type == "retail"
        assert p.analysis_period_months == 60
        assert p.total_area == 20000
        assert len(p.leases) == 1
        lease = p.leases[0]
        assert lease.lease_end_date == date(2033, 12, 31)
        assert lease.escalation_type == "fixed_step"
        assert [(s.effective_date, s.rent_per_unit) for s in lease.rent_steps] == [
            (date(2024, 1, 1), D(20)), (date(2029, 1, 1), D(22)),
        ]
        assert lease.free_rent_months == 2
        assert lease.pct_rent_rate == D("0.05")
        assert lease.projected_annual_sales_per_sf == D(500000) * 12 / 15000

    def test_vacant_suite_takes_mla_name_and_explicit_growth_survives_inflation(self):
        wb = Workbook()
        _xl4adw_sheet(wb, "PropertyAssets",
                      ["Property_ExternalID", "Name", "PropertyType_ID", "AnalysisBegin", "AnalysisEndPlusOne"],
                      [["A1", "Tower", "Office", date(2026, 1, 1), date(2031, 1, 1)]])
        _xl4adw_sheet(wb, "MarketLeasing", ["Property_ExternalID", "ExternalID", "Name", "MR_Amount", "MR_Inflation"],
                      [["A1", "MLA-OFF", "Office", 30, 3], ["A1", "MLA-RET", "Retail", 25, None]])
        _xl4adw_sheet(wb, "Inflation", ["Property_ExternalID", "Name", "Rate"], [["A1", "General", 2.5]])
        _xl4adw_sheet(
            wb, "Leases",
            ["Property_ExternalID", "TenantName", "Suite", "Area", "LeaseBegin", "FixedTerm_PD", "BaseRent_APCL",
             "LeaseProfile_ExternalID"],
            [["A1", "Acme", "100", 5000, date(2024, 1, 1), "5Y0M0W0D", 28, "MLA-OFF"],
             ["A1", "Vacant", "200", 3000, None, None, None, "MLA-OFF"]],
        )
        payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(), "x.xlsx").build()
        p = payload.properties[0]
        assert {s.suite_name: s.space_type for s in p.suites} == {"100": "Office", "200": "Office"}
        growth = {m.space_type: m.rent_growth_rate_pct for m in p.market_profiles}
        assert growth == {"Office": D("0.03"), "Retail": D("0.025")}

    def test_plain_rent_roll_single_sheet(self):
        wb = Workbook()
        ws = wb.create_sheet("Rent Roll")
        ws.append(["Tenant", "Suite", "SF", "Lease Start", "Lease End", "Annual Rent", "Reimbursement"])
        ws.append(["Alpha LLC", "101", 2000, "2024-01-01", "2028-12-31", 60000, "Full Service Gross"])
        ws.append(["Vacant", "102", 1500, None, None, None, None])
        payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(
            analysis_start_date=date(2026, 1, 1), default_property_type="office",
        ), "Tower.xlsx").build()
        p = payload.properties[0]
        assert p.name == "Tower" and p.total_area == 3500
        assert len(p.suites) == 2 and len(p.leases) == 1
        assert p.leases[0].base_rent_per_unit == D(30)  # $60K / 2,000 SF
        assert p.leases[0].recovery_type == "full_service_gross"
        assert any("No market leasing profile" in w for w in p.warnings)

    def test_multifamily_unit_mix(self):
        wb = Workbook()
        ws = wb.create_sheet("MultiFamily")
        ws.append(["Unit Type", "Units", "Market Rent", "Current Rent", "Occupancy"])
        ws.append(["1BR", 100, 1500, 1450, 0.95])
        ws.append(["2BR", 50, 2000, None, 0.93])
        payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(
            analysis_start_date=date(2026, 1, 1)), "apts.xlsx").build()
        p = payload.properties[0]
        assert p.property_type == "multifamily" and p.area_unit == "unit" and p.total_area == 150
        assert {m.space_type: m.general_vacancy_pct for m in p.market_profiles} == {"1BR": D("0.05"), "2BR": D("0.07")}
        assert len(p.leases) == 1 and p.leases[0].rent_payment_frequency == "monthly"

    def test_self_storage_unit_mix_with_sizes_becomes_a_model(self):
        import json

        wb = Workbook()
        ws = wb.create_sheet("Storage Units")
        ws.append(["Unit Size", "Units", "Occupied Units", "Street Rate", "In-Place Rent", "Climate Controlled"])
        ws.append(["5x10", 100, 90, 80, 88, "Yes"])
        ws.append(["10x20 Drive-Up", 40, 36, 190, 205, "No"])
        payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(
            analysis_start_date=date(2026, 1, 1)), "storage.xlsx").build()
        p = payload.properties[0]
        assert p.property_type == "self_storage" and p.area_unit == "sf" and p.total_area == 13000
        assert p.suites == [] and p.leases == []
        units = json.loads(p.self_storage_assumptions_json)["unit_types"]
        assert units[0]["sf_per_unit"] == "50" and units[0]["climate_controlled"] is True
        assert units[1]["access"] == "drive_up" and units[1]["in_place_rate"] == "205"

    def test_self_storage_without_sizes_keeps_the_rent_roll_path(self):
        wb = Workbook()
        ws = wb.create_sheet("Storage")
        ws.append(["Unit Type", "Units", "Market Rent", "Occupancy"])
        ws.append(["Small", 100, 80, 0.9])
        mapper = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(
            analysis_start_date=date(2026, 1, 1)), "s.xlsx")
        payload, _ = mapper.build()
        p = payload.properties[0]
        assert p.self_storage_assumptions_json is None and p.area_unit == "unit" and len(p.suites) == 1
        assert any("no unit sizes" in w for w in mapper.warnings)

    def test_column_mapping_override(self):
        wb = Workbook()
        ws = wb.create_sheet("Leases")
        ws.append(["Occupant Name", "Space", "Sq Ft", "From", "To", "Rate"])
        ws.append(["Beta", "1", 1000, "2025-01-01", "2029-12-31", 20])
        opts = ImportOptions(column_mapping={"Leases": {
            "Occupant Name": "tenant_name", "Sq Ft": "area", "From": "start", "To": "end", "Rate": "base_rent",
        }})
        payload, reports = ImportMapper(read_workbook(_to_bytes(wb)), opts, "m.xlsx").build()
        assert payload.properties[0].leases[0].base_rent_per_unit == D(20)
        assert reports[0].unmapped_columns == []


class TestLoanTape:
    def _tape(self, sheet_name="Loans"):
        wb = Workbook()
        ws = wb.create_sheet(sheet_name)
        ws.append(["Loan Number", "Property Name", "Property Type", "Origination Date", "Maturity Date",
                   "Original Loan Amount", "Current Balance", "Rate Type", "Interest Rate", "Spread",
                   "Floor", "Amortization (Years)", "IO Period", "Lien", "Status", "NOI", "Appraised Value",
                   "NRA"])
        ws.append(["L-1", "Main St Office", "Office", "2021-06-15", "2031-07-01", 8_000_000, 7_900_000,
                   "Fixed", "4.25%", None, None, 30, 36, "Senior", "Current", 860_000, 12_000_000, 50000])
        ws.append(["L-2", "Elm Industrial", "Warehouse", "2023-02-01", "2026-02-01", 5_000_000, 5_000_000,
                   "Floating", None, 325, "1.00%", "IO", "Yes", "B-Note", "90+ days", 400_000, 6_500_000,
                   80000])
        ws.append(["L-3", "Bad Row", "Office", "2025-01-01", "2020-01-01", 1, 1, "Fixed", 0.05])
        return read_workbook(_to_bytes(wb))

    def test_plain_loans_sheet_is_a_loan_tape(self):
        payload, reports = ImportMapper(self._tape(), ImportOptions(), "tape.xlsx").build()
        assert reports[0].recognized_as == "loan_tape"
        loans = {l.external_id: l for l in payload.loans}
        assert set(loans) == {"L-1", "L-2"}                 # L-3 matures before it starts

        a = loans["L-1"]
        assert a.rate_type == "fixed" and a.coupon == D("0.0425")
        assert a.amortization_months == 360 and a.io_months == 36
        assert a.reported_balance == 7_900_000 and a.lien_position == 1
        assert a.property_type == "office" and a.tape_noi == 860_000 and a.tape_value == 12_000_000

        b = loans["L-2"]
        assert b.rate_type == "floating" and b.spread == D("0.0325") and b.index_floor == D("0.01")
        assert b.amortization_months is None and b.io_months == 0
        assert b.lien_position == 2 and b.delinquency_status == "90_plus"
        assert b.property_type == "industrial"

    def test_sheet_named_by_kind(self):
        payload, reports = ImportMapper(self._tape("Loan Tape"), ImportOptions(), "x.xlsx").build()
        assert reports[0].recognized_as == "loan_tape" and len(payload.loans) == 2


def test_rate_of_one_is_one_percent_but_share_of_one_is_full():
    from src.services.published_import.mapper import _rate, _rate_schedule
    assert _rate(1) == D("0.01")
    assert _rate(2) == D("0.02")
    assert _rate("0.03") == D("0.03")
    assert _rate(1, share=True) == D(1)
    assert _rate(75, share=True) == D("0.75")
    assert _rate_schedule("1;2", "_AEY") == [D("0.01"), D("0.02")]


def test_partial_final_year_is_extended_to_whole_year():
    wb = Workbook()
    _xl4adw_sheet(wb, "PropertyAssets",
                  ["Property_ExternalID", "Name", "PropertyType_ID", "AnalysisBegin", "AnalysisEndPlusOne"],
                  [["A1", "Tower", "Office", date(2026, 1, 1), date(2036, 7, 1)]])
    _xl4adw_sheet(wb, "AreaMeasures", ["Property_ExternalID", "Name", "Area"], [["A1", "Building Area", 20000]])
    payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(), "x.xlsx").build()
    p = payload.properties[0]
    assert p.analysis_period_months == 132
    assert any("126 months extended to 11 whole years" in w for w in p.warnings)


def test_mid_month_analysis_start_moves_to_next_month():
    wb = Workbook()
    _xl4adw_sheet(wb, "PropertyAssets",
                  ["Property_ExternalID", "Name", "PropertyType_ID", "AnalysisBegin", "AnalysisEndPlusOne"],
                  [["A1", "Tower", "Office", date(2026, 1, 15), date(2036, 2, 1)]])
    _xl4adw_sheet(wb, "AreaMeasures", ["Property_ExternalID", "Name", "Area"], [["A1", "Building Area", 20000]])
    payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(), "x.xlsx").build()
    p = payload.properties[0]
    assert p.analysis_start_date == date(2026, 2, 1)
    assert p.analysis_period_months == 120
    assert any("moved to the first of the next month" in w for w in p.warnings)


def test_yearly_series_keep_year_by_year_market_and_property_rates():
    from src.services.published_import.mapper import _rate_schedule
    assert _rate_schedule("1;0.9", "_AEY", share=True) == [D(1), D("0.9")]   # a share of 1 is 100%
    wb = Workbook()
    _xl4adw_sheet(wb, "PropertyAssets",
                  ["Property_ExternalID", "Name", "PropertyType_ID", "AnalysisBegin", "AnalysisEndPlusOne"],
                  [["A1", "Tower", "Office", date(2026, 1, 1), date(2031, 1, 1)]])
    _xl4adw_sheet(wb, "MarketLeasing",
                  ["Property_ExternalID", "ExternalID", "Name", "MR_Amount", "RenewalProbability_AEY",
                   "MonthsVacant_AEY", "RF_Amount_AEY", "CreditLoss_AEY"],
                  [["A1", "MLA-OFF", "Office", 30, "0.7;0.6;0.5", "6;9", "3;2", "0.01;0.02"]])
    _xl4adw_sheet(wb, "Vacancies", ["Property_ExternalID", "Rate_AEY"], [["A1", "0.05;0.08;0.06"]])
    _xl4adw_sheet(wb, "Inflation", ["Property_ExternalID", "Name", "Rate_AEY"], [["A1", "General", "0.02;0.03"]])
    _xl4adw_sheet(wb, "OperatingExpenses", ["Property_ExternalID", "Name", "Amount1"], [["A1", "Taxes", 100000]])
    _xl4adw_sheet(wb, "Leases",
                  ["Property_ExternalID", "TenantName", "Suite", "Area", "LeaseBegin", "FixedTerm_PD", "BaseRent_APCL",
                   "LeaseProfile_ExternalID"],
                  [["A1", "Acme", "100", 5000, date(2024, 1, 1), "5Y0M0W0D", 28, "MLA-OFF"]])
    payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(), "x.xlsx").build()
    p = payload.properties[0]
    m = p.market_profiles[0]
    assert m.renewal_probability == D("0.7")
    assert m.renewal_probability_schedule == [D("0.7"), D("0.6"), D("0.5")]
    assert m.downtime_months == 6 and m.downtime_schedule == [6, 9]
    assert m.new_tenant_free_rent_months == 3 and m.new_free_rent_schedule == [D(3), D(2)]
    assert m.credit_loss_schedule == [D("0.01"), D("0.02")]
    # The property's vacancy sheet replaces the MLA's vacancy, schedule included
    assert m.general_vacancy_pct == D("0.05")
    assert m.general_vacancy_schedule == [D("0.05"), D("0.08"), D("0.06")]
    # General inflation fills default growth year by year
    assert m.rent_growth_rate_pct == D("0.02") and m.rent_growth_schedule == [D("0.02"), D("0.03")]
    assert p.expenses[0].growth_schedule == [D("0.02"), D("0.03")]


def test_out_of_range_by_year_values_are_dropped_with_a_warning():
    wb = Workbook()
    _xl4adw_sheet(wb, "PropertyAssets",
                  ["Property_ExternalID", "Name", "PropertyType_ID", "AnalysisBegin", "AnalysisEndPlusOne"],
                  [["A1", "Tower", "Office", date(2026, 1, 1), date(2031, 1, 1)]])
    _xl4adw_sheet(wb, "MarketLeasing", ["Property_ExternalID", "ExternalID", "Name", "MR_Amount", "MonthsVacant_AEY"],
                  [["A1", "MLA-OFF", "Office", 30, "6;400"]])
    _xl4adw_sheet(wb, "Leases",
                  ["Property_ExternalID", "TenantName", "Suite", "Area", "LeaseBegin", "FixedTerm_PD", "BaseRent_APCL",
                   "LeaseProfile_ExternalID"],
                  [["A1", "Acme", "100", 5000, date(2024, 1, 1), "5Y0M0W0D", 28, "MLA-OFF"]])
    payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(), "x.xlsx").build()
    p = payload.properties[0]
    assert p.market_profiles[0].downtime_schedule == [] and p.market_profiles[0].downtime_months == 6
    assert any("downtime schedule" in w for w in p.warnings)


class TestImportedLoans:
    def test_second_loan_is_an_additional_loan(self):
        wb = Workbook()
        _xl4adw_sheet(wb, "PropertyAssets",
                      ["Property_ExternalID", "Name", "PropertyType_ID", "AnalysisBegin", "AnalysisEndPlusOne"],
                      [["A1", "Office", "Office", date(2026, 1, 1), date(2036, 1, 1)]])
        _xl4adw_sheet(wb, "AreaMeasures", ["Property_ExternalID", "Name", "Area"], [["A1", "Building Area", 50000]])
        _xl4adw_sheet(wb, "DebtFinancing",
                      ["Property_ExternalID", "LoanName", "Amount", "InterestRate", "Amortization", "Term"],
                      [["A1", "Senior", 6000000, 0.06, 360, 120],
                       ["A1", "Mezz", 1000000, 0.10, None, 60],
                       ["A1", "No rate", 50000, None, None, None]])
        payload, _ = ImportMapper(read_workbook(_to_bytes(wb)), ImportOptions(), "x.xlsx").build()
        p = payload.properties[0]
        assert p.valuation.loan_amount == D(6000000)
        assert len(p.valuation.additional_loans) == 1
        mezz = p.valuation.additional_loans[0]
        assert mezz["label"] == "Mezz" and mezz["loan_amount"] == D(1000000) and mezz["interest_rate"] == D("0.10")
        assert mezz["loan_term_months"] == 60
        assert any("no interest rate" in w for w in p.warnings)
