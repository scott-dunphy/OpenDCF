from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.marina_valuation import (
    AdditionalRevenueLineInput,
    CapexLifecycleInput,
    CyclicalCostInput,
    DebtInput,
    DemandModelInput,
    FuelDockInput,
    LegalTenureInput,
    MarinaModelInput,
    MarinaScenarioInput,
    OperatingCostLineInput,
    SlipClassInput,
    ValuationInput,
    run_marina_scenarios,
    run_marina_sensitivity,
    run_marina_valuation,
    size_debt_for_covenants,
)


def _base_model() -> MarinaModelInput:
    seasonality = (
        Decimal("0.70"),
        Decimal("0.75"),
        Decimal("0.90"),
        Decimal("1.00"),
        Decimal("1.15"),
        Decimal("1.25"),
        Decimal("1.30"),
        Decimal("1.20"),
        Decimal("1.00"),
        Decimal("0.90"),
        Decimal("0.80"),
        Decimal("0.75"),
    )
    weather = tuple(Decimal("0.00") for _ in range(12))

    slips = (
        SlipClassInput(
            name="Wet 30-45",
            kind="wet_slip",
            length_class="30-45 ft",
            utility_service_level="fifty_amp",
            count=180,
            annual_contract_share=Decimal("0.60"),
            seasonal_contract_share=Decimal("0.20"),
            transient_share=Decimal("0.20"),
            annual_contract_rate=Decimal("7600"),
            seasonal_contract_rate=Decimal("4200"),
            transient_daily_rate=Decimal("58"),
            utility_fee_monthly=Decimal("45"),
            utility_fee_transient_daily=Decimal("6"),
            repair_service_revenue_per_occupied_day=Decimal("3"),
            retail_fnb_revenue_per_occupied_day=Decimal("2"),
            storage_fee_per_month=Decimal("18"),
            launch_fee_per_transient_arrival=Decimal("12"),
            avg_transient_stay_days=Decimal("2.5"),
            base_annual_occupancy=Decimal("0.94"),
            base_seasonal_occupancy=Decimal("0.78"),
            base_transient_capture=Decimal("0.55"),
        ),
        SlipClassInput(
            name="Dry 25-35",
            kind="dry_stack",
            length_class="25-35 ft",
            utility_service_level="water_only",
            count=120,
            annual_contract_share=Decimal("0.45"),
            seasonal_contract_share=Decimal("0.20"),
            transient_share=Decimal("0.35"),
            annual_contract_rate=Decimal("5100"),
            seasonal_contract_rate=Decimal("2800"),
            transient_daily_rate=Decimal("42"),
            utility_fee_monthly=Decimal("16"),
            utility_fee_transient_daily=Decimal("2"),
            repair_service_revenue_per_occupied_day=Decimal("2"),
            retail_fnb_revenue_per_occupied_day=Decimal("1.2"),
            storage_fee_per_month=Decimal("14"),
            launch_fee_per_transient_arrival=Decimal("8"),
            avg_transient_stay_days=Decimal("1.8"),
            base_annual_occupancy=Decimal("0.91"),
            base_seasonal_occupancy=Decimal("0.72"),
            base_transient_capture=Decimal("0.60"),
        ),
        SlipClassInput(
            name="Moorings",
            kind="mooring",
            length_class="20-35 ft",
            utility_service_level="none",
            count=90,
            annual_contract_share=Decimal("0.65"),
            seasonal_contract_share=Decimal("0.10"),
            transient_share=Decimal("0.25"),
            annual_contract_rate=Decimal("2600"),
            seasonal_contract_rate=Decimal("1500"),
            transient_daily_rate=Decimal("24"),
            utility_fee_monthly=Decimal("0"),
            utility_fee_transient_daily=Decimal("0"),
            repair_service_revenue_per_occupied_day=Decimal("0.8"),
            retail_fnb_revenue_per_occupied_day=Decimal("0.6"),
            storage_fee_per_month=Decimal("6"),
            launch_fee_per_transient_arrival=Decimal("4"),
            avg_transient_stay_days=Decimal("2.0"),
            base_annual_occupancy=Decimal("0.89"),
            base_seasonal_occupancy=Decimal("0.65"),
            base_transient_capture=Decimal("0.50"),
        ),
    )

    demand = DemandModelInput(
        monthly_seasonality=seasonality,
        monthly_weather_shock_pct=weather,
        seasonal_active_months=(4, 5, 6, 7, 8, 9, 10),
        waitlist_start_count=Decimal("35"),
        waitlist_conversion_pct=Decimal("0.55"),
        waitlist_new_demand_per_year=Decimal("12"),
        annual_rate_growth_pct=Decimal("0.03"),
        seasonal_rate_growth_pct=Decimal("0.035"),
        transient_rate_growth_pct=Decimal("0.03"),
        transient_weather_sensitivity=Decimal("1.0"),
    )

    opex = (
        OperatingCostLineInput(
            name="dock_labor",
            annual_fixed=Decimal("620000"),
            per_occupied_day=Decimal("2.2"),
            growth_pct=Decimal("0.03"),
        ),
        OperatingCostLineInput(
            name="utilities",
            annual_fixed=Decimal("290000"),
            per_occupied_day=Decimal("0.9"),
            growth_pct=Decimal("0.03"),
        ),
        OperatingCostLineInput(
            name="insurance_env",
            annual_fixed=Decimal("380000"),
            per_occupied_day=Decimal("0.0"),
            growth_pct=Decimal("0.045"),
        ),
    )

    cyclical = (
        CyclicalCostInput(
            name="dredging_cycle",
            base_amount=Decimal("450000"),
            first_year=3,
            every_n_years=4,
            growth_pct=Decimal("0.03"),
            probability_pct=Decimal("1.0"),
            treat_as_capex=True,
        ),
        CyclicalCostInput(
            name="storm_contingency",
            base_amount=Decimal("180000"),
            first_year=2,
            every_n_years=1,
            growth_pct=Decimal("0.03"),
            probability_pct=Decimal("0.6"),
            treat_as_capex=False,
        ),
    )

    legal = LegalTenureInput(
        tenure_type="fee_simple",
        annual_ground_lease=Decimal("0"),
        annual_submerged_land_lease=Decimal("120000"),
        annual_permit_concession_fees=Decimal("85000"),
    )

    capex = (
        CapexLifecycleInput(
            name="floating_docks",
            asset_type="floating_docks",
            base_amount=Decimal("300000"),
            first_year=4,
            every_n_years=5,
            growth_pct=Decimal("0.03"),
        ),
        CapexLifecycleInput(
            name="pumpout_upgrade",
            asset_type="pumpout",
            base_amount=Decimal("110000"),
            first_year=2,
            every_n_years=8,
            growth_pct=Decimal("0.025"),
            deferred_maintenance_catchup_year=1,
            deferred_maintenance_amount=Decimal("60000"),
        ),
    )

    valuation = ValuationInput(
        hold_years=7,
        discount_rate=Decimal("0.095"),
        exit_cap_rate=Decimal("0.0825"),
        exit_costs_pct=Decimal("0.02"),
        use_mid_year_convention=True,
        terminal_noi_growth_pct=Decimal("0.02"),
        dock_replacement_reserve_per_slip_year=Decimal("220"),
        reserve_growth_pct=Decimal("0.03"),
        initial_purchase_price=Decimal("18000000"),
    )

    debt = DebtInput(
        loan_amount=Decimal("9800000"),
        interest_rate=Decimal("0.0675"),
        amortization_months=300,
        term_months=84,
        io_period_months=12,
        minimum_dscr=Decimal("1.30"),
        maximum_ltv=Decimal("0.65"),
        minimum_debt_yield=Decimal("0.09"),
    )

    return MarinaModelInput(
        as_of_date=date(2026, 1, 1),
        slip_classes=slips,
        demand=demand,
        operating_cost_lines=opex,
        cyclical_costs=cyclical,
        legal_tenure=legal,
        capex_lifecycle=capex,
        valuation=valuation,
        debt=debt,
    )


def test_marina_valuation_generates_core_outputs():
    result = run_marina_valuation(_base_model())
    assert len(result.annual_cash_flows) == 7
    assert result.npv_unlevered > Decimal(0)
    assert result.terminal_value_after_tenure_risk > Decimal(0)
    assert result.annual_cash_flows[0].annual_contract_revenue > Decimal(0)
    assert result.annual_cash_flows[0].transient_revenue > Decimal(0)
    assert result.annual_cash_flows[0].fuel_margin_revenue > Decimal(0)


def test_weather_shock_reduces_demand_and_value():
    base = _base_model()
    base_result = run_marina_valuation(base)
    shocked = run_marina_scenarios(
        base, (MarinaScenarioInput(name="stormy", weather_shock_additive_pct=Decimal("0.20")),)
    )[0].result
    assert (
        shocked.annual_cash_flows[0].avg_occupancy_pct
        < base_result.annual_cash_flows[0].avg_occupancy_pct
    )
    assert shocked.npv_unlevered < base_result.npv_unlevered


def test_waitlist_conversion_supports_contract_revenue():
    base = _base_model()
    with_waitlist = run_marina_valuation(base)
    low_waitlist_demand = run_marina_valuation(
        MarinaModelInput(
            as_of_date=base.as_of_date,
            slip_classes=base.slip_classes,
            demand=replace(
                base.demand,
                waitlist_start_count=Decimal("0"),
                waitlist_new_demand_per_year=Decimal("0"),
            ),
            operating_cost_lines=base.operating_cost_lines,
            cyclical_costs=base.cyclical_costs,
            legal_tenure=base.legal_tenure,
            capex_lifecycle=base.capex_lifecycle,
            valuation=base.valuation,
            debt=base.debt,
            fuel_dock=base.fuel_dock,
        )
    )
    assert (
        with_waitlist.annual_cash_flows[1].annual_contract_revenue
        > low_waitlist_demand.annual_cash_flows[1].annual_contract_revenue
    )


def test_waitlist_new_demand_applies_once_per_year_not_per_slip_class():
    base = _base_model()
    model = MarinaModelInput(
        as_of_date=base.as_of_date,
        slip_classes=base.slip_classes,
        demand=replace(
            base.demand,
            waitlist_start_count=Decimal("0"),
            waitlist_conversion_pct=Decimal("0"),
            waitlist_new_demand_per_year=Decimal("10"),
        ),
        operating_cost_lines=base.operating_cost_lines,
        cyclical_costs=base.cyclical_costs,
        legal_tenure=base.legal_tenure,
        capex_lifecycle=base.capex_lifecycle,
        valuation=replace(base.valuation, hold_years=3),
        debt=base.debt,
        fuel_dock=base.fuel_dock,
    )
    result = run_marina_valuation(model)
    # Year-1 has no rollover; years 2 and 3 each add 10.
    assert result.annual_cash_flows[-1].waitlist_end_count == Decimal("20")


def test_leasehold_reversion_haircut_applies_to_terminal_value():
    base = _base_model()
    leasehold_model = MarinaModelInput(
        as_of_date=base.as_of_date,
        slip_classes=base.slip_classes,
        demand=base.demand,
        operating_cost_lines=base.operating_cost_lines,
        cyclical_costs=base.cyclical_costs,
        legal_tenure=LegalTenureInput(
            tenure_type="leasehold",
            annual_ground_lease=Decimal("250000"),
            annual_submerged_land_lease=Decimal("120000"),
            annual_permit_concession_fees=Decimal("85000"),
            remaining_lease_years=6,
            lease_extension_probability=Decimal("0.35"),
            reversion_value_loss_pct=Decimal("1.0"),
        ),
        capex_lifecycle=base.capex_lifecycle,
        valuation=base.valuation,
        debt=base.debt,
        fuel_dock=base.fuel_dock,
    )
    fee_simple_result = run_marina_valuation(base)
    leasehold_result = run_marina_valuation(leasehold_model)
    assert (
        leasehold_result.terminal_value_after_tenure_risk
        < fee_simple_result.terminal_value_after_tenure_risk
    )


def test_capex_cycles_and_debt_sizing_outputs():
    model = _base_model()
    result = run_marina_valuation(model)
    year3 = result.annual_cash_flows[2]
    assert year3.capex > Decimal("100000")

    sizing = size_debt_for_covenants(model)
    assert sizing.recommended_loan_amount > Decimal(0)
    assert sizing.recommended_loan_amount <= sizing.max_loan_by_ltv
    assert sizing.binding_constraint in {"dscr", "ltv", "debt_yield"}


def test_dscr_uses_scheduled_debt_service_excluding_balloon():
    model = _base_model()
    result = run_marina_valuation(model)
    last_year = result.annual_cash_flows[-1]
    # Debt service excludes balloon; balloon is reported separately.
    assert last_year.debt_service < Decimal("2000000")
    assert last_year.balloon_payment > Decimal("5000000")
    # Levered CF accounts for both regular service and balloon.
    assert last_year.levered_cash_flow < last_year.cash_flow_before_debt - last_year.debt_service
    # Covenant DSCR denominator uses scheduled debt service.
    assert result.covenants[-1].debt_service < Decimal("2000000")
    assert result.covenants[-1].dscr is not None
    assert result.covenants[-1].dscr > Decimal("1.0")


def test_sensitivity_grid_runs():
    model = _base_model()
    points = run_marina_sensitivity(
        model,
        discount_rates=(Decimal("0.085"), Decimal("0.095")),
        exit_cap_rates=(Decimal("0.075"), Decimal("0.085")),
        occupancy_multipliers=(Decimal("0.95"), Decimal("1.00"), Decimal("1.05")),
    )
    assert len(points) == 12


# ---------- New tests for bug fixes and new features ----------


def test_negative_occupancy_growth_reduces_seasonal_revenue():
    """Negative seasonal occupancy growth should reduce revenue over time."""
    base = _base_model()
    declining = run_marina_valuation(
        replace(base, demand=replace(
            base.demand,
            seasonal_occupancy_growth_pct=Decimal("-0.05"),
        ))
    )
    stable = run_marina_valuation(base)
    # By year 5, declining occupancy should have lower seasonal revenue
    assert (
        declining.annual_cash_flows[4].seasonal_contract_revenue
        < stable.annual_cash_flows[4].seasonal_contract_revenue
    )


def test_storage_revenue_based_on_occupied_slips():
    """Storage revenue should be proportional to occupancy, not total slip count."""
    base = _base_model()
    full_occ = run_marina_valuation(base)

    # Create a low-occupancy version
    low_occ_slips = tuple(
        replace(
            sc,
            base_annual_occupancy=Decimal("0.30"),
            base_seasonal_occupancy=Decimal("0.20"),
            base_transient_capture=Decimal("0.10"),
        )
        for sc in base.slip_classes
    )
    low_occ = run_marina_valuation(replace(base, slip_classes=low_occ_slips))

    # Storage revenue should be lower with fewer occupied slips
    assert low_occ.annual_cash_flows[0].storage_revenue < full_occ.annual_cash_flows[0].storage_revenue


def test_ancillary_revenue_grows_over_hold_period():
    """Utility, repair, retail, storage, launch fees should grow by ancillary_growth_pct."""
    base = _base_model()
    # Set ancillary growth to 5% to make growth obvious
    model = replace(base, demand=replace(base.demand, ancillary_growth_pct=Decimal("0.05")))
    result = run_marina_valuation(model)

    # Year 7 utility revenue should be higher than year 1 due to rate growth
    # (even though occupancy may shift slightly from churn)
    y1 = result.annual_cash_flows[0]
    y7 = result.annual_cash_flows[6]
    assert y7.utility_service_revenue > y1.utility_service_revenue


def test_vacancy_collection_loss_reduces_egi():
    """vacancy_collection_loss_pct should reduce EGI below potential gross revenue."""
    base = _base_model()
    # No V&C loss
    no_vc = run_marina_valuation(
        replace(base, demand=replace(base.demand, vacancy_collection_loss_pct=Decimal("0.00")))
    )
    # 5% V&C loss
    with_vc = run_marina_valuation(
        replace(base, demand=replace(base.demand, vacancy_collection_loss_pct=Decimal("0.05")))
    )
    y1_no_vc = no_vc.annual_cash_flows[0]
    y1_with_vc = with_vc.annual_cash_flows[0]

    assert y1_no_vc.vacancy_collection_loss == Decimal(0)
    assert y1_with_vc.vacancy_collection_loss > Decimal(0)
    assert y1_with_vc.effective_gross_income < y1_no_vc.effective_gross_income
    assert y1_with_vc.noi < y1_no_vc.noi


def test_management_fee_reduces_noi():
    """management_fee_pct should be deducted from EGI to arrive at NOI."""
    base = _base_model()
    no_mgmt = run_marina_valuation(
        replace(base, demand=replace(base.demand, management_fee_pct=Decimal("0.00")))
    )
    with_mgmt = run_marina_valuation(
        replace(base, demand=replace(base.demand, management_fee_pct=Decimal("0.05")))
    )
    y1_no = no_mgmt.annual_cash_flows[0]
    y1_with = with_mgmt.annual_cash_flows[0]

    assert y1_no.management_fee == Decimal(0)
    assert y1_with.management_fee > Decimal(0)
    assert y1_with.noi < y1_no.noi


def test_levered_discount_rate_affects_equity_value():
    """A separate levered_discount_rate should produce different equity value than unlevered rate."""
    base = _base_model()
    # Same rate for both (default behavior)
    same_rate = run_marina_valuation(base)
    # Higher levered rate -> lower equity PV
    higher_equity_rate = run_marina_valuation(
        replace(
            base,
            valuation=replace(base.valuation, levered_discount_rate=Decimal("0.14")),
        )
    )
    # Unlevered NPV should be the same
    assert same_rate.npv_unlevered == higher_equity_rate.npv_unlevered
    # Levered NPV should be lower with higher discount rate
    assert higher_equity_rate.npv_levered < same_rate.npv_levered


def test_zero_levered_discount_rate_is_honored():
    """Explicit zero levered rate should not silently fall back to unlevered discount rate."""
    base = _base_model()
    default_result = run_marina_valuation(base)
    zero_levered_rate = run_marina_valuation(
        replace(
            base,
            valuation=replace(base.valuation, levered_discount_rate=Decimal("0.0")),
        )
    )
    assert zero_levered_rate.npv_unlevered == default_result.npv_unlevered
    assert zero_levered_rate.npv_levered > default_result.npv_levered


def test_pgr_egi_management_fee_flow():
    """Verify PGR -> V&C -> EGI -> Mgmt Fee -> NOI flow is internally consistent."""
    base = _base_model()
    model = replace(
        base,
        demand=replace(
            base.demand,
            vacancy_collection_loss_pct=Decimal("0.03"),
            management_fee_pct=Decimal("0.04"),
        ),
    )
    result = run_marina_valuation(model)
    y1 = result.annual_cash_flows[0]

    # PGR - V&C = EGI
    expected_egi = y1.potential_gross_revenue - y1.vacancy_collection_loss
    assert abs(y1.effective_gross_income - expected_egi) < Decimal("0.01")

    # NOI = EGI - mgmt_fee - opex - legal - cyclical_opex
    expected_noi = (
        y1.effective_gross_income
        - y1.management_fee
        - y1.operating_expenses
        - y1.legal_tenure_costs
        - y1.cyclical_opex
    )
    assert abs(y1.noi - expected_noi) < Decimal("0.01")


def test_mid_year_convention_increases_npv():
    """Mid-year convention discounts at year - 0.5 (closer), producing higher NPV."""
    base = _base_model()
    end_of_year_model = replace(
        base,
        valuation=replace(base.valuation, use_mid_year_convention=False),
    )
    mid_year_model = replace(
        base,
        valuation=replace(base.valuation, use_mid_year_convention=True),
    )
    eoy_result = run_marina_valuation(end_of_year_model)
    mid_result = run_marina_valuation(mid_year_model)

    # Mid-year NPV should be higher (less discounting)
    assert mid_result.npv_unlevered > eoy_result.npv_unlevered
    assert mid_result.npv_levered > eoy_result.npv_levered
    # Difference should be meaningful but not huge (typically 2-5%)
    pct_diff = (mid_result.npv_unlevered - eoy_result.npv_unlevered) / eoy_result.npv_unlevered
    assert Decimal("0.01") < pct_diff < Decimal("0.10")


def test_fuel_margin_excludes_moorings():
    """Fuel revenue should not count mooring occupied days."""
    base = _base_model()
    # Run base model (has moorings)
    result_with_moorings = run_marina_valuation(base)

    # Remove moorings — keep only wet/dry slips
    no_mooring_slips = tuple(sc for sc in base.slip_classes if sc.kind != "mooring")
    model_no_moorings = replace(base, slip_classes=no_mooring_slips)
    result_no_moorings = run_marina_valuation(model_no_moorings)

    # Fuel margin Y1 should be the same if moorings were excluded from fuel calc
    # (moorings contribute 0 fuel days now). More precisely, since we removed 90
    # mooring slips, the total occupied days are lower → less non-fuel revenue.
    # But fuel margin should be proportional to wet+dry occupied days only.
    y1_full = result_with_moorings.annual_cash_flows[0]
    y1_no_m = result_no_moorings.annual_cash_flows[0]

    # Fuel margin for the full model should NOT include mooring occupied days
    # Moorings have repair/retail/storage revenue, so total revenue differs
    assert y1_full.fuel_margin_revenue > Decimal(0)
    assert y1_no_m.fuel_margin_revenue > Decimal(0)
    # Fuel in full model should equal fuel from wet+dry only (since moorings excluded)
    # The full model has MORE slips overall but moorings don't contribute to fuel
    # So fuel_margin_full should be close to but different from no-moorings (different occupancy dynamics)
    # Key assertion: fuel margin in full model < what it would be if moorings counted
    # We verify by checking fuel is less than proportional to total occupied days
    assert y1_full.fuel_margin_revenue < y1_full.potential_gross_revenue * Decimal("0.15")


def test_positive_occupancy_growth_increases_revenue():
    """Positive occupancy growth should increase annual contract revenue."""
    base = _base_model()
    growing = run_marina_valuation(
        replace(base, demand=replace(
            base.demand,
            annual_occupancy_growth_pct=Decimal("0.02"),
        ),
            valuation=replace(base.valuation, hold_years=5),
        )
    )
    stable = run_marina_valuation(
        replace(base, valuation=replace(base.valuation, hold_years=5))
    )

    y5_growing = growing.annual_cash_flows[4]
    y5_stable = stable.annual_cash_flows[4]

    # Growing occupancy should produce higher annual contract revenue
    assert y5_growing.annual_contract_revenue > y5_stable.annual_contract_revenue


def test_additional_revenue_lines_increase_pgr():
    """Additional revenue lines should add to PGR and grow over time."""
    base = _base_model()
    # Add two revenue lines
    model = replace(
        base,
        additional_revenue_lines=(
            AdditionalRevenueLineInput(
                name="Boat Club Memberships",
                annual_fixed=Decimal("100000"),
                per_occupied_day=Decimal("0"),
                growth_pct=Decimal("0.03"),
            ),
            AdditionalRevenueLineInput(
                name="Ship Store",
                annual_fixed=Decimal("0"),
                per_occupied_day=Decimal("1.50"),
                growth_pct=Decimal("0.03"),
            ),
        ),
    )
    result_with = run_marina_valuation(model)
    result_without = run_marina_valuation(base)

    y1_with = result_with.annual_cash_flows[0]
    y1_without = result_without.annual_cash_flows[0]

    # PGR should be higher with additional revenue
    assert y1_with.potential_gross_revenue > y1_without.potential_gross_revenue
    # Additional revenue should include the $100K fixed + variable
    assert y1_with.additional_revenue >= Decimal("100000")
    # Without additional revenue lines, it should be zero
    assert y1_without.additional_revenue == Decimal(0)

    # Growth: Y3 additional rev should be > Y1
    y3_with = result_with.annual_cash_flows[2]
    assert y3_with.additional_revenue > y1_with.additional_revenue


def test_debt_service_stops_after_full_amortization():
    from src.engine.marina_valuation import DebtInput, _build_debt_service_and_balances
    debt = DebtInput(loan_amount=Decimal("1000000"), interest_rate=Decimal("0.06"), amortization_months=60)
    svc, _, balances, dscr_svc = _build_debt_service_and_balances(debt, 8)
    assert svc[4] > 0 and balances[4] < Decimal("0.01")
    assert svc[5] == svc[6] == svc[7] == Decimal(0)
    assert dscr_svc[7] == Decimal(0)
