"""Unit tests for portfolio assumption resolution and application."""
from decimal import Decimal

from src.engine.assumption_overrides import (
    OverrideTargets,
    ScopedValues,
    apply_assumptions,
    resolve,
)
from src.engine.types import ExpenseInput, MarketAssumptions, OtherIncomeInput
from tests.unit.test_dcf import make_params

D = Decimal


def _market() -> MarketAssumptions:
    return MarketAssumptions(
        space_type="office", market_rent_per_unit=D("30"), rent_growth_rate=D("0.03"),
        new_lease_term_months=60, new_ti_per_sf=D("40"), new_lc_pct=D("0.06"),
        new_free_rent_months=3, downtime_months=6, renewal_probability=D("0.65"),
        renewal_term_months=60, renewal_ti_per_sf=D("15"), renewal_lc_pct=D("0.03"),
        renewal_free_rent_months=1, renewal_rent_adjustment_pct=D("0"),
        general_vacancy_pct=D("0.05"), credit_loss_pct=D("0.01"),
    )


def _expense(pct_egi=False) -> ExpenseInput:
    return ExpenseInput(
        expense_id="e", category="taxes", base_amount=D("1000"), growth_rate=D("0.03"),
        is_recoverable=True, is_gross_up_eligible=False, gross_up_vacancy_pct=None,
        is_pct_of_egi=pct_egi, pct_of_egi=D("0.03") if pct_egi else None,
    )


LAYERS = [
    ScopedValues({"exit_cap_rate": D("0.07"), "discount_rate": D("0.085")}, source="house"),
    ScopedValues({"exit_cap_rate": D("0.06")}, property_type="industrial", source="industrial"),
    ScopedValues({"exit_cap_rate": D("0.055")}, property_type="industrial", market="Dallas", source="ind-dal"),
    ScopedValues({"market_rent_growth": D("0.04")}, market="dallas", source="dal"),
    ScopedValues({"exit_cap_rate": D("0.065")}, portfolio_id="P1", source="p1-default"),
]


class TestResolve:
    def test_type_and_market_beats_type_and_default(self):
        r = resolve(LAYERS, "P1", "industrial", "Dallas")
        assert r.values["exit_cap_rate"] == D("0.055")
        assert r.sources["exit_cap_rate"] == "ind-dal"
        assert r.values["discount_rate"] == D("0.085")
        assert r.values["market_rent_growth"] == D("0.04")  # market match is case-insensitive

    def test_type_only(self):
        r = resolve(LAYERS, None, "industrial", "Houston")
        assert r.values["exit_cap_rate"] == D("0.06")
        assert "market_rent_growth" not in r.values

    def test_portfolio_default_beats_house_default(self):
        r = resolve(LAYERS, "P1", "office", None)
        assert r.values["exit_cap_rate"] == D("0.065")
        r2 = resolve(LAYERS, "P2", "office", None)
        assert r2.values["exit_cap_rate"] == D("0.07")

    def test_scenario_shift_on_resolved_and_model_values(self):
        base = resolve(LAYERS, None, "office", None)
        scen = [ScopedValues({"exit_cap_rate": D("0.005"), "market_rent_growth": D("-0.01")}, mode="shift", source="down")]
        r = resolve(scen, None, "office", None, base=base)
        assert r.values["exit_cap_rate"] == D("0.075")
        # market_rent_growth has no resolved value -> becomes a pending shift on the model value
        assert r.values["shift:market_rent_growth"] == D("-0.01")


class TestApply:
    def _targets(self):
        return OverrideTargets(
            params=make_params(),
            market={"office": _market()},
            expenses=[_expense(), _expense(pct_egi=True)],
            other_income=[OtherIncomeInput("oi", "parking", D("100"), D("0.02"))],
            cpi_assumption=D("0.025"),
        )

    def test_set_values(self):
        resolved = resolve([ScopedValues({
            "exit_cap_rate": D("0.06"), "downtime_months": D("9"), "expense_growth": D("0.035"),
            "market_rent_change_pct": D("-0.10"), "cpi_rate": D("0.03"), "other_income_growth": D("0.04"),
        })], None, "office", None)
        out = apply_assumptions(self._targets(), resolved)
        assert out.params.exit_cap_rate == D("0.06")
        m = out.market["office"]
        assert m.downtime_months == 9 and isinstance(m.downtime_months, int)
        assert m.market_rent_per_unit == D("27.0")
        assert out.expenses[0].growth_rate == D("0.035")
        assert out.expenses[1].growth_rate == D("0.03")  # % of EGI line untouched
        assert out.other_income[0].growth_rate == D("0.04")
        assert out.cpi_assumption == D("0.03")

    def test_shift_applies_to_model_value(self):
        resolved = resolve(
            [ScopedValues({"market_rent_growth": D("-0.01"), "renewal_probability": D("-0.15")}, mode="shift")],
            None, "office", None,
        )
        out = apply_assumptions(self._targets(), resolved)
        assert out.market["office"].rent_growth_rate == D("0.02")
        assert out.market["office"].renewal_probability == D("0.50")

    def test_overrides_reach_year_by_year_market_schedules(self):
        from dataclasses import replace
        t = self._targets()
        t.market["office"] = replace(
            _market(), general_vacancy_schedule=(D("0.05"), D("0.10")), downtime_schedule=(6, 9),
            renewal_probability_schedule=(D("0.70"), D("0.60")), new_free_rent_schedule=(D("3"), D("2")),
        )
        # A set replaces the schedule (the single value then applies every year)
        out = apply_assumptions(t, resolve([ScopedValues({
            "general_vacancy_pct": D("0.08"), "downtime_months": D("4")})], None, "office", None))
        m = out.market["office"]
        assert m.general_vacancy_pct == D("0.08") and m.general_vacancy_schedule == ()
        assert m.downtime_months == 4 and m.downtime_schedule == ()
        assert m.renewal_probability_schedule == (D("0.70"), D("0.60"))   # untouched
        # A shift moves every year; downtime stays whole months, never below zero
        out = apply_assumptions(t, resolve([ScopedValues({
            "renewal_probability": D("-0.10"), "downtime_months": D("-7"), "new_free_rent_months": D("1"),
        }, mode="shift")], None, "office", None))
        m = out.market["office"]
        assert m.renewal_probability_schedule == (D("0.60"), D("0.50"))
        assert m.downtime_schedule == (0, 2)
        assert m.new_free_rent_schedule == (D("4"), D("3"))

    def test_overrides_reach_leasing_commission_by_lease_year(self):
        from dataclasses import replace
        t = self._targets()
        t.market["office"] = replace(_market(), new_lc_pct_by_lease_year=(D("0.06"), D("0.03")),
                                     renewal_lc_pct_by_lease_year=(D("0.03"), D("0.015")))
        out = apply_assumptions(t, resolve([ScopedValues({"new_lc_pct": D("0.05")})], None, "office", None))
        m = out.market["office"]
        assert m.new_lc_pct == D("0.05") and m.new_lc_pct_by_lease_year == ()
        assert m.renewal_lc_pct_by_lease_year == (D("0.03"), D("0.015"))
        out = apply_assumptions(t, resolve([ScopedValues({"renewal_lc_pct": D("0.01")}, mode="shift")],
                                           None, "office", None))
        assert out.market["office"].renewal_lc_pct_by_lease_year == (D("0.04"), D("0.025"))

    def test_no_values_returns_same_inputs(self):
        t = self._targets()
        out = apply_assumptions(t, resolve([], None, "office", None))
        assert out.params is t.params
        assert out.market["office"] is t.market["office"]


class TestManagementFee:
    def _targets(self, expenses):
        from src.engine.assumption_overrides import OverrideTargets

        return OverrideTargets(params=make_params(), market={}, expenses=expenses, other_income=[],
                               cpi_assumption=D("0.025"), cpi_schedule=())

    def test_sets_an_existing_fee_line(self):
        from dataclasses import replace as dc_replace

        fee = dc_replace(_expense(pct_egi=True), category="management_fee")
        out = apply_assumptions(self._targets([fee]), resolve([ScopedValues({"management_fee_pct": D("0.04")})], None, "office", None))
        assert [e.pct_of_egi for e in out.expenses] == [D("0.04")]

    def test_adds_a_fee_line_when_none_is_modeled(self):
        out = apply_assumptions(self._targets([_expense()]), resolve([ScopedValues({"management_fee_pct": D("0.03")})], None, "office", None))
        added = [e for e in out.expenses if e.category == "management_fee"]
        assert len(added) == 1 and added[0].is_pct_of_egi and added[0].pct_of_egi == D("0.03") and not added[0].is_recoverable
