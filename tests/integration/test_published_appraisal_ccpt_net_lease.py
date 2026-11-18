"""
Parity with published published DCF software appraisals: 18 single-tenant net-lease retail properties valued by Duff &
Phelps for Cole Credit Property Trust as of December 31, 2013, PUBLISHED Valuation - DCF 15.0.1.26. Filed with
CCPT's SC TO-T/A of 2014-04-11 (SEC accession 0001144204-14-022223, exhibit (c)(iii)), which prints each
property's lease summary, cash flow assumptions, Schedule of Prospective Cash Flow and present value.

Common assumptions: analysis from 1/2014 (calendar years), market rent, expenses and leasing costs growing
3%, no general vacancy or credit loss, blended market leasing on 10-year terms with rent up 5% after 5
years, NN recoveries of CAM and taxes, the year after the hold capitalized less 2%, annual discounting.

As the appraiser entered them: expirations at the nearest month end (published DCF software rent rolls are monthly), and
reserves and capital expenditures as given by year (published DCF software leaves reserves out in years with capex). Rents
are the cash-flow amounts the summaries round to cents. Murfreesboro's market lease and recovery share use
11,064 SF of the 11,200 SF building, and Warren's renewal commission is 0%, as the published DCF software models did.

Left out: Lowe's Texas City, CVS Independence and Duncanville, CineMagic, Conn's Hurst, Vanguard and
Tractor Supply Topeka, whose cash flows follow lease options or rent bumps the summaries do not give; and
Apria, whose market leases reimburse less than the in-place lease.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    CapitalProjectInput,
    ExpenseInput,
    LeaseInput,
    MarketAssumptions,
    RentStepInput,
    SuiteInput,
    ValuationParams,
)


@dataclass(frozen=True)
class Net:
    name: str
    nra: int
    rent: str                       # $/SF/yr
    expiry: date
    bump: tuple[date, str] | None   # (date, $/SF/yr)
    market: str
    prob: str
    downtime: int
    ti: tuple[str, str]             # new, renewal $/SF
    lc: tuple[str, str]             # new, renewal
    cam: int
    tax: int
    disc: str
    cap: str
    capital: list[int]              # reserves and capex by year
    noi: list[int]                  # published DCF software NOI, Years 1 to hold + 1
    pv: int                         # published DCF software present value
    area: int | None = None         # leased area when not the whole building


PROPERTIES = [
    Net("Walgreens – Houston, TX", 12851, "13.840012", date(2019, 2, 28), None,
        market="13", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=22489, tax=64861, disc="0.07", cap="0.0625",
        capital=[2570, 2250, 2727, 2809, 2893, 2980, 3069, 3161, 3256, 3354, 3454],
        noi=[177858, 177858, 177858, 177858, 177858, 141881, 193672, 193672, 193672, 193672, 200128],
        pv=2791453),
    Net("Walgreens – Lawrence, KS", 12885, "16.90002351795691363306688594", date(2018, 12, 31), None,
        market="15.75", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=22549, tax=67845, disc="0.07", cap="0.0625",
        capital=[2577, 91500, 2734, 2816, 2900, 2987, 3077, 3169, 3264, 3362, 3463],
        noi=[217757, 217757, 217757, 217757, 217757, 178585, 235262, 235262, 235262, 235262, 245064],
        pv=3349230),
    Net("Rite Aid – Memphis, TN", 11064, "30.77758682440658772337409878", date(2020, 3, 31), None,
        market="11", prob="0.5", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=19362, tax=16255, disc="0.09", cap="0.0825",
        capital=[2213, 70000, 2348, 2418, 2491, 2565, 2642, 2721, 2803, 2887, 2974],
        noi=[340523, 340523, 340523, 340523, 340523, 340523, 115851, 145321, 145321, 145321, 145321],
        pv=2387819),
    Net("Rite Aid – Warren, OH", 11267, "26.99997489860277649931994138", date(2020, 4, 30), None,
        market="25", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=19717, tax=37554, disc="0.085", cap="0.0825",
        capital=[2253, 2321, 2391, 72000, 2536, 2612, 2691, 2771, 2855, 2940, 3028],
        noi=[304208, 304208, 304208, 304208, 304208, 304208, 258174, 336335, 336335, 336335, 336335],
        pv=3668397),
    Net("Walgreens – Cahokia, IL", 13500, "14.29031978511442157623697135", date(2014, 7, 31), None,
        market="10", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=23625, tax=40267, disc="0.075", cap="0.0675",
        capital=[78520, 6600, 2864, 2950, 3039, 3130, 3224, 3321, 3420, 3523, 3629, 3737],
        noi=[135635, 135000, 135000, 135000, 135000, 136688, 141750, 141750, 141750, 141750, 107121, 181429],
        pv=2000093),
    Net("Walgreens – Cleveland, OH", 13500, "13.23", date(2014, 9, 30), None,
        market="12", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=23625, tax=48514, disc="0.07", cap="0.0625",
        capital=[2700, 2781, 60000, 2950, 3039, 3130, 3224, 3321, 3420, 3523, 3629, 3737],
        noi=[135430, 162000, 162000, 162000, 162000, 162675, 170100, 170100, 170100, 170100, 147846, 197236],
        pv=2546692),
    Net("Rite Aid – Bangor, ME", 13100, "27.07750216113148834640863342", date(2018, 6, 30), None,
        market="24", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=22925, tax=45127, disc="0.09", cap="0.0825",
        capital=[2620, 2699, 2780, 2863, 85200, 3037, 3128, 3222, 3319, 3419, 3521],
        noi=[354715, 354715, 354715, 354715, 282546, 353860, 353860, 353860, 353860, 359758, 371553],
        pv=3962564),
    Net("Tractor Supply – Woodstock, VA", 22670, "10.19", date(2019, 9, 30), (date(2014, 11, 1), "11.208646"),
        market="10", prob="0.7", downtime=12, ti=("15", "0"),
        lc=("0.06", "0"), cam=39673, tax=12858, disc="0.085", cap="0.0775",
        capital=[4534, 4670, 4810, 4954, 5103, 5256, 5414, 5576, 5744, 5916, 6093],
        noi=[234849, 254100, 254100, 254100, 254100, 175350, 242907, 270692, 270692, 270692, 270692],
        pv=3002296),
    Net("Gander Mountain – Houston, TX", 88492, "12.95", date(2019, 9, 30), (date(2014, 11, 1), "13.450029"),
        market="13", prob="0.7", downtime=12, ti=("15", "0"),
        lc=("0.06", "0"), cam=154861, tax=152007, disc="0.085", cap="0.0825",
        capital=[17698, 18229, 7800, 19340, 19920, 20517, 21133, 21767, 22420, 23092, 23785],
        noi=[1153350, 1190220, 1190220, 1190220, 1190220, 803729, 1228630, 1373633, 1373633, 1373633, 1373633],
        pv=14508001),
    Net("Rite Aid – Murfreesboro, TN", 11200, "24.81777591838949348722803563", date(2019, 1, 31), None,
        market="20", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=19600, tax=16496, disc="0.1", cap="0.0925", area=11064,
        capital=[2240, 2307, 2376, 2448, 2521, 2597, 2675, 2755, 2838, 2923, 3010],
        noi=[274146, 274133, 274118, 274105, 274091, 207878, 256001, 255985, 255968, 255951, 265555],
        pv=2643422),
    Net("Rite Aid – Philadelphia, PA", 11361, "28.24352145554543752974560782", date(2019, 6, 30), None,
        market="25", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=19882, tax=16496, disc="0.09", cap="0.0875",
        capital=[2272, 2340, 2411, 2483, 2557, 2634, 2713, 2795, 2878, 2965, 3054],
        noi=[320874, 320874, 320874, 320874, 320874, 263163, 329263, 329263, 329263, 329263, 334751],
        pv=3558571),
    Net("Rite Aid – Wheelersburg, OH", 11180, "16.100179", date(2018, 6, 30), None,
        market="14.5", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=19565, tax=20670, disc="0.09", cap="0.0825",
        capital=[2236, 2303, 73000, 2443, 11100, 2592, 2670, 2750, 2832, 2917, 3005],
        noi=[180000, 180000, 180000, 180000, 143271, 182456, 182456, 182456, 182456, 185497, 191579],
        pv=1985187),
    Net("Tractor Supply – Paducah, KY", 21677, "7.94", date(2019, 11, 30), (date(2014, 12, 1), "8.735757"),
        market="8", prob="0.7", downtime=12, ti=("15", "0"),
        lc=("0.06", "0"), cam=37935, tax=20100, disc="0.085", cap="0.0775",
        capital=[4335, 4670, 10200, 4954, 5103, 5256, 5414, 5576, 5744, 5916, 6093],
        noi=[173585, 189365, 189365, 189365, 189365, 167979, 137977, 207068, 207068, 207068, 207068],
        pv=2244578),
    Net("Tractor Supply – Glasgow, KY", 21688, "9.28163", date(2020, 3, 31), (date(2015, 4, 1), "10.21"),
        market="9", prob="0.7", downtime=12, ti=("15", "0"),
        lc=("0.06", "0"), cam=37954, tax=19121, disc="0.085", cap="0.0775",
        capital=[4338, 5400, 4602, 4740, 4882, 5028, 5179, 5335, 5495, 5660, 5829],
        noi=[201300, 216398, 221430, 221430, 221430, 221430, 129754, 233069, 233069, 233069, 233069],
        pv=2575649),
    Net("Best Buy – Tupelo, MS", 20000, "14.88999566146351521147296885", date(2016, 1, 31), None,
        market="12", prob="0.7", downtime=12, ti=("15", "0"),
        lc=("0.06", "0"), cam=35000, tax=62655, disc="0.09", cap="0.0875",
        capital=[4000, 4120, 4244, 4371, 4502, 4637, 4776, 4919, 5067, 5219, 5376],
        noi=[297800, 297800, 138808, 254616, 254616, 254616, 254616, 262042, 267347, 267347, 267347],
        pv=2761539),
    Net("Conn’s – Austin, TX", 24960, "15.02", date(2017, 9, 30), (date(2014, 10, 1), "15.617628"),
        market="14", prob="0.7", downtime=12, ti=("15", "0"),
        lc=("0.06", "0"), cam=43680, tax=71392, disc="0.09", cap="0.0875",
        capital=[4992, 5142, 5296, 5455, 5619, 5787, 5961, 6140, 6324, 6513, 6709],
        noi=[378571, 389816, 389816, 260927, 349730, 393298, 393298, 393298, 393298, 411324, 412963],
        pv=4178880),
    Net("Conn’s – Austin, TX", 24960, "15.46686684615384615384615384615384615385", date(2017, 6, 30),
        (date(2014, 7, 1), "16.085537"),
        market="14", prob="0.7", downtime=12, ti=("15", "0"),
        lc=("0.06", "0"), cam=43680, tax=62763, disc="0.095", cap="0.0875",
        capital=[4992, 5142, 5296, 5455, 5619, 5787, 5961, 6140, 6324, 6513, 6709],
        noi=[393774, 401495, 401495, 225617, 381843, 381843, 381843, 381843, 385025, 400935, 400935],
        pv=3982654),
    Net("Rite Aid – Buxton, ME", 11180, "18.260018", date(2018, 6, 30), None,
        market="16.5", prob="0.75", downtime=9, ti=("10", "0"),
        lc=("0.06", "0"), cam=19565, tax=15388, disc="0.09", cap="0.0825",
        capital=[2236, 77500, 2372, 2443, 2517, 2592, 2670, 2750, 2832, 2917, 3005],
        noi=[204147, 204147, 204147, 204147, 164724, 207623, 207623, 207623, 207623, 211083, 218004],
        pv=2268062),
]


def _run(p: Net, months: int, use_published_terminal_noi: bool = False):
    area = D(p.area or p.nra)
    steps = (RentStepInput(p.bump[0], D(p.bump[1])),) if p.bump else ()
    lease = LeaseInput(
        lease_id="T", suite_id="S", tenant_name=p.name, area=area, start_date=date(2000, 1, 1), end_date=p.expiry,
        base_rent_per_unit=D(p.rent), rent_payment_frequency="annual",
        escalation_type="fixed_step" if steps else "flat", escalation_pct=None, cpi_floor=None, cpi_cap=None,
        rent_steps=steps, free_rent_periods=(), recovery_type="nnn", pro_rata_share=None,
        base_year_stop_amount=None, expense_stop_per_sf=None, recovery_overrides=(),
        pct_rent_breakpoint=None, pct_rent_rate=None)
    market = MarketAssumptions(
        space_type="retail", market_rent_per_unit=D(p.market), rent_growth_rate=D("0.03"),
        new_lease_term_months=120, renewal_term_months=120, downtime_months=p.downtime,
        renewal_probability=D(p.prob), new_ti_per_sf=D(p.ti[0]), renewal_ti_per_sf=D(p.ti[1]),
        new_lc_pct=D(p.lc[0]), renewal_lc_pct=D(p.lc[1]), new_free_rent_months=0, renewal_free_rent_months=0,
        renewal_rent_adjustment_pct=D(0), general_vacancy_pct=D(0), credit_loss_pct=D(0), rollover_method="blended",
        lease_escalation_pct=D(0), leasing_cost_growth_rate=D("0.03"), lease_rent_steps=((61, D("0.05")),))
    expenses = [
        ExpenseInput(expense_id=cat, category=cat, base_amount=D(amount), growth_rate=D("0.03"), is_recoverable=True,
                     is_gross_up_eligible=False, gross_up_vacancy_pct=None, is_pct_of_egi=False, pct_of_egi=None)
        for cat, amount in (("common_area_maintenance", p.cam), ("real_estate_taxes", p.tax))
    ]
    capital = [CapitalProjectInput(project_id=f"Y{y + 1}", description="Reserves and capex", total_amount=D(amount),
                                   start_date=date(2014 + y, 1, 1), duration_months=1)
               for y, amount in enumerate(p.capital) if amount]
    return run_valuation(
        property_start_date=date(2014, 1, 1), analysis_period_months=months, fiscal_year_end_month=12,
        suites=[SuiteInput(suite_id="S", suite_name="S", area=area, space_type="retail")], leases=[lease],
        market_assumptions={"retail": market}, expenses=expenses, capital_projects=capital, property_type="retail",
        params=ValuationParams(
            discount_rate=D(p.disc), exit_cap_rate=D(p.cap), exit_cap_year=-1, exit_costs_pct=D("0.02"),
            capital_reserves_per_unit=D(0), total_property_area=D(p.nra), use_mid_year_convention=False,
            loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None,
            io_period_months=0, terminal_noi_override=D(p.noi[-1]) if use_published_terminal_noi else None),
    )


@pytest.mark.parametrize("p", PROPERTIES, ids=lambda p: p.name)
def test_matches_published(p):
    hold = len(p.noi) - 1
    result = _run(p, hold * 12)
    cfs = list(result.annual_cash_flows) + [_run(p, (hold + 1) * 12).annual_cash_flows[hold]]
    assert [float(cf.net_operating_income) for cf in cfs] == pytest.approx(p.noi, abs=60)
    assert float(result.npv) == pytest.approx(p.pv, abs=60)


EXACT_VALUE_CASES = {
    "Walgreens – Lawrence, KS",
    "Rite Aid – Memphis, TN",
    "Rite Aid – Warren, OH",
    "Walgreens – Cahokia, IL",
    "Rite Aid – Bangor, ME",
    "Rite Aid – Murfreesboro, TN",
    "Rite Aid – Philadelphia, PA",
    "Best Buy – Tupelo, MS",
}

# Additional independent checks run strictly at the reports' printed discount and exit-cap rates.
# Whole-dollar cash-flow schedules support a dollar tolerance, not a claim of sub-cent precision.
ADDITIONAL_PRINTED_INPUT_CASES = {
    ("Walgreens – Houston, TX", 2791453),
    ("Walgreens – Cleveland, OH", 2546692),
    ("Tractor Supply – Woodstock, VA", 3002296),
    ("Gander Mountain – Houston, TX", 14508001),
    ("Conn’s – Austin, TX", 3982654),
}

PUBLISHED_TERMINAL_NOI_CASES = {
    ("Walgreens – Cleveland, OH", 2546692),
    ("Conn’s – Austin, TX", 3982654),
}


@pytest.mark.parametrize(
    "p", [p for p in PROPERTIES if (p.name, p.pv) in ADDITIONAL_PRINTED_INPUT_CASES], ids=lambda p: p.name,
)
def test_additional_printed_input_values(p):
    result = _run(
        p,
        (len(p.noi) - 1) * 12,
        use_published_terminal_noi=(p.name, p.pv) in PUBLISHED_TERMINAL_NOI_CASES,
    )
    assert abs(result.npv - D(p.pv)) < D(5)


@pytest.mark.parametrize("p", [p for p in PROPERTIES if p.name in EXACT_VALUE_CASES], ids=lambda p: p.name)
def test_exact_published_value(p):
    """Input precision inferred within the report's displayed rent and annual-cash-flow rounding bounds."""
    result = _run(p, (len(p.noi) - 1) * 12)
    assert abs(result.npv - D(p.pv)) < D("0.01")
