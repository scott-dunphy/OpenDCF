"""Year-by-year growth tables for market rent, expenses, other income and CPI."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.assumption_overrides import OverrideTargets, ResolvedAssumptions, apply_assumptions
from src.engine.growth import expense_at_year, growth_factor_to_year, market_rent_at_year, rate_for_year
from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseInput, LeaseInput, OtherIncomeInput, SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params

D = Decimal


class TestGrowthHelpers:
    def test_rate_for_year_carries_last_forward(self):
        sched = (D("0.01"), D("0.02"), D("0.04"))
        assert rate_for_year(D("0.03"), sched, 1) == D("0.01")
        assert rate_for_year(D("0.03"), sched, 3) == D("0.04")
        assert rate_for_year(D("0.03"), sched, 9) == D("0.04")
        assert rate_for_year(D("0.03"), (), 9) == D("0.03")

    def test_one_entry_schedule_matches_single_rate(self):
        for year in range(1, 8):
            assert growth_factor_to_year(D("0.03"), year, (D("0.03"),)) == growth_factor_to_year(D("0.03"), year)

    def test_year_n_compounds_rates_for_years_2_to_n(self):
        sched = (D("0.10"), D("0.00"), D("0.05"))
        # Year 1 rate does not apply (base is stated at Year 1)
        assert market_rent_at_year(D("100"), D("0.03"), 1, sched) == D("100")
        assert market_rent_at_year(D("100"), D("0.03"), 2, sched) == D("100")
        assert market_rent_at_year(D("100"), D("0.03"), 3, sched) == D("105.00")
        assert market_rent_at_year(D("100"), D("0.03"), 4, sched) == D("110.2500")
        assert expense_at_year(D("100"), D("0.03"), 4, sched) == D("110.2500")


def _flat_lease(**overrides) -> LeaseInput:
    base = dict(
        lease_id="L1", suite_id="S1", tenant_name="T", area=D("10000"),
        start_date=date(2025, 1, 1), end_date=date(2034, 12, 31),
        base_rent_per_unit=D("30"), rent_payment_frequency="annual",
        escalation_type="flat", escalation_pct=None, cpi_floor=None, cpi_cap=None,
        rent_steps=(), free_rent_periods=(), recovery_type="full_service_gross",
        pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None,
        recovery_overrides=(), pct_rent_breakpoint=None, pct_rent_rate=None,
    )
    base.update(overrides)
    return LeaseInput(**base)


def _expense(**overrides) -> ExpenseInput:
    base = dict(
        expense_id="E1", category="real_estate_taxes", base_amount=D("100000"), growth_rate=D("0.03"),
        is_recoverable=False, is_gross_up_eligible=False, gross_up_vacancy_pct=None,
        is_pct_of_egi=False, pct_of_egi=None,
    )
    base.update(overrides)
    return ExpenseInput(**base)


def _run(lease, expenses=(), other_income=(), market=None, **kw):
    suite = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")
    return run_valuation(
        property_start_date=date(2025, 1, 1),
        analysis_period_months=60,
        fiscal_year_end_month=12,
        suites=[suite],
        leases=[lease],
        market_assumptions={"office": market or _make_market()},
        expenses=list(expenses),
        params=_make_params(),
        other_income_items=list(other_income),
        **kw,
    )


class TestEngineSchedules:
    def test_expense_schedule_drives_opex(self):
        sched = (D("0"), D("0.10"), D("0.00"))
        r = _run(_flat_lease(), expenses=[_expense(growth_schedule=sched)])
        opex = [-cf.operating_expenses for cf in r.annual_cash_flows]
        assert opex[0] == D("100000")
        assert opex[1] == D("110000")
        assert opex[2] == D("110000")
        assert opex[4] == D("110000")

    def test_other_income_schedule(self):
        oi = OtherIncomeInput(income_id="O1", category="parking", base_amount=D("1000"), growth_rate=D("0.03"),
                              growth_schedule=(D("0"), D("0.5")))
        r = _run(_flat_lease(), other_income=[oi])
        assert [cf.other_income for cf in r.annual_cash_flows[:3]] == [D("1000"), D("1500.0"), D("2250.00")]

    def test_explicit_amount_schedules_allow_zero_first_year(self):
        oi = OtherIncomeInput("O1", "vacancy_adjustment", D(0), D(0),
                              amount_schedule=(D(0), D("-25000"), D("-30000")))
        expense = _expense(base_amount=D(0), amount_schedule=(D(0), D("10000"), D("12000")))
        r = _run(_flat_lease(), expenses=[expense], other_income=[oi])
        assert [cf.other_income for cf in r.annual_cash_flows[:4]] == [D(0), D("-25000"), D("-30000"), D("-30000")]
        # Past the schedule the last amount grows at the line's growth rate (3% here; other income has 0%)
        assert [-cf.operating_expenses for cf in r.annual_cash_flows[:4]] == [D(0), D("10000"), D("12000"), D("12360")]

    def test_amount_schedule_tail_grows_at_the_growth_schedule(self):
        from src.engine.growth import scheduled_amount_at_year
        sched = (D("100"), D("110"))
        assert scheduled_amount_at_year(D(0), D("0.03"), 2, (), sched) == D("110")
        assert scheduled_amount_at_year(D(0), D("0.03"), 4, (), sched) == D("110") * D("1.03") ** 2
        # A growth schedule applies year by year past the amounts: Year 3 at 10%, Year 4 at 5% (carried)
        growth = (D("0"), D("0"), D("0.10"), D("0.05"))
        assert scheduled_amount_at_year(D(0), D("0.03"), 4, growth, sched) == D("110") * D("1.10") * D("1.05")

    def test_market_rent_schedule_sets_loss_to_lease(self):
        flat = _run(_flat_lease())
        bumped = _run(_flat_lease(), market=replace(_make_market(), rent_growth_schedule=(D("0"), D("0.20"))))
        # Year 2 market rent 35 * 1.2 = 42 vs contract 30 -> larger loss to lease than at 3%
        assert bumped.annual_cash_flows[1].loss_to_lease < flat.annual_cash_flows[1].loss_to_lease

    def test_cpi_schedule_by_analysis_year(self):
        lease = _flat_lease(escalation_type="cpi")
        r = _run(lease, cpi_assumption=D("0.025"), cpi_schedule=(D("0.10"), D("0.02"), D("0.05")))
        gpr = [cf.gross_potential_rent for cf in r.annual_cash_flows]
        # Anniversary 2026-01-01 falls in analysis Year 2 (2%), 2027-01-01 in Year 3 (5%)
        assert gpr[0] == D("300000")
        assert abs(gpr[1] - D("306000")) < D("0.01")
        assert abs(gpr[2] - D("321300")) < D("0.01")

    def test_no_schedule_unchanged(self):
        lease = _flat_lease(escalation_type="cpi")
        a = _run(lease, cpi_assumption=D("0.025"))
        b = _run(lease, cpi_assumption=D("0.025"), cpi_schedule=(D("0.025"),))
        assert a.npv == b.npv


class TestOverridesOnSchedules:
    def _targets(self):
        return OverrideTargets(
            params=_make_params(),
            market={"office": replace(_make_market(), rent_growth_schedule=(D("0.01"), D("0.02")))},
            expenses=[_expense(growth_schedule=(D("0.01"), D("0.02")))],
            other_income=[],
            cpi_assumption=D("0.025"),
            cpi_schedule=(D("0.03"),),
        )

    def test_shift_moves_every_year(self):
        resolved = ResolvedAssumptions(values={"shift:expense_growth": D("0.01"), "shift:market_rent_growth": D("0.01")})
        out = apply_assumptions(self._targets(), resolved)
        assert out.expenses[0].growth_schedule == (D("0.02"), D("0.03"))
        assert out.market["office"].rent_growth_schedule == (D("0.02"), D("0.03"))

    def test_set_replaces_table(self):
        resolved = ResolvedAssumptions(values={"expense_growth": D("0.04"), "cpi_rate": D("0.02")})
        out = apply_assumptions(self._targets(), resolved)
        assert out.expenses[0].growth_schedule == ()
        assert out.expenses[0].growth_rate == D("0.04")
        assert out.cpi_schedule == ()
        assert out.cpi_assumption == D("0.02")


def test_loss_to_lease_prorates_partial_months():
    # Contract rent equals market rent; the lease ends mid-June, so June is half a month of each
    market = replace(_make_market(), market_rent_per_unit=D("30"), rent_growth_rate=D("0"))
    r = _run(_flat_lease(end_date=date(2025, 6, 15)), market=market)
    assert r.annual_cash_flows[0].loss_to_lease == 0
