"""Self storage engine: hand-checked revenue build and DCF (docs/self-storage-plan.md)."""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.self_storage import run_self_storage
from src.engine.types import CapitalProjectInput, ExpenseInput, ValuationParams
from src.schemas.self_storage import SelfStorageOperatingModel

D = Decimal
CENT = D("0.01")


def _params(**kw) -> ValuationParams:
    base = dict(
        discount_rate=D("0.09"), exit_cap_rate=D("0.08"), exit_cap_year=-1, exit_costs_pct=D("0.02"),
        capital_reserves_per_unit=D("0.20"), total_property_area=D("10000"), use_mid_year_convention=False,
        loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None, io_period_months=0,
    )
    base.update(kw)
    return ValuationParams(**base)


def _expense(category, amount=D(0), pct_of_egi=None, variable_pct=D(0)) -> ExpenseInput:
    return ExpenseInput(
        expense_id=category, category=category, base_amount=amount, growth_rate=D(0), is_recoverable=False,
        is_gross_up_eligible=False, gross_up_vacancy_pct=None, is_pct_of_egi=pct_of_egi is not None,
        pct_of_egi=pct_of_egi, variable_pct=variable_pct,
    )


def _model(**kw) -> SelfStorageOperatingModel:
    data = {
        "unit_types": [{"name": "10x10", "sf_per_unit": 100, "count": 100, "occupied_units": 90,
                        "in_place_rate": 100, "street_rate": 100}],
        "credit_loss_pct": "0.01",
        "ancillary_lines": [{"name": "Tenant protection", "basis": "per_occupied_unit_month", "amount": 12,
                             "participation_pct": "0.6"}],
    }
    data.update(kw)
    return SelfStorageOperatingModel.model_validate(data)


def _run(model, months=12, expenses=None, params=None, **kw):
    expenses = expenses if expenses is not None else [
        _expense("fixed", D(30000)), _expense("management_fee", pct_of_egi=D("0.06")),
    ]
    return run_self_storage(model, date(2026, 1, 1), months, 12, expenses, params or _params(), **kw)


def test_hand_check_a_static_facility():
    result = _run(_model())
    y1 = result.annual_cash_flows[0]
    assert y1.gross_potential_rent == D(108000)
    assert y1.credit_loss == D(-1080)
    assert y1.other_income == D(7776)
    assert y1.effective_gross_income == D(114696)
    assert y1.expense_detail["management_fee"].quantize(CENT) == D("-6881.76")
    assert y1.net_operating_income.quantize(CENT) == D("77814.24")
    assert y1.cash_flow_before_debt.quantize(CENT) == D("75814.24")
    assert result.terminal_gross_value.quantize(CENT) == D("972678.00")
    assert result.terminal_value.quantize(CENT) == D("953224.44")
    assert result.npv.quantize(CENT) == D("944072.18")
    assert result.avg_occupancy_pct == D("0.9")
    # Street x all units reconciles through vacancy and loss to lease
    assert y1.gross_potential_rent - y1.absorption_vacancy - y1.loss_to_lease == D(120000)


def _model_b(**kw) -> SelfStorageOperatingModel:
    data = {
        "unit_types": [{"name": "10x10", "sf_per_unit": 100, "count": 150, "occupied_units": 120,
                        "in_place_rate": 100, "street_rate": 90, "stabilized_occupancy": "0.8"}],
        "churn": {"monthly_move_out_pct": "0.05"},
        "ecri": {"enabled": True, "first_after_months": 12, "interval_months": 12, "increase_pct": "0.10",
                 "extra_move_out_pct": "0.10"},
        "concessions": {"first_month_discount_pct": "0.5"},
    }
    data.update(kw)
    return SelfStorageOperatingModel.model_validate(data)


def test_hand_check_b_first_month():
    month = _run(_model_b(), expenses=[], include_monthly=True).monthly_cash_flows[0]
    rental = month.gross_potential_rent + month.free_rent
    assert rental.quantize(CENT) == D("11703.25")
    assert month.free_rent.quantize(CENT) == D("-312.75")
    assert month.absorption_vacancy.quantize(CENT) == D("-2700.00")
    assert month.loss_to_lease.quantize(CENT) == D("1216.00")
    # GPR at street (13,500) - vacancy + loss to lease + concession = rental
    street_all = month.gross_potential_rent - month.absorption_vacancy - month.loss_to_lease
    assert street_all.quantize(CENT) == D("13500.00")


def test_move_ins_age_into_their_first_increase():
    """No churn: each month one opening bucket (10 units, $1,000) gets its increase and loses a unit,
    which is refilled at the $90 street rate. Month 12 holds 12 raised buckets (9 units, $990) and
    12 one-unit move-ins ($90): $12,960. In month 13 the month-1 move-in reaches its first increase
    in the same bucket as the first opening bucket's second: (990 + 90) x 1.10 x 0.90 = $1,069.20,
    one unit leaves and is refilled at $90, so rent = 12,960 - 1,080 + 1,069.20 + 90 = $13,039.20."""
    model = _model_b(churn={"monthly_move_out_pct": "0"}, concessions={"first_month_discount_pct": "0"})
    rows = _run(model, months=24, expenses=[], include_monthly=True).monthly_cash_flows
    assert rows[0].gross_potential_rent.quantize(CENT) == D("12080.00")
    assert rows[11].gross_potential_rent.quantize(CENT) == D("12960.00")
    assert rows[12].gross_potential_rent.quantize(CENT) == D("13039.20")


def test_lease_up_converges_under_the_absorption_cap():
    model = _model(
        unit_types=[{"name": "10x10", "sf_per_unit": 100, "count": 100, "occupied_units": 20,
                     "in_place_rate": 100, "street_rate": 100, "stabilized_occupancy": "0.9"}],
        lease_up={"monthly_net_absorption_units": 5},
    )
    rows = _run(model, months=24, include_monthly=True).monthly_cash_flows
    occupied = [(r.gross_potential_rent / 100) for r in rows]
    assert occupied[0] == D(25)
    assert occupied[13] == D(90)  # 20 + 5 x 14 = 90, reached in month 14
    assert occupied[-1] == D(90)
    assert all(b - a <= 5 for a, b in zip(occupied, occupied[1:]))


def test_ecri_raises_rent_and_adds_move_outs():
    base = _model_b(ecri={"enabled": False})
    with_ecri = _model_b()
    plain = _run(base, months=24, expenses=[]).storage_detail
    ecri = _run(with_ecri, months=24, expenses=[]).storage_detail
    assert ecri[1]["in_place_rent_per_occupied_sf"] > plain[1]["in_place_rent_per_occupied_sf"]
    assert ecri[0]["ecri_move_outs"] > 0 and plain[0]["ecri_move_outs"] == 0
    assert ecri[0]["move_outs"] > plain[0]["move_outs"]


def test_forward_noi_is_the_year_after_the_hold():
    model = _model(street_rate_growth_pct="0.04", churn={"monthly_move_out_pct": "0.03"})
    two_years = _run(model, months=24)
    three_years = _run(model, months=36)
    assert two_years.terminal_noi_basis == three_years.annual_cash_flows[2].net_operating_income


@pytest.mark.parametrize("basis, amount, expected", [
    ("annual_fixed", 1200, D(1200)),
    ("per_occupied_unit_month", 2, D(2160)),        # 90 units x 12 months
    ("per_move_in", 10, D(0)),                       # static: no move-ins
    ("pct_of_rental", "0.05", D(5400)),              # 5% of 108,000
])
def test_each_ancillary_basis(basis, amount, expected):
    model = _model(ancillary_lines=[{"name": "Line", "basis": basis, "amount": amount}])
    y1 = _run(model).annual_cash_flows[0]
    assert y1.other_income_detail["Line"] == expected


def test_per_move_in_income_counts_move_ins():
    model = _model_b(ancillary_lines=[{"name": "Admin fee", "basis": "per_move_in", "amount": 25}])
    month = _run(model, expenses=[], include_monthly=True).monthly_cash_flows[0]
    assert month.other_income_detail["Admin fee"].quantize(CENT) == D("173.75")  # 6.95 x 25


def test_variable_expense_scales_with_occupancy():
    full = _model(unit_types=[{"name": "A", "sf_per_unit": 100, "count": 100, "occupied_units": 100,
                               "in_place_rate": 100, "street_rate": 100}])
    half = _model(unit_types=[{"name": "A", "sf_per_unit": 100, "count": 100, "occupied_units": 50,
                               "in_place_rate": 100, "street_rate": 100}])
    utilities = [_expense("utilities", D(10000), variable_pct=D("0.5"))]
    assert _run(full, expenses=utilities).annual_cash_flows[0].operating_expenses.quantize(CENT) == D(-10000)
    assert _run(half, expenses=utilities).annual_cash_flows[0].operating_expenses.quantize(CENT) == D(-7500)


def test_every_pct_of_egi_line_is_charged():
    lines = [_expense("management_fee", pct_of_egi=D("0.06")), _expense("card_fees", pct_of_egi=D("0.02"))]
    y1 = _run(_model(), expenses=lines).annual_cash_flows[0]
    assert y1.expense_detail["card_fees"].quantize(CENT) == D("-2293.92")
    assert y1.expense_detail["management_fee"].quantize(CENT) == D("-6881.76")


def test_monthly_discounting_values_the_same_cash_flows_differently():
    annual = _run(_model(), months=24)
    monthly = _run(_model(), months=24, params=_params(discounting_convention="monthly"))
    assert monthly.annual_cash_flows[0].net_operating_income == annual.annual_cash_flows[0].net_operating_income
    assert monthly.npv > annual.npv  # cash arrives through the year, not at year end
    assert len(monthly.monthly_cash_flows) == 24


def test_capital_projects_and_debt_flow_through():
    params = _params(loan_amount=D(500000), interest_rate=D("0.06"), amortization_months=360,
                     loan_term_months=120, purchase_price=D(900000))
    project = CapitalProjectInput(project_id="roof", description="Roof", total_amount=D(12000),
                                  start_date=date(2026, 3, 1), duration_months=6)
    result = _run(_model(), months=24, params=params, capital_projects=[project])
    y1 = result.annual_cash_flows[0]
    assert y1.building_improvements == D(-12000)
    assert y1.debt_service < 0
    assert result.returns is not None and result.returns.levered_irr is not None
    assert result.irr is not None


def test_model_validation():
    with pytest.raises(ValueError, match="exceed the unit count"):
        _model(unit_types=[{"name": "A", "sf_per_unit": 100, "count": 10, "occupied_units": 11,
                            "in_place_rate": 1, "street_rate": 1}])
    with pytest.raises(ValueError, match="unique"):
        _model(unit_types=[{"name": "A", "sf_per_unit": 1, "count": 1, "occupied_units": 0, "in_place_rate": 1,
                            "street_rate": 1}] * 2)
    with pytest.raises(ValueError, match="fraction"):
        _model(ancillary_lines=[{"name": "x", "basis": "pct_of_rental", "amount": 5}])
