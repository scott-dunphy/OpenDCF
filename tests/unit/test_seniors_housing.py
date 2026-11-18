from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.seniors_housing import (
    AncillaryRevenueInput,
    CapexInput,
    CareLevelTier,
    DebtInput,
    ExpenseLineInput,
    OccupancyRampInput,
    SeniorsHousingModelInput,
    SeniorsHousingScenarioInput,
    SNFPayerMixInput,
    UnitTypeInput,
    ValuationAssumptions,
    run_seniors_housing_scenarios,
    run_seniors_housing_sensitivity,
    run_seniors_housing_valuation,
)


def _base_model() -> SeniorsHousingModelInput:
    """A realistic mixed AL/MC community for testing."""
    al_studio = UnitTypeInput(
        name="AL Studio",
        acuity="assisted_living",
        unit_type="studio",
        count=40,
        avg_sf=Decimal("350"),
        monthly_base_fee=Decimal("5400"),
        second_person_fee_monthly=Decimal("1200"),
        second_person_pct=Decimal("0.10"),
        community_fee=Decimal("5400"),
        avg_length_of_stay_months=Decimal("22"),
        stabilized_occupancy=Decimal("0.88"),
        annual_turnover_rate=Decimal("0.45"),
        care_level_tiers=(
            CareLevelTier(name="Level 1", monthly_surcharge=Decimal("500"), pct_of_residents=Decimal("0.30")),
            CareLevelTier(name="Level 2", monthly_surcharge=Decimal("1200"), pct_of_residents=Decimal("0.45")),
            CareLevelTier(name="Level 3", monthly_surcharge=Decimal("2200"), pct_of_residents=Decimal("0.25")),
        ),
    )
    al_1br = UnitTypeInput(
        name="AL 1-BR",
        acuity="assisted_living",
        unit_type="one_br",
        count=20,
        avg_sf=Decimal("550"),
        monthly_base_fee=Decimal("6200"),
        second_person_fee_monthly=Decimal("1200"),
        second_person_pct=Decimal("0.20"),
        community_fee=Decimal("6200"),
        avg_length_of_stay_months=Decimal("24"),
        stabilized_occupancy=Decimal("0.90"),
        annual_turnover_rate=Decimal("0.42"),
        care_level_tiers=(
            CareLevelTier(name="Level 1", monthly_surcharge=Decimal("500"), pct_of_residents=Decimal("0.35")),
            CareLevelTier(name="Level 2", monthly_surcharge=Decimal("1200"), pct_of_residents=Decimal("0.40")),
            CareLevelTier(name="Level 3", monthly_surcharge=Decimal("2200"), pct_of_residents=Decimal("0.25")),
        ),
    )
    mc_private = UnitTypeInput(
        name="MC Private",
        acuity="memory_care",
        unit_type="private",
        count=24,
        avg_sf=Decimal("300"),
        monthly_base_fee=Decimal("6800"),
        community_fee=Decimal("6800"),
        avg_length_of_stay_months=Decimal("20"),
        stabilized_occupancy=Decimal("0.85"),
        annual_turnover_rate=Decimal("0.40"),
        care_level_tiers=(
            CareLevelTier(name="MC Standard", monthly_surcharge=Decimal("1500"), pct_of_residents=Decimal("0.60")),
            CareLevelTier(name="MC High", monthly_surcharge=Decimal("2800"), pct_of_residents=Decimal("0.40")),
        ),
    )
    il_1br = UnitTypeInput(
        name="IL 1-BR",
        acuity="independent_living",
        unit_type="one_br",
        count=30,
        avg_sf=Decimal("700"),
        monthly_base_fee=Decimal("3200"),
        second_person_fee_monthly=Decimal("800"),
        second_person_pct=Decimal("0.25"),
        community_fee=Decimal("3200"),
        avg_length_of_stay_months=Decimal("28"),
        stabilized_occupancy=Decimal("0.92"),
        annual_turnover_rate=Decimal("0.25"),
    )

    expenses = (
        ExpenseLineInput(
            name="Nursing & Caregiving",
            category="labor",
            annual_fixed=Decimal("800000"),
            per_occupied_unit_month=Decimal("1800"),
            applies_to_acuity=("assisted_living", "memory_care"),
        ),
        ExpenseLineInput(
            name="Dietary Staff",
            category="labor",
            annual_fixed=Decimal("320000"),
        ),
        ExpenseLineInput(
            name="Housekeeping",
            category="labor",
            annual_fixed=Decimal("180000"),
        ),
        ExpenseLineInput(
            name="Admin & Management Staff",
            category="labor",
            annual_fixed=Decimal("420000"),
        ),
        ExpenseLineInput(
            name="Activities Staff",
            category="labor",
            annual_fixed=Decimal("95000"),
        ),
        ExpenseLineInput(
            name="Maintenance Staff",
            category="labor",
            annual_fixed=Decimal("140000"),
        ),
        ExpenseLineInput(
            name="Food & Dietary Costs",
            category="food",
            per_occupied_unit_month=Decimal("350"),
        ),
        ExpenseLineInput(
            name="General Liability Insurance",
            category="insurance",
            annual_fixed=Decimal("120000"),
            growth_pct=Decimal("0.04"),
        ),
        ExpenseLineInput(
            name="Professional Liability Insurance",
            category="insurance",
            annual_fixed=Decimal("95000"),
            growth_pct=Decimal("0.045"),
        ),
        ExpenseLineInput(
            name="Marketing & Advertising",
            category="marketing",
            annual_fixed=Decimal("180000"),
            growth_pct=Decimal("0.03"),
        ),
        ExpenseLineInput(
            name="Utilities",
            category="utilities",
            annual_fixed=Decimal("210000"),
            per_occupied_unit_month=Decimal("80"),
        ),
        ExpenseLineInput(
            name="Property Taxes",
            category="property_tax",
            annual_fixed=Decimal("280000"),
            growth_pct=Decimal("0.025"),
        ),
        ExpenseLineInput(
            name="Medical Supplies",
            category="medical_supplies",
            per_occupied_unit_month=Decimal("120"),
            applies_to_acuity=("assisted_living", "memory_care"),
        ),
        ExpenseLineInput(
            name="Management Fee",
            category="management_fee",
            pct_of_revenue=Decimal("0.05"),
        ),
    )

    ancillary = (
        AncillaryRevenueInput(
            name="Respite / Short-Stay",
            annual_fixed=Decimal("60000"),
            growth_pct=Decimal("0.03"),
        ),
        AncillaryRevenueInput(
            name="Beauty Salon",
            per_occupied_unit_month=Decimal("25"),
            growth_pct=Decimal("0.02"),
        ),
        AncillaryRevenueInput(
            name="Guest Meals",
            annual_fixed=Decimal("18000"),
            growth_pct=Decimal("0.02"),
        ),
    )

    capex = (
        CapexInput(name="Capital Reserves", annual_per_unit=Decimal("400")),
        CapexInput(name="FF&E Replacement", annual_fixed=Decimal("50000")),
    )

    valuation = ValuationAssumptions(
        hold_years=10,
        discount_rate=Decimal("0.09"),
        exit_cap_rate=Decimal("0.075"),
        fee_growth_rate=Decimal("0.04"),
        expense_growth_rate=Decimal("0.035"),
        initial_purchase_price=Decimal("32000000"),
        use_mid_year_convention=True,
    )

    return SeniorsHousingModelInput(
        as_of_date=date(2026, 1, 1),
        community_name="Sunrise Assisted Living",
        unit_types=(al_studio, al_1br, mc_private, il_1br),
        ancillary_revenue=ancillary,
        expenses=expenses,
        capex=capex,
        valuation=valuation,
    )


def test_basic_valuation_generates_outputs():
    result = run_seniors_housing_valuation(_base_model())
    assert len(result.annual_cash_flows) == 10
    assert result.npv_unlevered > Decimal(0)
    assert result.terminal_value_net > Decimal(0)
    assert result.irr_unlevered is not None


def test_unit_type_detail_drill_down():
    """Each year's cash flow should have expandable unit type detail."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]

    # 4 unit types
    assert len(y1.unit_type_detail) == 4

    # Verify each unit type has revenue
    for det in y1.unit_type_detail:
        assert det.total_revenue > Decimal(0)
        assert det.occupied_units > Decimal(0)
        assert Decimal(0) < det.occupancy_pct <= Decimal(1)

    # AL units should have care level revenue
    al_detail = [d for d in y1.unit_type_detail if d.acuity == "assisted_living"]
    assert all(d.care_level_revenue > Decimal(0) for d in al_detail)

    # MC units should have care level revenue
    mc_detail = [d for d in y1.unit_type_detail if d.acuity == "memory_care"]
    assert all(d.care_level_revenue > Decimal(0) for d in mc_detail)


def test_expense_detail_drill_down():
    """Each year should have expandable expense line detail with acuity breakdown."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]

    assert len(y1.expense_detail) > 0

    # Nursing expense should have acuity breakdown
    nursing = [e for e in y1.expense_detail if e.name == "Nursing & Caregiving"]
    assert len(nursing) == 1
    assert nursing[0].amount > Decimal(0)
    # Should only apply to AL and MC
    assert "assisted_living" in nursing[0].acuity_breakdown
    assert "memory_care" in nursing[0].acuity_breakdown
    assert "independent_living" not in nursing[0].acuity_breakdown


def test_care_level_tiers_add_revenue():
    """Care level surcharges should increase revenue vs no tiers."""
    base = _base_model()
    # Strip care tiers from all units
    no_tiers = tuple(replace(ut, care_level_tiers=()) for ut in base.unit_types)
    model_no_tiers = replace(base, unit_types=no_tiers)

    result_with = run_seniors_housing_valuation(base)
    result_without = run_seniors_housing_valuation(model_no_tiers)

    assert result_with.annual_cash_flows[0].care_level_revenue > Decimal(0)
    assert result_without.annual_cash_flows[0].care_level_revenue == Decimal(0)
    assert result_with.annual_cash_flows[0].effective_gross_income > result_without.annual_cash_flows[0].effective_gross_income


def test_second_person_fees():
    """Second person fees should contribute to revenue."""
    base = _base_model()
    # Strip second person from all units
    no_sp = tuple(replace(ut, second_person_pct=Decimal(0)) for ut in base.unit_types)
    model_no_sp = replace(base, unit_types=no_sp)

    result_with = run_seniors_housing_valuation(base)
    result_without = run_seniors_housing_valuation(model_no_sp)

    assert result_with.annual_cash_flows[0].second_person_revenue > Decimal(0)
    assert result_without.annual_cash_flows[0].second_person_revenue == Decimal(0)


def test_community_fees_on_move_in():
    """Community fees are revenue when residents move in (turnover)."""
    base = _base_model()
    result = run_seniors_housing_valuation(base)
    y1 = result.annual_cash_flows[0]
    assert y1.community_fee_revenue > Decimal(0)

    # Zero out community fees
    no_cf = tuple(replace(ut, community_fee=Decimal(0)) for ut in base.unit_types)
    result_no_cf = run_seniors_housing_valuation(replace(base, unit_types=no_cf))
    assert result_no_cf.annual_cash_flows[0].community_fee_revenue == Decimal(0)


def test_management_fee_as_pct_of_revenue():
    """Management fee should be % of EGI."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]
    assert y1.management_fee > Decimal(0)
    expected = y1.effective_gross_income * Decimal("0.05")
    assert abs(y1.management_fee - expected) < Decimal("1")


def test_ebitdarm_equals_noi_plus_mgmt_fee():
    """EBITDARM = NOI + management fee."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]
    assert abs(y1.ebitdarm - (y1.noi + y1.management_fee)) < Decimal("0.01")


def test_revenue_grows_over_hold_period():
    """Revenue should grow year-over-year by fee_growth_rate."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]
    y10 = result.annual_cash_flows[9]
    # 4% growth over 9 years ≈ 42% increase
    assert y10.effective_gross_income > y1.effective_gross_income * Decimal("1.30")


def test_operating_metrics_populated():
    """RevPOR, RevPAR, OpEx ratio, NOI margin should be computed."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]
    assert y1.rev_por > Decimal(0)
    assert y1.rev_par > Decimal(0)
    assert Decimal(0) < y1.operating_expense_ratio < Decimal(1)
    assert Decimal(0) < y1.noi_margin < Decimal(1)


def test_occupancy_ramp_up():
    """Occupancy ramp should start low and increase to stabilized."""
    base = _base_model()
    ramp = OccupancyRampInput(
        start_occupancy=Decimal("0.20"),
        monthly_absorption_units=Decimal("4"),
        stabilization_month=30,
    )
    model = replace(base, occupancy_ramp=ramp)
    result = run_seniors_housing_valuation(model)

    y1 = result.annual_cash_flows[0]
    y3 = result.annual_cash_flows[2]
    y5 = result.annual_cash_flows[4]

    # Year 1 should have lower occupancy than year 3
    assert y1.avg_occupancy_pct < y3.avg_occupancy_pct
    # Year 5 should be at or near stabilized (ramp done by month 30)
    assert y5.avg_occupancy_pct > y1.avg_occupancy_pct


def test_debt_service():
    """Debt should produce debt service and lower levered CF."""
    base = _base_model()
    debt = DebtInput(
        loan_amount=Decimal("20000000"),
        interest_rate=Decimal("0.065"),
        amortization_months=360,
        term_months=120,
        io_period_months=12,
    )
    model = replace(base, debt=debt)
    result = run_seniors_housing_valuation(model)
    y1 = result.annual_cash_flows[0]
    assert y1.debt_service > Decimal(0)
    assert y1.levered_cash_flow < y1.cash_flow_before_debt

    no_debt = run_seniors_housing_valuation(base)
    assert no_debt.annual_cash_flows[0].debt_service == Decimal(0)


def test_zero_levered_discount_rate_is_honored():
    """Explicit zero levered rate should not silently fall back to unlevered discount rate."""
    base = _base_model()
    debt = DebtInput(
        loan_amount=Decimal("20000000"),
        interest_rate=Decimal("0.065"),
        amortization_months=360,
        term_months=120,
        io_period_months=12,
    )
    with_debt = replace(base, debt=debt)
    default_result = run_seniors_housing_valuation(with_debt)
    zero_levered_rate = run_seniors_housing_valuation(
        replace(
            with_debt,
            valuation=replace(with_debt.valuation, levered_discount_rate=Decimal("0.0")),
        )
    )
    assert zero_levered_rate.npv_unlevered == default_result.npv_unlevered
    assert zero_levered_rate.npv_levered > default_result.npv_levered


def test_snf_payer_mix_revenue():
    """SNF units with payer mix should generate payer revenue."""
    base = _base_model()
    snf_unit = UnitTypeInput(
        name="SNF Private",
        acuity="skilled_nursing",
        unit_type="private",
        count=30,
        avg_sf=Decimal("250"),
        monthly_base_fee=Decimal("0"),  # Revenue comes from payer mix
        stabilized_occupancy=Decimal("0.85"),
        annual_turnover_rate=Decimal("0.30"),
    )
    snf_payers = (
        SNFPayerMixInput(payer="medicare", pct_of_days=Decimal("0.15"), daily_rate=Decimal("550")),
        SNFPayerMixInput(payer="medicaid", pct_of_days=Decimal("0.55"), daily_rate=Decimal("250")),
        SNFPayerMixInput(payer="private_pay", pct_of_days=Decimal("0.20"), daily_rate=Decimal("350")),
        SNFPayerMixInput(payer="insurance", pct_of_days=Decimal("0.10"), daily_rate=Decimal("400")),
    )
    model = replace(
        base,
        unit_types=base.unit_types + (snf_unit,),
        snf_payer_mix=snf_payers,
    )
    result = run_seniors_housing_valuation(model)
    y1 = result.annual_cash_flows[0]
    assert y1.snf_payer_revenue > Decimal(0)

    # SNF detail should show payer revenue
    snf_detail = [d for d in y1.unit_type_detail if d.acuity == "skilled_nursing"]
    assert len(snf_detail) == 1
    assert snf_detail[0].snf_payer_revenue > Decimal(0)


def test_ancillary_revenue():
    """Ancillary revenue lines should add to total."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]
    assert y1.ancillary_revenue > Decimal(0)
    assert len(y1.ancillary_detail) == 3


def test_capex_detail():
    """CapEx detail should be populated."""
    result = run_seniors_housing_valuation(_base_model())
    y1 = result.annual_cash_flows[0]
    assert y1.total_capex > Decimal(0)
    assert len(y1.capex_detail) == 2


def test_scenario_analysis():
    """Scenario analysis should produce different NPVs."""
    base = _base_model()
    scenarios = (
        SeniorsHousingScenarioInput(name="Downside", occupancy_multiplier=Decimal("0.90"), opex_multiplier=Decimal("1.05")),
        SeniorsHousingScenarioInput(name="Upside", occupancy_multiplier=Decimal("1.05"), rate_multiplier=Decimal("1.03")),
    )
    results = run_seniors_housing_scenarios(base, scenarios)
    assert len(results) == 2
    assert results[0].scenario_name == "Downside"
    assert results[1].scenario_name == "Upside"

    base_result = run_seniors_housing_valuation(base)
    assert results[0].result.npv_unlevered < base_result.npv_unlevered
    assert results[1].result.npv_unlevered > base_result.npv_unlevered


def test_sensitivity_grid():
    """Sensitivity grid should produce correct number of points."""
    base = _base_model()
    points = run_seniors_housing_sensitivity(
        base,
        discount_rates=(Decimal("0.08"), Decimal("0.09"), Decimal("0.10")),
        exit_cap_rates=(Decimal("0.07"), Decimal("0.08")),
        occupancy_multipliers=(Decimal("0.95"), Decimal("1.00")),
    )
    assert len(points) == 12  # 3 x 2 x 2


def test_going_in_cap_rate():
    """Going-in cap rate should be Y1 NOI / purchase price."""
    result = run_seniors_housing_valuation(_base_model())
    assert result.going_in_cap_rate is not None
    expected = result.annual_cash_flows[0].noi / Decimal("32000000")
    assert abs(result.going_in_cap_rate - expected) < Decimal("0.0001")


def test_noi_flow_is_consistent():
    """EGI - total_opex = NOI should hold."""
    result = run_seniors_housing_valuation(_base_model())
    for row in result.annual_cash_flows:
        expected_noi = row.effective_gross_income - row.total_operating_expenses
        assert abs(row.noi - expected_noi) < Decimal("0.01")


def test_cfbd_flow_is_consistent():
    """NOI - capex = CFBD should hold."""
    result = run_seniors_housing_valuation(_base_model())
    for row in result.annual_cash_flows:
        expected_cfbd = row.noi - row.total_capex
        assert abs(row.cash_flow_before_debt - expected_cfbd) < Decimal("0.01")


def test_mid_year_convention_increases_npv():
    """Mid-year convention should produce higher NPV."""
    base = _base_model()
    eoy = replace(base, valuation=replace(base.valuation, use_mid_year_convention=False))
    mid = replace(base, valuation=replace(base.valuation, use_mid_year_convention=True))
    result_eoy = run_seniors_housing_valuation(eoy)
    result_mid = run_seniors_housing_valuation(mid)
    assert result_mid.npv_unlevered > result_eoy.npv_unlevered


def test_expense_categories_sum_to_total():
    """Category subtotals should sum to total operating expenses."""
    result = run_seniors_housing_valuation(_base_model())
    for row in result.annual_cash_flows:
        cat_sum = (
            row.total_labor + row.total_food_dietary + row.total_insurance
            + row.total_marketing + row.total_utilities + row.total_property_tax
            + row.total_medical_supplies + row.management_fee + row.total_other_expenses
        )
        assert abs(cat_sum - row.total_operating_expenses) < Decimal("0.01")


def test_acuity_specific_expenses():
    """Expenses with applies_to_acuity should only charge those units."""
    base = _base_model()
    result = run_seniors_housing_valuation(base)
    y1 = result.annual_cash_flows[0]

    # Medical supplies only applies to AL and MC
    med = [e for e in y1.expense_detail if e.name == "Medical Supplies"]
    assert len(med) == 1
    assert "independent_living" not in med[0].acuity_breakdown
    assert "assisted_living" in med[0].acuity_breakdown or "memory_care" in med[0].acuity_breakdown


def test_invalid_snf_payer_mix_sum_raises():
    base = _base_model()
    bad_payer_mix = (
        SNFPayerMixInput(payer="medicare", pct_of_days=Decimal("0.8"), daily_rate=Decimal("550")),
        SNFPayerMixInput(payer="medicaid", pct_of_days=Decimal("0.4"), daily_rate=Decimal("250")),
    )
    with pytest.raises(ValueError, match="SNF payer mix"):
        run_seniors_housing_valuation(replace(base, snf_payer_mix=bad_payer_mix))


def test_invalid_care_level_tier_sum_raises():
    base = _base_model()
    bad_units = list(base.unit_types)
    bad_units[0] = replace(
        bad_units[0],
        care_level_tiers=(
            CareLevelTier(name="L1", monthly_surcharge=Decimal("500"), pct_of_residents=Decimal("0.8")),
            CareLevelTier(name="L2", monthly_surcharge=Decimal("1000"), pct_of_residents=Decimal("0.4")),
        ),
    )
    with pytest.raises(ValueError, match="care_level_tiers"):
        run_seniors_housing_valuation(replace(base, unit_types=tuple(bad_units)))


def test_debt_service_stops_after_full_amortization():
    from src.engine.seniors_housing import DebtInput, _build_debt_service
    debt = DebtInput(loan_amount=Decimal("1000000"), interest_rate=Decimal("0.06"), amortization_months=60)
    svc, _, balances = _build_debt_service(debt, 8)
    assert svc[4] > 0 and balances[4] < Decimal("0.01")
    assert svc[5] == svc[6] == svc[7] == Decimal(0)


def test_community_fees_on_lease_up_move_ins():
    """With no turnover, a ramping community still collects a fee from every unit it absorbs."""
    from src.engine.seniors_housing import _effective_occupancy
    base = _base_model()
    units = tuple(replace(ut, annual_turnover_rate=Decimal(0)) for ut in base.unit_types)
    ramp = OccupancyRampInput(start_occupancy=Decimal("0.20"), monthly_absorption_units=Decimal("2"),
                              stabilization_month=60)
    stable = run_seniors_housing_valuation(replace(base, unit_types=units))
    assert stable.annual_cash_flows[0].community_fee_revenue == Decimal(0)

    model = replace(base, unit_types=units, occupancy_ramp=ramp)
    total = sum(u.count for u in units)
    expected = sum(
        ut.community_fee * (_effective_occupancy(ut, 1, 12, ramp, total) - _effective_occupancy(ut, 1, 1, ramp, total))
        for ut in units
    )
    y1 = run_seniors_housing_valuation(model).annual_cash_flows[0]
    assert expected > 0
    assert y1.community_fee_revenue == pytest.approx(expected)


def test_expense_growth_defaults_to_valuation_rate():
    base = _base_model()
    lines = (ExpenseLineInput(name="Default", category="labor", annual_fixed=Decimal(100000)),
             ExpenseLineInput(name="Own", category="labor", annual_fixed=Decimal(100000), growth_pct=Decimal("0.02")))
    model = replace(base, expenses=lines, valuation=replace(base.valuation, expense_growth_rate=Decimal("0.05")))
    y2 = {e.name: e.amount for e in run_seniors_housing_valuation(model).annual_cash_flows[1].expense_detail}
    assert y2["Default"] == pytest.approx(Decimal(105000))
    assert y2["Own"] == pytest.approx(Decimal(102000))
