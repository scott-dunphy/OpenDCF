"""Unit tests for DCF calculations."""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.dcf import (
    build_debt_schedule,
    calculate_irr,
    calculate_terminal_value,
    discount_cash_flows,
    going_in_cap_rate,
)
from src.engine.types import AnnualPropertyCashFlow, ValuationParams


def make_params(
    discount_rate: float = 0.08,
    exit_cap_rate: float = 0.065,
    exit_cap_year: int = -1,
    exit_costs_pct: float = 0.02,
    cap_reserves: float = 0.25,
    total_area: float = 10000,
) -> ValuationParams:
    return ValuationParams(
        discount_rate=Decimal(str(discount_rate)),
        exit_cap_rate=Decimal(str(exit_cap_rate)),
        exit_cap_year=exit_cap_year,
        exit_costs_pct=Decimal(str(exit_costs_pct)),
        capital_reserves_per_unit=Decimal(str(cap_reserves)),
        total_property_area=Decimal(str(total_area)),
        use_mid_year_convention=False,
        loan_amount=None,
        interest_rate=None,
        amortization_months=None,
        loan_term_months=None,
        io_period_months=0,
    )


def make_annual_cfs(noi_values: list[float]) -> list[AnnualPropertyCashFlow]:
    """Create simple AnnualPropertyCashFlow objects with given NOI values."""
    cfs = []
    for i, noi in enumerate(noi_values):
        noi_d = Decimal(str(noi))
        cfs.append(AnnualPropertyCashFlow(
            year=i + 1,
            period_start=date(2025 + i, 1, 1),
            period_end=date(2025 + i, 12, 31),
            gross_potential_rent=noi_d,
            free_rent=Decimal(0),
            absorption_vacancy=Decimal(0),
            loss_to_lease=Decimal(0),
            expense_recoveries=Decimal(0),
            percentage_rent=Decimal(0),
            other_income=Decimal(0),
            gross_potential_income=noi_d,
            general_vacancy_loss=Decimal(0),
            credit_loss=Decimal(0),
            effective_gross_income=noi_d,
            operating_expenses=Decimal(0),
            net_operating_income=noi_d,
            tenant_improvements=Decimal(0),
            leasing_commissions=Decimal(0),
            capital_reserves=Decimal(0),
            building_improvements=Decimal(0),
            cash_flow_before_debt=noi_d,
            debt_service=Decimal(0),
            levered_cash_flow=noi_d,
        ))
    return cfs


class TestTerminalValue:
    def test_basic_terminal_value(self):
        """NOI = $1M, exit cap = 6.5%, costs = 2%"""
        cfs = make_annual_cfs([1_000_000] * 10)
        params = make_params(exit_cap_rate=0.065, exit_costs_pct=0.02)
        tv = calculate_terminal_value(cfs, params, forward_year_noi=Decimal("1000000"))
        # Gross = 1M / 0.065 = $15,384,615.38
        # Net = 15,384,615.38 * 0.98 = $15,076,923.08
        expected = Decimal("1000000") / Decimal("0.065") * Decimal("0.98")
        assert abs(tv - expected) < Decimal("10")

    def test_specific_year_exit_cap(self):
        """Use Year 5 NOI for exit cap."""
        nois = [100_000 * (1.03 ** i) for i in range(10)]
        cfs = make_annual_cfs(nois)
        params = make_params(exit_cap_rate=0.065, exit_cap_year=5, exit_costs_pct=0.0)
        tv = calculate_terminal_value(cfs, params)
        expected = Decimal(str(nois[4])) / Decimal("0.065")
        assert abs(tv - expected) < Decimal("100")


class TestDiscounting:
    def test_pv_of_perpetuity(self):
        """$100K/yr perpetuity at 8% = $1.25M"""
        cfs = make_annual_cfs([100_000] * 10)
        params = make_params(discount_rate=0.08, exit_cap_rate=0.08, exit_costs_pct=0.0)
        tv = Decimal("100000") / Decimal("0.08")  # perpetuity = last NOI / rate
        pv_cfs, pv_tv, npv = discount_cash_flows(cfs, tv, Decimal("0.08"))
        # Total NPV should be approximately $1.25M (sum of discounted perpetuity)
        # Not exactly because this is a 10-yr hold, not infinite
        assert npv > Decimal("900000")
        assert npv < Decimal("1350000")

    def test_npv_simple_annuity(self):
        """PV of $100K/yr for 10 years at 8% = $671,008 (standard annuity formula)."""
        cfs = make_annual_cfs([100_000] * 10)
        pv_cfs, pv_tv, npv = discount_cash_flows(cfs, Decimal(0), Decimal("0.08"))
        # PV = 100000 * (1 - 1.08^-10) / 0.08 = 671,008.14
        expected = Decimal("671008.14")
        assert abs(pv_cfs - expected) < Decimal("1")


class TestIRR:
    def test_known_irr(self):
        """Investment of $1M returning $200K/yr for 7 years.
        IRR satisfies: 1M = 200K * PVIFA(r,7) → PVIFA = 5
        At r≈9.19%: PVIFA(9.19%, 7) ≈ 5.0
        """
        cfs = make_annual_cfs([200_000] * 7)
        irr = calculate_irr(cfs, Decimal(0), initial_investment=Decimal("1000000"))
        assert irr is not None
        # Verify: NPV at this IRR ≈ 0
        npv = -1_000_000 + sum(200_000 / (1 + float(irr)) ** t for t in range(1, 8))
        assert abs(npv) < 1.0  # within $1 of zero

    def test_irr_with_terminal_value(self):
        """$1M investment, $100K/yr for 10 years, $1.5M terminal value."""
        cfs = make_annual_cfs([100_000] * 10)
        irr = calculate_irr(cfs, Decimal("1500000"), initial_investment=Decimal("1000000"))
        assert irr is not None
        # Expected IRR > 10% given terminal value
        assert irr > Decimal("0.10")
        assert irr < Decimal("0.25")

    def test_irr_no_initial_investment(self):
        """IRR without initial investment — should handle gracefully."""
        cfs = make_annual_cfs([100_000] * 10)
        irr = calculate_irr(cfs, Decimal("1000000"))
        # Without negative CF, IRR is undefined / None
        assert irr is None


class TestDebtSchedule:
    def test_no_loan_returns_zeros(self):
        params = make_params()
        schedule = build_debt_schedule(params, 10)
        assert all(ds == Decimal(0) for ds in schedule)

    def test_fixed_payment_is_constant(self):
        """Amortizing years are constant until maturity; maturity year includes balloon."""
        params = ValuationParams(
            discount_rate=Decimal("0.07"), exit_cap_rate=Decimal("0.06"),
            exit_cap_year=-1, exit_costs_pct=Decimal("0"),
            capital_reserves_per_unit=Decimal("0"),
            total_property_area=Decimal("10000"),
            use_mid_year_convention=False,
            loan_amount=Decimal("1000000"), interest_rate=Decimal("0.05"),
            amortization_months=360, loan_term_months=120, io_period_months=0,
        )
        schedule = build_debt_schedule(params, 10)
        # Years 1-9 are identical amortizing service.
        first = schedule[0]
        assert first > Decimal(0)
        for yr, ds in enumerate(schedule[:9], 1):
            assert abs(ds - first) < Decimal("0.01"), f"Year {yr}: {ds} != {first}"
        # Year 10 contains balloon payoff.
        assert schedule[9] > schedule[0]

    def test_io_then_amortizing(self):
        """IO period is lower; maturity year includes balloon payoff."""
        params = ValuationParams(
            discount_rate=Decimal("0.07"), exit_cap_rate=Decimal("0.06"),
            exit_cap_year=-1, exit_costs_pct=Decimal("0"),
            capital_reserves_per_unit=Decimal("0"),
            total_property_area=Decimal("10000"),
            use_mid_year_convention=False,
            loan_amount=Decimal("1000000"), interest_rate=Decimal("0.05"),
            amortization_months=360, loan_term_months=120, io_period_months=24,
        )
        schedule = build_debt_schedule(params, 10)
        # Year 1 & 2 = IO, Year 3+ = amortizing
        io_annual = Decimal("1000000") * Decimal("0.05")  # $50,000
        assert abs(schedule[0] - io_annual) < Decimal("0.01")
        assert abs(schedule[1] - io_annual) < Decimal("0.01")
        # Amortizing payment should be higher than IO
        assert schedule[2] > schedule[0]
        # Amortizing years before maturity should be equal.
        for yr in range(2, 9):
            assert abs(schedule[yr] - schedule[2]) < Decimal("0.01")
        # Year 10 contains balloon payoff.
        assert schedule[9] > schedule[2]

    def test_zero_rate_divides_evenly(self):
        """0% interest: payment = principal / n_months."""
        params = ValuationParams(
            discount_rate=Decimal("0.07"), exit_cap_rate=Decimal("0.06"),
            exit_cap_year=-1, exit_costs_pct=Decimal("0"),
            capital_reserves_per_unit=Decimal("0"),
            total_property_area=Decimal("10000"),
            use_mid_year_convention=False,
            loan_amount=Decimal("360000"), interest_rate=Decimal("0"),
            amortization_months=360, loan_term_months=120, io_period_months=0,
        )
        schedule = build_debt_schedule(params, 10)
        # Monthly payment = 360000 / 360 = 1000
        expected_annual = Decimal("12000")
        assert abs(schedule[0] - expected_annual) < Decimal("0.01")

    def test_balloon_payoff_at_loan_maturity(self):
        """Debt service stops after maturity; maturity year includes balloon payoff."""
        params = ValuationParams(
            discount_rate=Decimal("0.07"), exit_cap_rate=Decimal("0.06"),
            exit_cap_year=-1, exit_costs_pct=Decimal("0"),
            capital_reserves_per_unit=Decimal("0"),
            total_property_area=Decimal("10000"),
            use_mid_year_convention=False,
            loan_amount=Decimal("1000000"), interest_rate=Decimal("0.06"),
            amortization_months=360, loan_term_months=60, io_period_months=0,
        )
        schedule = build_debt_schedule(params, 10)

        # No debt service after year 5 maturity.
        assert all(ds == Decimal(0) for ds in schedule[5:])
        # Maturity year should be larger than normal amortizing year due to balloon payoff.
        assert schedule[4] > schedule[0]


class TestGoingInCapRate:
    def test_basic_cap_rate(self):
        """Year 1 NOI = $650K, price = $10M → 6.5% cap rate"""
        cap = going_in_cap_rate(Decimal("650000"), Decimal("10000000"))
        assert abs(cap - Decimal("0.065")) < Decimal("0.0001")

    def test_zero_purchase_price_returns_zero(self):
        assert going_in_cap_rate(Decimal("100000"), Decimal(0)) == Decimal(0)
