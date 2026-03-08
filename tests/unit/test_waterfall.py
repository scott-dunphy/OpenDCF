"""Unit tests for the cash flow waterfall aggregation."""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period, end_of_month
from src.engine.types import (
    AnalysisPeriod,
    ExpenseInput,
    MarketAssumptions,
    MonthlySlice,
    OtherIncomeInput,
    SuiteInput,
    ValuationParams,
)
from src.engine.waterfall import build_annual_waterfall


def make_params(
    discount_rate: float = 0.08,
    exit_cap_rate: float = 0.065,
    cap_reserves: float = 0.0,
    total_area: float = 10_000,
    apply_stabilized_gross_up: bool = True,
    stabilized_occupancy_pct: float | None = None,
) -> ValuationParams:
    return ValuationParams(
        discount_rate=Decimal(str(discount_rate)),
        exit_cap_rate=Decimal(str(exit_cap_rate)),
        exit_cap_year=-1,
        exit_costs_pct=Decimal("0.02"),
        capital_reserves_per_unit=Decimal(str(cap_reserves)),
        total_property_area=Decimal(str(total_area)),
        use_mid_year_convention=False,
        loan_amount=None,
        interest_rate=None,
        amortization_months=None,
        loan_term_months=None,
        io_period_months=0,
        apply_stabilized_gross_up=apply_stabilized_gross_up,
        stabilized_occupancy_pct=(
            Decimal(str(stabilized_occupancy_pct))
            if stabilized_occupancy_pct is not None else None
        ),
    )


def make_suite(suite_id: str = "s1", area: float = 10_000, space_type: str = "office") -> SuiteInput:
    return SuiteInput(
        suite_id=suite_id,
        suite_name=f"Suite {suite_id}",
        area=Decimal(str(area)),
        space_type=space_type,
    )


def make_market(gen_vac: float = 0.0, credit_loss: float = 0.0) -> MarketAssumptions:
    return MarketAssumptions(
        space_type="office",
        market_rent_per_unit=Decimal("35"),
        rent_growth_rate=Decimal("0.03"),
        new_lease_term_months=60,
        new_ti_per_sf=Decimal("50"),
        new_lc_pct=Decimal("0.06"),
        new_free_rent_months=3,
        downtime_months=6,
        renewal_probability=Decimal("0.65"),
        renewal_term_months=60,
        renewal_ti_per_sf=Decimal("20"),
        renewal_lc_pct=Decimal("0.03"),
        renewal_free_rent_months=1,
        renewal_rent_adjustment_pct=Decimal("0"),
        general_vacancy_pct=Decimal(str(gen_vac)),
        credit_loss_pct=Decimal(str(credit_loss)),
    )


def make_expense(
    category: str = "real_estate_taxes",
    base_amount: float = 0.0,
    growth_rate: float = 0.0,
    is_recoverable: bool = True,
    is_gross_up_eligible: bool = False,
    gross_up_vacancy_pct: float | None = None,
    is_pct_egi: bool = False,
    pct_egi: float | None = None,
) -> ExpenseInput:
    return ExpenseInput(
        expense_id=f"exp_{category}",
        category=category,
        base_amount=Decimal(str(base_amount)),
        growth_rate=Decimal(str(growth_rate)),
        is_recoverable=is_recoverable,
        is_gross_up_eligible=is_gross_up_eligible,
        gross_up_vacancy_pct=(
            Decimal(str(gross_up_vacancy_pct))
            if gross_up_vacancy_pct is not None else None
        ),
        is_pct_of_egi=is_pct_egi,
        pct_of_egi=Decimal(str(pct_egi)) if pct_egi is not None else None,
    )


def make_slice(
    suite_id: str,
    month_index: int,
    effective_rent: float,
    expense_recovery: float = 0.0,
    scenario_weight: float = 1.0,
    is_vacant: bool = False,
    ti_cost: float = 0.0,
    lc_cost: float = 0.0,
) -> MonthlySlice:
    year = 2025 + (month_index // 12)
    month = (month_index % 12) + 1
    period_start = date(year, month, 1)
    return MonthlySlice(
        month_index=month_index,
        period_start=period_start,
        period_end=end_of_month(period_start),
        suite_id=suite_id,
        lease_id=f"l_{suite_id}",
        tenant_name="Tenant A",
        base_rent=Decimal(str(effective_rent)),
        free_rent_adjustment=Decimal(0),
        effective_rent=Decimal(str(effective_rent)),
        expense_recovery=Decimal(str(expense_recovery)),
        percentage_rent=Decimal(0),
        ti_cost=Decimal(str(ti_cost)),
        lc_cost=Decimal(str(lc_cost)),
        is_vacant=is_vacant,
        scenario_label="in_place",
        scenario_weight=Decimal(str(scenario_weight)),
    )


def make_year1_slices(
    suite_id: str,
    monthly_rent: float,
    monthly_recovery: float = 0.0,
) -> list[MonthlySlice]:
    """12 full-year slices for Jan-Dec 2025."""
    return [
        make_slice(suite_id, i, monthly_rent, monthly_recovery)
        for i in range(12)
    ]


class TestGPRAggregation:
    def test_single_suite_gpr(self):
        """GPR = sum of effective_rent * scenario_weight across all slices."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        monthly_rent = 10_000 / 12  # $10K/year
        slices = make_year1_slices("s1", monthly_rent)

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)],
        )

        assert len(annual_cfs) == 1
        cf = annual_cfs[0]
        assert abs(cf.gross_potential_rent - Decimal("10000")) < Decimal("1")

    def test_two_suite_gpr_sums(self):
        """GPR = rent from suite A + rent from suite B."""
        s1 = make_suite("s1", area=5_000)
        s2 = make_suite("s2", area=5_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)

        slices_s1 = make_year1_slices("s1", 5_000 / 12)   # $5K/yr each
        slices_s2 = make_year1_slices("s2", 5_000 / 12)

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices_s1, "s2": slices_s2},
            suites=[s1, s2],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        assert abs(cf.gross_potential_rent - Decimal("10000")) < Decimal("1")

    def test_probability_weighted_rent(self):
        """Weighted slices: GPR = effective_rent * weight."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        # Renewal at 70% weight, new tenant at 30% weight, same rent
        renewal_rent = 1000.0
        new_rent = 1000.0
        slices = []
        for i in range(12):
            slices.append(make_slice("s1", i, renewal_rent, scenario_weight=0.70))
            slices.append(make_slice("s1", i, new_rent, scenario_weight=0.30))

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        # 12 months * $1000/mo * (0.70 + 0.30) = $12,000
        assert abs(cf.gross_potential_rent - Decimal("12000")) < Decimal("1")


class TestGeneralVacancy:
    def test_general_vacancy_applied_to_gpr_only(self):
        """General vacancy deducted from GPR, NOT from expense recoveries."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)

        monthly_rent = 10_000 / 12        # $10K/yr GPR
        monthly_recovery = 1_000 / 12    # $1K/yr recoveries

        slices = make_year1_slices("s1", monthly_rent, monthly_recovery)

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market(gen_vac=0.05)},
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        gpr = cf.gross_potential_rent
        recoveries = cf.expense_recoveries
        gpi = cf.gross_potential_income
        gen_vac = cf.general_vacancy_loss

        # GPI = GPR + recoveries
        assert abs(gpi - (gpr + recoveries)) < Decimal("1")

        # Gen vac = -5% of GPR (not of GPI or EGI)
        expected_vac = -(gpr * Decimal("0.05"))
        assert abs(gen_vac - expected_vac) < Decimal("1")

        # EGI = GPI + gen_vac (recoveries not reduced by vacancy)
        assert abs(cf.effective_gross_income - (gpi + gen_vac + cf.credit_loss)) < Decimal("1")

    def test_credit_loss_on_gpr_only(self):
        """Credit loss = -credit_loss_rate * GPR (same as general vacancy)."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        slices = make_year1_slices("s1", 10_000 / 12, monthly_recovery=500 / 12)

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market(gen_vac=0.0, credit_loss=0.01)},
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        expected_credit_loss = -(cf.gross_potential_rent * Decimal("0.01"))
        assert abs(cf.credit_loss - expected_credit_loss) < Decimal("1")


class TestMgmtFeeCircularity:
    def test_mgmt_fee_algebraic_formula(self):
        """Management fee = EGI * pct / (1 + pct) — solves circular dependency."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        annual_gpr = Decimal("100000")
        slices = make_year1_slices("s1", float(annual_gpr / 12))

        mgmt_fee_expense = make_expense(
            category="management_fee",
            base_amount=0,
            is_recoverable=False,
            is_pct_egi=True,
            pct_egi=0.04,  # 4% of EGI
        )

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[mgmt_fee_expense],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market(gen_vac=0.0, credit_loss=0.0)},
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        egi = cf.effective_gross_income
        # Algebraic: fee = EGI * 0.04 / 1.04
        expected_fee = egi * Decimal("0.04") / Decimal("1.04")
        # operating_expenses is negative in the waterfall output
        actual_fee = -cf.operating_expenses
        assert abs(actual_fee - expected_fee) < Decimal("1")

    def test_noi_equals_egi_minus_opex(self):
        """NOI = EGI - opex (opex represented as negative in output)."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        slices = make_year1_slices("s1", 10_000 / 12)
        opex = make_expense(base_amount=20_000, is_recoverable=False)

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[opex],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        # operating_expenses is negative
        assert abs(cf.net_operating_income - (cf.effective_gross_income + cf.operating_expenses)) < Decimal("1")


class TestOperatingExpenseGrossUp:
    def test_gross_up_eligible_opex_is_normalized_at_low_occupancy(self):
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        market = {"office": make_market(gen_vac=0.0, credit_loss=0.0)}
        params = make_params(total_area=10_000)

        # Simple rent so EGI is positive; occupancy for gross-up is passed separately.
        slices = make_year1_slices("s1", 10_000 / 12)
        occupancy_by_month = [Decimal("1.0")] * 6 + [Decimal("0.0")] * 6

        variable_opex = make_expense(
            category="utilities",
            base_amount=120_000,
            growth_rate=0.0,
            is_recoverable=False,
            is_gross_up_eligible=True,
            gross_up_vacancy_pct=0.95,
        )

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[variable_opex],
            params=params,
            analysis=analysis,
            market_map=market,
            debt_schedule=[Decimal(0)],
            occupancy_by_month=occupancy_by_month,
        )

        cf = annual_cfs[0]
        expected_opex = Decimal("120000") * (Decimal("0.95") / Decimal("0.5"))
        assert abs((-cf.operating_expenses) - expected_opex) < Decimal("1")

    def test_non_eligible_opex_is_not_grossed_up(self):
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        market = {"office": make_market(gen_vac=0.0, credit_loss=0.0)}
        params = make_params(total_area=10_000)
        slices = make_year1_slices("s1", 10_000 / 12)
        occupancy_by_month = [Decimal("1.0")] * 6 + [Decimal("0.0")] * 6

        fixed_opex = make_expense(
            category="insurance",
            base_amount=120_000,
            growth_rate=0.0,
            is_recoverable=False,
            is_gross_up_eligible=False,
        )

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[fixed_opex],
            params=params,
            analysis=analysis,
            market_map=market,
            debt_schedule=[Decimal(0)],
            occupancy_by_month=occupancy_by_month,
        )

        cf = annual_cfs[0]
        assert abs((-cf.operating_expenses) - Decimal("120000")) < Decimal("1")

    def test_valuation_level_toggle_can_disable_gross_up(self):
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        market = {"office": make_market(gen_vac=0.0, credit_loss=0.0)}
        params = make_params(total_area=10_000, apply_stabilized_gross_up=False)
        slices = make_year1_slices("s1", 10_000 / 12)
        occupancy_by_month = [Decimal("1.0")] * 6 + [Decimal("0.0")] * 6

        variable_opex = make_expense(
            category="utilities",
            base_amount=120_000,
            growth_rate=0.0,
            is_recoverable=False,
            is_gross_up_eligible=True,
            gross_up_vacancy_pct=0.95,
        )

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[variable_opex],
            params=params,
            analysis=analysis,
            market_map=market,
            debt_schedule=[Decimal(0)],
            occupancy_by_month=occupancy_by_month,
        )

        cf = annual_cfs[0]
        assert abs((-cf.operating_expenses) - Decimal("120000")) < Decimal("1")

    def test_valuation_level_stabilized_occupancy_overrides_expense_target(self):
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        market = {"office": make_market(gen_vac=0.0, credit_loss=0.0)}
        params = make_params(total_area=10_000, stabilized_occupancy_pct=0.90)
        slices = make_year1_slices("s1", 10_000 / 12)
        occupancy_by_month = [Decimal("1.0")] * 6 + [Decimal("0.0")] * 6

        variable_opex = make_expense(
            category="utilities",
            base_amount=120_000,
            growth_rate=0.0,
            is_recoverable=False,
            is_gross_up_eligible=True,
            gross_up_vacancy_pct=0.95,  # should be overridden by valuation-level 0.90
        )

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[variable_opex],
            params=params,
            analysis=analysis,
            market_map=market,
            debt_schedule=[Decimal(0)],
            occupancy_by_month=occupancy_by_month,
        )

        cf = annual_cfs[0]
        expected_opex = Decimal("120000") * (Decimal("0.90") / Decimal("0.5"))
        assert abs((-cf.operating_expenses) - expected_opex) < Decimal("1")

    def test_waterfall_autocomputes_occupancy_when_not_passed(self):
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        market = {"office": make_market(gen_vac=0.0, credit_loss=0.0)}
        params = make_params(total_area=10_000)

        slices = []
        for i in range(12):
            if i < 6:
                slices.append(make_slice("s1", i, 10_000 / 12, is_vacant=False))
            else:
                slices.append(make_slice("s1", i, 0, is_vacant=True))

        variable_opex = make_expense(
            category="utilities",
            base_amount=120_000,
            growth_rate=0.0,
            is_recoverable=False,
            is_gross_up_eligible=True,
            gross_up_vacancy_pct=0.95,
        )

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[variable_opex],
            params=params,
            analysis=analysis,
            market_map=market,
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        expected_opex = Decimal("120000") * (Decimal("0.95") / Decimal("0.5"))
        assert abs((-cf.operating_expenses) - expected_opex) < Decimal("1")


class TestCapReserves:
    def test_capital_reserves_reduce_cfbd(self):
        """Capital reserves = -(cap_reserves_per_unit * total_area)."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        slices = make_year1_slices("s1", 10_000 / 12)

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(cap_reserves=0.25, total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)],
        )

        cf = annual_cfs[0]
        # Reserves = -(0.25 * 10000) = -$2500
        assert abs(cf.capital_reserves - Decimal("-2500")) < Decimal("1")
        # CFBD = NOI + cap_reserves (which is negative)
        assert abs(cf.cash_flow_before_debt - (cf.net_operating_income + cf.capital_reserves)) < Decimal("1")


class TestDebtService:
    def test_debt_service_reduces_levered_cf(self):
        """Debt service is deducted from CFBD to get levered CF."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        slices = make_year1_slices("s1", 10_000 / 12)

        debt_service = Decimal("5000")

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[debt_service],
        )

        cf = annual_cfs[0]
        assert cf.debt_service == -debt_service
        assert abs(cf.levered_cash_flow - (cf.cash_flow_before_debt - debt_service)) < Decimal("1")


class TestMultiYear:
    def test_10_year_analysis_produces_10_rows(self):
        """10-year analysis generates 10 annual cash flows."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)

        slices = [
            make_slice("s1", i, 10_000 / 12)
            for i in range(120)
        ]

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)] * 10,
        )

        assert len(annual_cfs) == 10
        assert annual_cfs[0].year == 1
        assert annual_cfs[-1].year == 10

    def test_expense_grows_across_years(self):
        """Operating expense grows at 3% per year."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)

        slices = [make_slice("s1", i, 10_000 / 12) for i in range(24)]
        # Months 12-23 fall in year 2 (Jan-Dec 2026)
        for s in slices[12:]:
            s.period_start = date(2026, s.month_index - 11, 1)
            s.period_end = end_of_month(s.period_start)

        opex = make_expense(base_amount=100_000, growth_rate=0.03, is_recoverable=False)

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[opex],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)] * 2,
        )

        assert len(annual_cfs) == 2
        # Year 1 opex = $100K (stored negative)
        assert abs(annual_cfs[0].operating_expenses + Decimal("100000")) < Decimal("1")
        # Year 2 opex = $103K
        assert abs(annual_cfs[1].operating_expenses + Decimal("103000")) < Decimal("1")


class TestAnalysisYearAnnualization:
    def test_start_anchored_years_use_full_annual_assumptions(self):
        """
        Annual assumptions (OpEx, other income, and capital reserves) should
        annualize over start-date-anchored 12-month buckets.
        """
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 24, 6)  # 2 full analysis years
        slices = [make_slice("s1", i, 0) for i in range(24)]

        fixed_opex = make_expense(
            category="taxes",
            base_amount=120_000,
            growth_rate=0.0,
            is_recoverable=False,
        )
        oi_item = OtherIncomeInput(
            income_id="oi_1",
            category="parking",
            base_amount=Decimal("24000"),
            growth_rate=Decimal("0"),
        )

        annual_cfs, _ = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[fixed_opex],
            params=make_params(cap_reserves=1.0, total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market(gen_vac=0.0, credit_loss=0.0)},
            debt_schedule=[Decimal(0)] * 2,
            other_income_items=[oi_item],
            other_income_annual=Decimal("12000"),
        )

        assert len(annual_cfs) == 2

        # 120,000 annual OpEx and 10,000 annual reserves for each full year.
        assert abs(annual_cfs[0].operating_expenses + Decimal("120000")) < Decimal("1")
        assert abs(annual_cfs[1].operating_expenses + Decimal("120000")) < Decimal("1")

        assert abs(annual_cfs[0].capital_reserves + Decimal("10000")) < Decimal("1")
        assert abs(annual_cfs[1].capital_reserves + Decimal("10000")) < Decimal("1")

        # Other income: legacy 12k + item 24k = 36k annual each year.
        assert abs(annual_cfs[0].other_income - Decimal("36000")) < Decimal("1")
        assert abs(annual_cfs[1].other_income - Decimal("36000")) < Decimal("1")


class TestSuiteAnnualBaseVsEffective:
    def test_base_rent_differs_from_effective_with_free_rent(self):
        """When free rent reduces effective_rent, suite details should distinguish base vs effective."""
        suite = make_suite("s1", area=10_000)
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)

        # 12 months: base_rent = $1000/mo, effective = $500/mo (free rent halves it)
        slices = []
        for m in range(12):
            period_start = date(2025, m // 12 + 1, 1) if m == 0 else date(2025, m + 1, 1)
            period_start = date(2025, m + 1, 1) if m < 12 else date(2026, 1, 1)
            # Construct month properly
            yr = 2025 + (m // 12)
            mo = (m % 12) + 1
            ps = date(yr, mo, 1)
            slices.append(MonthlySlice(
                month_index=m,
                period_start=ps,
                period_end=end_of_month(ps),
                suite_id="s1",
                lease_id="l_s1",
                tenant_name="Tenant A",
                base_rent=Decimal("1000"),
                free_rent_adjustment=Decimal("-500"),
                effective_rent=Decimal("500"),
                expense_recovery=Decimal(0),
                percentage_rent=Decimal(0),
                ti_cost=Decimal(0),
                lc_cost=Decimal(0),
                is_vacant=False,
                scenario_label="in_place",
                scenario_weight=Decimal(1),
            ))

        _, suite_details = build_annual_waterfall(
            suite_slices={"s1": slices},
            suites=[suite],
            expenses=[],
            params=make_params(total_area=10_000),
            analysis=analysis,
            market_map={"office": make_market()},
            debt_schedule=[Decimal(0)],
        )

        sd = [d for d in suite_details if d.suite_id == "s1"][0]
        # base_rent should be 12 * $1000 = $12,000
        assert abs(sd.base_rent - Decimal("12000")) < Decimal("1"), (
            f"base_rent={sd.base_rent}, expected 12000"
        )
        # effective_rent should be 12 * $500 = $6,000
        assert abs(sd.effective_rent - Decimal("6000")) < Decimal("1"), (
            f"effective_rent={sd.effective_rent}, expected 6000"
        )
        # They should be DIFFERENT
        assert sd.base_rent != sd.effective_rent
