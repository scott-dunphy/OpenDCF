from sqlalchemy import select
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.models.lease import Lease, Tenant
from src.models.market import MarketLeasingProfile
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.services.appraisal_reconstruction import build_plan, materialize_plan


async def test_appraisal_plan_clones_to_separate_property_and_valuation(db_session):
    prop = Property(
        name="Source",
        property_type="office",
        total_area=Decimal("10000"),
        area_unit="sf",
        analysis_start_date=date(2026, 1, 1),
    )
    db_session.add(prop)
    await db_session.flush()
    valuation = Valuation(
        property_id=prop.id,
        name="Source valuation",
        discount_rate=Decimal("0.08"),
        exit_cap_rate=Decimal("0.065"),
    )
    db_session.add(valuation)
    await db_session.flush()
    profile = MarketLeasingProfile(
        property_id=prop.id,
        valuation_id=valuation.id,
        space_type="anchor",
        market_rent_per_unit=Decimal("10"),
        rent_growth_rate_pct=Decimal("0.03"),
    )
    tenant = Tenant(property_id=prop.id, valuation_id=valuation.id, name="ABC Tenant")
    db_session.add_all([profile, tenant])
    await db_session.flush()
    suite = Suite(
        property_id=prop.id,
        valuation_id=valuation.id,
        suite_name="Anchor",
        area=Decimal("10000"),
        space_type="anchor",
        market_space_type="anchor",
    )
    db_session.add(suite)
    await db_session.flush()
    db_session.add(
        Lease(
            suite_id=suite.id,
            tenant_id=tenant.id,
            lease_start_date=date(2021, 1, 1),
            lease_end_date=date(2030, 12, 31),
            base_rent_per_unit=Decimal("9"),
        )
    )
    await db_session.commit()
    fact = SimpleNamespace(
        field_path="valuation.discount_rate",
        value_json='"0.09"',
        confidence=0.98,
        page_number=71,
        source_quote="Discount rate 9%",
        status="accepted",
    )

    plan, unresolved = await build_plan(db_session, valuation, [fact])
    rebuilt_property, rebuilt_valuation = await materialize_plan(db_session, plan)
    await db_session.commit()

    assert not unresolved
    assert rebuilt_property.id != prop.id
    assert rebuilt_valuation.property_id == rebuilt_property.id
    assert rebuilt_valuation.discount_rate == Decimal("0.09")
    assert "Imported Appraisal" in rebuilt_valuation.name
    profiles = (await db_session.execute(
        select(MarketLeasingProfile).where(MarketLeasingProfile.valuation_id == rebuilt_valuation.id)
    )).scalars().all()
    assert [p.space_type for p in profiles] == ["anchor"]
    # The rebuilt valuation owns its own copy of the model
    suites = (await db_session.execute(select(Suite).where(Suite.valuation_id == rebuilt_valuation.id))).scalars().all()
    assert [s.suite_name for s in suites] == ["Anchor"] and suites[0].id != suite.id
    assert suites[0].property_id == rebuilt_property.id
    tenants = (await db_session.execute(select(Tenant).where(Tenant.valuation_id == rebuilt_valuation.id))).scalars().all()
    assert [t.name for t in tenants] == ["ABC Tenant"]
    assert rebuilt_valuation.analysis_start_date_override == date(2026, 1, 1)

    # Materializing into an existing property adds a valuation there and keeps the property as is
    plan2, _ = await build_plan(db_session, valuation, [fact])
    plan2["target_property_id"] = prop.id
    same_property, added = await materialize_plan(db_session, plan2, prop)
    await db_session.commit()
    assert same_property.id == prop.id and added.property_id == prop.id and prop.name == "Source"
    added_suites = (await db_session.execute(select(Suite).where(Suite.valuation_id == added.id))).scalars().all()
    assert len(added_suites) == 1 and added_suites[0].id != suite.id


async def test_lease_recovery_terms_reach_the_created_valuation(db_session):
    from sqlalchemy import select

    from src.models.lease import LeaseExpenseRecovery
    from src.models.recovery_structure import RecoveryStructure, RecoveryStructureItem
    from src.services.appraisal_reconstruction import normalize_structured_plan

    prop = Property(
        name="Import",
        property_type="office",
        total_area=Decimal("10000"),
        area_unit="sf",
        analysis_start_date=date(2026, 1, 1),
    )
    db_session.add(prop)
    await db_session.flush()
    valuation = Valuation(
        property_id=prop.id, name="Import", discount_rate=Decimal("0.08"), exit_cap_rate=Decimal("0.065")
    )
    db_session.add(valuation)
    await db_session.commit()

    plan, _ = await build_plan(db_session, valuation, [])
    plan.update(
        suites=[
            {"source_id": "s1", "suite_name": "100", "area": 6000, "space_type": "office"},
            {"source_id": "s2", "suite_name": "200", "area": 4000, "space_type": "office"},
        ],
        tenants=[{"source_id": "t1", "name": "Acme"}, {"source_id": "t2", "name": "Beta"}],
        leases=[
            {
                "source_id": "l1", "source_suite_id": "s1", "source_tenant_id": "t1",
                "lease_start_date": "2024-01-01", "lease_end_date": "2030-12-31",
                "base_rent_per_unit": 30, "recovery_type": "Base Year",
                "escalation_type": "percent", "escalation_pct_annual": "3%",
                "pro_rata_share_pct": "60%", "base_year": "2024 calendar year",
                "upon_expiration": "Option", "option_term_months": 60,
            },
            {
                "source_id": "l2", "source_suite_id": "s2", "source_tenant_id": "t2",
                "lease_start_date": "2025-01-01", "lease_end_date": "2029-12-31",
                "base_rent_per_unit": 28, "recovery_type": "NNN",
                "source_recovery_structure_id": "rs1",
            },
        ],
        expenses=[
            {"category": "Real Estate Taxes", "base_year_amount": 100000},
            {"category": "CAM", "base_year_amount": 50000},
        ],
        lease_expense_recoveries=[
            {
                "source_lease_id": "l1", "expense_category": "cam", "recovery_type": "nnn",
                "cap_per_sf_annual": 1.5, "cap_growth_pct": "5%", "admin_fee_pct": 15,
                "cap_group": "controllable",
            },
            {"source_lease_id": "l1", "expense_category": "parking", "recovery_type": "nnn"},
        ],
        recovery_structures=[{"source_id": "rs1", "name": "Standard NNN", "default_recovery_type": "triple net"}],
        recovery_structure_items=[
            {"source_recovery_structure_id": "rs1", "expense_category": "Real Estate Taxes", "recovery_type": "nnn"},
            {"source_recovery_structure_id": "missing", "expense_category": "cam", "recovery_type": "nnn"},
        ],
    )
    normalize_structured_plan(plan)

    lease = plan["leases"][0]
    assert lease["recovery_type"] == "base_year_stop"
    assert lease["escalation_type"] == "pct_annual"
    assert lease["escalation_pct_annual"] == "0.03"
    assert lease["pro_rata_share_pct"] == "0.6"
    assert lease["base_year"] == 2024
    assert lease["upon_expiration"] == "option"
    assert plan["recovery_structures"][0]["default_recovery_type"] == "nnn"
    assert len(plan["recovery_structure_items"]) == 1
    notes = " ".join(plan["review_notes"])
    assert "Acme: recovery terms for 'parking'" in notes
    assert "recovery setup is missing" in notes

    rebuilt_property, _ = await materialize_plan(db_session, plan)
    await db_session.commit()

    overrides = list((await db_session.execute(select(LeaseExpenseRecovery))).scalars())
    cam = next(o for o in overrides if o.expense_category == "cam")
    assert cam.cap_per_sf_annual == Decimal("1.5")
    assert cam.cap_growth_pct == Decimal("0.05")
    assert cam.admin_fee_pct == Decimal("0.15")
    assert cam.cap_group == "controllable"
    structure = (
        await db_session.execute(
            select(RecoveryStructure).where(RecoveryStructure.property_id == rebuilt_property.id)
        )
    ).scalar_one()
    item = (await db_session.execute(select(RecoveryStructureItem))).scalar_one()
    assert item.recovery_structure_id == structure.id
    assert item.expense_category == "real_estate_taxes"
    beta = (
        await db_session.execute(select(Lease).where(Lease.base_rent_per_unit == Decimal("28")))
    ).scalar_one()
    assert beta.recovery_structure_id == structure.id


def test_escalation_types_and_whole_number_rates_are_checked():
    from src.services.appraisal_reconstruction import normalize_structured_plan

    plan = {
        "property": {}, "valuation": {}, "suites": [], "market_leasing_profiles": [], "expenses": [],
        "tenants": [{"source_id": "t1", "name": "Acme"}],
        "rent_steps": [{"source_lease_id": "l3", "effective_date": "2027-01-01", "rent_per_unit": 31}],
        "leases": [
            {"source_id": "l1", "lease_start_date": "2025-01-01", "lease_end_date": "2030-12-31", "source_tenant_id": "t1", "escalation_type": "Percentage", "escalation_pct_annual": 1,
             "pro_rata_share_pct": 1},
            {"source_id": "l2", "lease_start_date": "2025-01-01", "lease_end_date": "2030-12-31", "escalation_type": "CPI-U", "cpi_floor": "2%"},
            {"source_id": "l3", "lease_start_date": "2025-01-01", "lease_end_date": "2030-12-31", "escalation_type": "Stepped per schedule"},
        ],
        "lease_expense_recoveries": [],
    }
    normalize_structured_plan(plan)
    l1, l2, l3 = plan["leases"]
    assert l1["escalation_type"] == "pct_annual"
    assert l1["escalation_pct_annual"] == "0.01"
    assert l1["pro_rata_share_pct"] == "1"
    assert l2["escalation_type"] == "cpi" and l2["cpi_floor"] == "0.02"
    assert l3["escalation_type"] == "fixed_step"
    notes = " ".join(plan["review_notes"])
    assert "Acme: annual escalation of 1 read as 1%." in notes
    assert "escalation 'Stepped per schedule' is not recognised and was set to fixed_step" in notes


def test_reapplied_property_type_fact_keeps_a_known_code():
    """materialize_plan reapplies reviewed facts after normalizing; a descriptive type must not return."""
    from src.services.appraisal_reconstruction import normalize_structured_plan, refresh_fact_overlays

    fact = {"field_path": "property.property_type", "review_status": "accepted",
            "value": "Single-tenant net lease (STNL) retail – freestanding drive-thru coffee"}
    plan = {"property": {"property_type": "office"}, "valuation": {}, "appraisal_facts": [fact]}
    normalize_structured_plan(refresh_fact_overlays(plan))
    assert plan["property"]["property_type"] == "retail"
    refresh_fact_overlays(plan)  # what materialize_plan does next
    assert plan["property"]["property_type"] == "retail"

    unknown = {"field_path": "property.property_type", "review_status": "accepted", "value": "Car wash"}
    plan = {"property": {"property_type": "industrial"}, "valuation": {}, "appraisal_facts": [unknown]}
    refresh_fact_overlays(plan)
    assert plan["property"]["property_type"] == "industrial"


def test_capital_reserves_and_incomplete_capital_rows_become_review_notes():
    from src.services.appraisal_reconstruction import normalize_structured_plan

    plan = {
        "property": {}, "valuation": {}, "suites": [], "market_leasing_profiles": [], "expenses": [],
        "tenants": [], "leases": [], "rent_steps": [], "lease_expense_recoveries": [],
        "capital_projects": [
            {"source_id": "CAP-RESERVES", "name": "Capital reserves", "amount": 5000, "start_date": "2021-05-01",
             "frequency": "annual", "is_recurring": True},
            {"source_id": "ROOF", "name": "Roof replacement", "amount": 250000, "start_date": "2027-04-01"},
            {"source_id": "HVAC", "description": "HVAC", "start_date": "2027-01-01"},
        ],
    }
    normalize_structured_plan(plan)
    assert plan["capital_projects"] == [{
        "source_id": "ROOF", "description": "Roof replacement", "total_amount": 250000,
        "start_date": "2027-04-01", "duration_months": 1,
    }]
    notes = " ".join(plan["review_notes"])
    assert "Capital reserves" in notes and "recurring reserve" in notes and "HVAC" in notes
