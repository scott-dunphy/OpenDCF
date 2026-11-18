"""Bottom-up rent-roll reconstruction of The Epic office appraisal (April 2026).

Source pages 64, 79-86 and the lease-summary/input reports in Addendum C:
https://mayafiles.tase.co.il/rpdf/1745001-1746000/P1745280-00.pdf
"""
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseInput, FreeRentPeriodInput, LeaseInput, MarketAssumptions, OtherIncomeInput, RentStepInput, SuiteInput, ValuationParams


AREA = D(282873)
G3 = D("0.03")

# suite, SF, start, end, starting rent, first annual increase, free months, TI, commission, type
LEASES = (
    ("regus", 47999, date(2026, 4, 1), date(2031, 5, 31), "39.03", date(2026, 6, 1), 0, 0, 0, "regus"),
    ("regus-next", 47999, date(2031, 8, 1), date(2036, 7, 31), "42.06", date(2032, 8, 1), 2, 625995, 490641, "regus"),
    ("regus-third", 47999, date(2036, 10, 1), date(2041, 9, 30), "48.76", date(2037, 10, 1), 2, 725700, 568787, "regus"),
    ("westdale", 40162, date(2026, 4, 1), date(2029, 11, 1), "39.41", date(2026, 5, 1), 0, 0, 0, "office"),
    ("westdale-next", 40162, date(2030, 2, 1), date(2040, 1, 31), "39.65", date(2031, 2, 1), 2, 1141039, 870568, "office"),
    ("arm-candy", 8189, date(2026, 4, 1), date(2033, 7, 31), "43.61", date(2027, 1, 1), 0, 0, 0, "office"),
    ("arm-candy-next", 8189, date(2033, 11, 1), date(2043, 10, 31), "44.63", date(2034, 11, 1), 2, 261857, 199787, "office"),
    ("deep-ellum", 5839, date(2026, 4, 1), date(2027, 12, 31), "40", None, 0, 0, 0, "spec_office"),
    ("deep-ellum-next", 5839, date(2028, 3, 1), date(2038, 2, 28), "43.86", date(2029, 3, 1), 2, 67659, 136119, "spec_office"),
    ("soterix", 7629, date(2026, 4, 1), date(2031, 6, 30), "43", date(2027, 7, 1), 3, 76290, 0, "spec_office"),
    ("soterix-next", 7629, date(2031, 9, 1), date(2041, 8, 31), "48.89", date(2032, 9, 1), 2, 99496, 198225, "spec_office"),
    ("four-minds", 5995, date(2026, 4, 1), date(2029, 4, 30), "43", date(2027, 5, 1), 1, 0, 0, "spec_office"),
    ("four-minds-next", 5995, date(2029, 7, 1), date(2039, 6, 30), "46.08", date(2030, 7, 1), 2, 73698, 146827, "spec_office"),
    ("retail-a", 6664, date(2027, 4, 1), date(2037, 3, 31), "48.96", date(2028, 4, 1), 6, 666400, 214631, "retail"),
    ("retail-b", 6664, date(2028, 4, 1), date(2038, 3, 31), "49.94", date(2029, 4, 1), 6, 666400, 218923, "retail"),
    ("retail-c", 6664, date(2029, 4, 1), date(2039, 3, 31), "51.44", date(2030, 4, 1), 6, 666400, 225491, "retail"),
    ("shell-retail", 5069, date(2027, 10, 1), date(2037, 9, 30), "48.96", date(2028, 10, 1), 6, 557590, 163260, "retail"),
    ("eastwind", 2562, date(2026, 10, 1), date(2036, 12, 31), "40", date(2028, 10, 1), 3, 0, 69084, "retail"),
    ("spec-940", 6443, date(2026, 10, 1), date(2036, 9, 30), "43", date(2027, 10, 1), 3, 0, 209709, "spec_office"),
    ("spec-940-third", 6443, date(2036, 12, 1), date(2046, 11, 30), "56.67", date(2037, 12, 1), 2, 97412, 194073, "spec_office"),
    ("spec-1050", 15906, date(2027, 4, 1), date(2037, 3, 31), "43.86", date(2028, 4, 1), 3, 1590600, 528067, "spec_office"),
    ("spec-1000", 10000, date(2027, 4, 1), date(2037, 3, 31), "43.86", date(2028, 4, 1), 3, 1000000, 331993, "spec_office"),
    ("spec-1100", 25906, date(2027, 10, 1), date(2037, 9, 30), "43.86", date(2028, 10, 1), 3, 2590600, 860060, "spec_office"),
    ("spec-1200", 25906, date(2028, 4, 1), date(2038, 3, 31), "44.74", date(2029, 4, 1), 3, 2590600, 877261, "spec_office"),
    ("uber-1300", 25906, date(2028, 4, 1), date(2038, 3, 31), "38.49", date(2029, 4, 1), 6, 1295300, 738024, "office"),
    ("uber-1400", 25906, date(2030, 1, 1), date(2039, 12, 31), "39.65", date(2031, 1, 1), 6, 1295300, 760165, "office"),
    ("second-gen", 3464, date(2029, 4, 1), date(2039, 3, 31), "39.65", date(2030, 4, 1), 6, 173200, 101645, "office"),
)

PUBLISHED = {
    "rent": [4694603, 6431642, 9768287, 10508497, 12449607, 12243533, 13286145, 13500501, 14023099, 14443792, 14050900],
    "recoveries": [2088083, 3047363, 4499676, 4732616, 5460257, 5426827, 5795208, 5921690, 6145906, 6330283, 6278510],
    "noi": [2862200, 5384452, 9781988, 10154543, 11439549, 11395516, 12206497, 12450678, 12885141, 13271695, 13135767],
    "ti": [76290, 6472849, 4552300, 3349636, 0, 725491, 0, 261857, 0, 0, 823112],
    "lc": [278792, 2234129, 1834208, 2104696, 0, 688866, 0, 199787, 0, 0, 762861],
}


SPECIAL_STEPS = {
    "regus": ("40.01", "41.01", "42.04", "43.09", "44.17"),
    "westdale": ("40.20", "41.01", "41.83"),
    "arm-candy": ("44.70", "45.82", "46.97", "48.14", "49.35", "50.58", "51.85"),
}

FREE_RENT_ENDS = {
    "regus-next": date(2031, 9, 15),
    "regus-third": date(2036, 11, 15),
    "westdale-next": date(2030, 3, 18),
    "arm-candy-next": date(2033, 12, 18),
    "deep-ellum-next": date(2028, 4, 15),
    "soterix-next": date(2031, 10, 15),
    "four-minds-next": date(2029, 8, 15),
    "spec-940-third": date(2037, 1, 15),
}


def _rent_steps(sid, rent, first, end):
    if first is None:
        return ()
    out, value, when = [], D(rent), first
    overrides = iter(SPECIAL_STEPS.get(sid, ()))
    while when <= end:
        override = next(overrides, None)
        value = D(override) if override is not None else (value * (1 + G3)).quantize(D("0.01"))
        out.append(RentStepInput(when, value))
        when = date(when.year + 1, when.month, when.day)
    return tuple(out)


def _suite_id(sid):
    return sid.replace("-next", "").replace("-third", "")


def _leases():
    out = []
    for sid, area, start, end, rent, first, free, ti, lc, _ in LEASES:
        periods = ()
        if free:
            free_end = FREE_RENT_ENDS.get(sid, date(start.year + (start.month - 1 + free - 1) // 12,
                (start.month - 1 + free - 1) % 12 + 1, 28))
            periods = (FreeRentPeriodInput(start, free_end, True, False),)
        out.append(LeaseInput(
            lease_id=sid, suite_id=_suite_id(sid), tenant_name=sid, area=D(area), start_date=start,
            end_date=end, base_rent_per_unit=D(rent), rent_payment_frequency="annual", escalation_type="fixed_step",
            escalation_pct=None, cpi_floor=None, cpi_cap=None, rent_steps=_rent_steps(sid, rent, first, end),
            free_rent_periods=periods, recovery_type="nnn", pro_rata_share=None, base_year_stop_amount=None,
            expense_stop_per_sf=None, recovery_overrides=(), pct_rent_breakpoint=None, pct_rent_rate=None,
            committed_ti_amount=D(ti), committed_lc_amount=D(lc), upon_expiration="market",
        ))
    return out


def _market(name):
    market_rent = {"office": 37, "spec_office": 43, "retail": 48, "regus": 37}[name]
    return MarketAssumptions(
        space_type=name, market_rent_per_unit=D(market_rent), rent_growth_rate=G3, new_lease_term_months=120,
        rent_growth_schedule=(D("0.02"), D("0.02"), G3),
        renewal_term_months=120, downtime_months=9, renewal_probability=D("0.70"), new_ti_per_sf=D(40),
        renewal_ti_per_sf=D(20), new_lc_pct=D("0.06"), renewal_lc_pct=D("0.04"), new_free_rent_months=3,
        renewal_free_rent_months=0, renewal_rent_adjustment_pct=D(0), general_vacancy_pct=D("0.10"),
        credit_loss_pct=D(0), rollover_method="blended", lease_escalation_pct=G3, leasing_cost_growth_rate=G3,
    )


def _run(months=120):
    areas = {}
    types = {}
    for sid, area, *_, kind in LEASES:
        key = _suite_id(sid)
        areas[key], types[key] = area, kind
    schedules = {
        "real_estate_taxes": [2135506,2199571,2265558,2333525,2403531,2475637,2549906,2626403,2705195,2786351,2869941],
        "margin_tax": [24933,34023,49548,51306,56202,56562,59865,61243,63289,65188,65315],
        "utilities": [124464,128198,132044,136005,140085,144288,148617,153075,157667,162397,167269],
        "insurance": [187977,193616,199425,205408,211570,217917,224454,231188,238124,245267,252625],
        "cam": [1654807,1704451,1755585,1808252,1862500,1918375,1975926,2035204,2096260,2159148,2223922],
        "administrative": [246100,253482,261087,268920,276987,285297,293856,302671,311751,321104,330737],
        "landlord": [70718,72840,75025,77276,79594,81982,84441,86975,89584,92271,95039],
    }
    expenses = [ExpenseInput(
        k, k, D(v[0]), G3, k != "landlord", False, None, False, None,
        amount_schedule=tuple(map(D, v)),
    ) for k, v in schedules.items()]
    expenses.append(ExpenseInput(
        "management_fee", "management_fee", D(0), D(0), True, True, D("0.95"), True, D("0.03")
    ))
    return run_valuation(
        property_start_date=date(2026, 4, 1), analysis_period_months=months, fiscal_year_end_month=3,
        suites=[SuiteInput(
            k, k, D(v), types[k],
            absorption_start_date=date(2026, 4, 1) if min(x[2] for x in LEASES if _suite_id(x[0]) == k) > date(2026, 4, 1) else None,
            lease_up_months=min((x[2].year - 2026) * 12 + x[2].month - 4 for x in LEASES if _suite_id(x[0]) == k) if min(x[2] for x in LEASES if _suite_id(x[0]) == k) > date(2026, 4, 1) else None,
        ) for k, v in areas.items()], leases=_leases(),
        market_assumptions={k: _market(k) for k in set(types.values())}, expenses=expenses, property_type="office",
        other_income_items=[
            OtherIncomeInput("other", "other", D(175000), D(0), amount_schedule=tuple(map(D, [175000,200000,231750,238703,245864,253239,260837,268662,276722,285023,293574]))),
            OtherIncomeInput("parking", "parking", D(575000), D(0), amount_schedule=tuple(map(D, [575000,600000,669500,689585,710273,731581,753528,776134,799418,823401,848103]))),
        ],
        params=ValuationParams(D("0.10"), D("0.075"), -1, D("0.015"), D("0.20"), AREA, False, None, None, None, None, 0,
            vacancy_calculation_frequency="monthly", reduce_general_vacancy_by_downtime=True,
            vacancy_on_gross_revenue=True),
    )


@pytest.fixture(scope="module")
def result():
    r = _run()
    return r, list(r.annual_cash_flows) + [_run(132).annual_cash_flows[10]]


def test_area_reconciles():
    assert sum({_suite_id(sid): area for sid, area, *_ in LEASES}.values()) == AREA


@pytest.mark.parametrize("line,tolerance", [("rent", 1000), ("recoveries", 10000), ("noi", 20000)])
@pytest.mark.xfail(reason="Bottom-up reconciliation remains in progress; do not count as validated")
def test_annual_cash_flow(result, line, tolerance):
    _, cfs = result
    actual = {
        "rent": [x.gross_potential_rent + x.free_rent for x in cfs],
        "recoveries": [x.expense_recoveries for x in cfs],
        "noi": [x.net_operating_income for x in cfs],
        "ti": [-x.tenant_improvements for x in cfs],
        "lc": [-x.leasing_commissions for x in cfs],
    }[line]
    assert [float(x) for x in actual] == pytest.approx(PUBLISHED[line], abs=tolerance)


@pytest.mark.parametrize("line", ["ti", "lc"])
def test_annual_leasing_costs(result, line):
    _, cfs = result
    actual = {
        "ti": [-x.tenant_improvements for x in cfs],
        "lc": [-x.leasing_commissions for x in cfs],
    }[line]
    assert [float(x) for x in actual] == pytest.approx(PUBLISHED[line], abs=5)


@pytest.mark.xfail(reason="Bottom-up reconciliation remains in progress; do not count as validated")
def test_value(result):
    assert float(result[0].npv) == pytest.approx(106593160, abs=50000)
