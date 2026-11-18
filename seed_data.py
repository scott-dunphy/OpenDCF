"""
Seed example data for OpenDCF — Commercial Real Estate Valuation Engine.

Usage:
    python seed_data.py

Creates 6 example properties with realistic tenants, leases, expenses,
market profiles, and valuations. Runs valuations via the engine.
"""

import asyncio
import sys
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from src.db.session import AsyncSessionLocal, engine
from src.models.base import Base
from src.models.expense import PropertyExpense
from src.models.lease import Lease, Tenant
from src.models.market import MarketLeasingProfile
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.services.valuation_service import ValuationService


def uid():
    return str(uuid.uuid4())


async def seed():
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Check if data already exists
        result = await session.execute(select(Property).limit(1))
        if result.scalar_one_or_none():
            print("Database already contains data. To re-seed, delete opendcf.db and run again.")
            return

        print("Seeding example data...")

        # ──────────────────────────────────────────────
        # TENANTS
        # ──────────────────────────────────────────────
        tenants = {}
        tenant_data = [
            ("Goldman Advisory LLC", "AA", "Finance"),
            ("Kirkland & Ellis LLP", "A+", "Legal"),
            ("Deloitte Consulting", "AA", "Consulting"),
            ("Bloomberg Analytics", "AA-", "Technology"),
            ("Cushman & Wakefield", "A", "Real Estate Services"),
            ("Whole Foods Market", "A", "Grocery"),
            ("Chipotle Mexican Grill", "BBB+", "Restaurant"),
            ("Amazon Logistics", "AAA", "Logistics"),
            ("FedEx Ground Services", "A", "Logistics"),
            ("Allstate Insurance", "A+", "Insurance"),
        ]
        for name, rating, industry in tenant_data:
            key = name.split()[0].lower()
            t = Tenant(id=uid(), name=name, credit_rating=rating, industry=industry)
            tenants[key] = t
            session.add(t)

        print(f"  Created {len(tenants)} tenants")

        # ──────────────────────────────────────────────
        # PROPERTY 1: One Liberty Plaza (Office, NYC)
        # ──────────────────────────────────────────────
        p1_id = uid()
        p1 = Property(
            id=p1_id, name="One Liberty Plaza",
            address_line1="100 Wall Street", city="New York", state="NY", zip_code="10005",
            property_type="office", total_area=Decimal("250000"), area_unit="sf",
            year_built=2001, analysis_start_date=date(2025, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
        )
        session.add(p1)

        p1_suites = [
            ("Suite 100", 1, Decimal("45000"), "office"),
            ("Suite 200", 2, Decimal("35000"), "office"),
            ("Suite 300", 3, Decimal("30000"), "office"),
            ("Suite 400", 4, Decimal("28000"), "office"),
            ("Suite 500", 5, Decimal("25000"), "office"),
            ("Suite 600", 6, Decimal("32000"), "office"),
            ("Suite 700", 7, Decimal("30000"), "office"),
            ("Suite 800", 8, Decimal("25000"), "office"),
        ]
        p1_suite_ids = {}
        for name, floor, area, stype in p1_suites:
            sid = uid()
            p1_suite_ids[name] = sid
            session.add(Suite(id=sid, property_id=p1_id, suite_name=name,
                              floor=floor, area=area, space_type=stype, is_available=True))

        # P1 Leases
        p1_leases = [
            (p1_suite_ids["Suite 100"], tenants["goldman"].id, "in_place",
             date(2022, 1, 1), date(2029, 12, 31), Decimal("65"), "pct_annual", Decimal("0.03"),
             None, None, "nnn", None, None, None, None),
            (p1_suite_ids["Suite 200"], tenants["kirkland"].id, "in_place",
             date(2023, 7, 1), date(2030, 6, 30), Decimal("72"), "pct_annual", Decimal("0.025"),
             None, None, "full_service_gross", None, None, None, None),
            (p1_suite_ids["Suite 300"], tenants["deloitte"].id, "in_place",
             date(2024, 1, 1), date(2028, 12, 31), Decimal("58"), "cpi", None,
             Decimal("0.02"), Decimal("0.04"), "nnn", None, None, None, None),
            (p1_suite_ids["Suite 400"], tenants["bloomberg"].id, "in_place",
             date(2021, 3, 1), date(2028, 2, 28), Decimal("68"), "pct_annual", Decimal("0.03"),
             None, None, "nnn", None, None, None, None),
            # Suite 500: VACANT — no lease
            (p1_suite_ids["Suite 600"], tenants["cushman"].id, "in_place",
             date(2023, 1, 1), date(2027, 12, 31), Decimal("55"), "flat", None,
             None, None, "modified_gross", None, None, Decimal("12"), None),
            (p1_suite_ids["Suite 700"], tenants["allstate"].id, "in_place",
             date(2024, 6, 1), date(2031, 5, 31), Decimal("62"), "pct_annual", Decimal("0.025"),
             None, None, "nnn", None, None, None, None),
            # Suite 800: VACANT — no lease
        ]
        for (suite_id, tenant_id, ltype, start, end, rent, esc_type, esc_pct,
             cpi_floor, cpi_cap, rec_type, base_year, bys_amount, exp_stop, pct_rent_bp) in p1_leases:
            session.add(Lease(
                id=uid(), suite_id=suite_id, tenant_id=tenant_id, lease_type=ltype,
                lease_start_date=start, lease_end_date=end,
                base_rent_per_unit=rent, rent_payment_frequency="annual",
                escalation_type=esc_type, escalation_pct_annual=esc_pct,
                cpi_floor=cpi_floor, cpi_cap=cpi_cap,
                recovery_type=rec_type, base_year=base_year,
                base_year_stop_amount=bys_amount, expense_stop_per_sf=exp_stop,
            ))

        # P1 Expenses
        p1_expenses = [
            ("real_estate_taxes", "Real Estate Taxes", Decimal("2500000"), Decimal("0.03"), True, False, None),
            ("insurance", "Property Insurance", Decimal("375000"), Decimal("0.03"), True, False, None),
            ("cam", "Common Area Maintenance", Decimal("1250000"), Decimal("0.025"), True, True, Decimal("0.95")),
            ("utilities", "Utilities", Decimal("875000"), Decimal("0.03"), True, False, None),
            ("management_fee", "Property Management", Decimal("0"), Decimal("0"), False, False, None,
             True, Decimal("0.04")),
            ("repairs_maintenance", "Repairs & Maintenance", Decimal("500000"), Decimal("0.02"), True, False, None),
        ]
        for exp in p1_expenses:
            is_egi = len(exp) > 7 and exp[7]
            session.add(PropertyExpense(
                id=uid(), property_id=p1_id, category=exp[0], description=exp[1],
                base_year_amount=exp[2], growth_rate_pct=exp[3],
                is_recoverable=exp[4], is_gross_up_eligible=exp[5],
                gross_up_vacancy_pct=exp[6],
                is_pct_of_egi=is_egi, pct_of_egi=exp[8] if is_egi else None,
            ))

        # P1 Market Profile
        session.add(MarketLeasingProfile(
            id=uid(), property_id=p1_id, space_type="office",
            description="Class A Manhattan Office",
            market_rent_per_unit=Decimal("65"), rent_growth_rate_pct=Decimal("0.03"),
            new_lease_term_months=60, new_tenant_ti_per_sf=Decimal("45"),
            new_tenant_lc_pct=Decimal("0.06"), new_tenant_free_rent_months=2, downtime_months=3,
            renewal_probability=Decimal("0.65"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("20"), renewal_lc_pct=Decimal("0.03"),
            renewal_free_rent_months=0, renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0.05"), credit_loss_pct=Decimal("0.01"),
        ))

        # P1 Valuation
        v1_id = uid()
        session.add(Valuation(
            id=v1_id, property_id=p1_id, name="Base Case Q1 2025",
            description="Core office hold analysis with standard assumptions",
            discount_rate=Decimal("0.08"), exit_cap_rate=Decimal("0.065"),
            exit_costs_pct=Decimal("0.02"), capital_reserves_per_unit=Decimal("0.25"),
        ))

        print("  Created: One Liberty Plaza (Office, NYC)")

        # ──────────────────────────────────────────────
        # PROPERTY 2: Westfield Town Center (Retail, Dallas)
        # ──────────────────────────────────────────────
        p2_id = uid()
        p2 = Property(
            id=p2_id, name="Westfield Town Center",
            address_line1="5500 Belt Line Road", city="Dallas", state="TX", zip_code="75254",
            property_type="retail", total_area=Decimal("85000"), area_unit="sf",
            year_built=2008, analysis_start_date=date(2025, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
        )
        session.add(p2)

        p2_suites = [
            ("Anchor Space", 1, Decimal("25000"), "retail"),
            ("Pad A", 1, Decimal("15000"), "retail"),
            ("Pad B", 1, Decimal("12000"), "retail"),
            ("Inline 1", 1, Decimal("18000"), "retail"),
            ("Inline 2", 1, Decimal("15000"), "retail"),
        ]
        p2_suite_ids = {}
        for name, floor, area, stype in p2_suites:
            sid = uid()
            p2_suite_ids[name] = sid
            session.add(Suite(id=sid, property_id=p2_id, suite_name=name,
                              floor=floor, area=area, space_type=stype, is_available=True))

        # P2 Leases
        session.add(Lease(
            id=uid(), suite_id=p2_suite_ids["Anchor Space"], tenant_id=tenants["whole"].id,
            lease_type="in_place", lease_start_date=date(2020, 3, 1), lease_end_date=date(2030, 2, 28),
            base_rent_per_unit=Decimal("28"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.02"),
            recovery_type="nnn",
            pct_rent_breakpoint=Decimal("15000000"), pct_rent_rate=Decimal("0.02"),
            projected_annual_sales_per_sf=Decimal("450"),
        ))
        session.add(Lease(
            id=uid(), suite_id=p2_suite_ids["Pad A"], tenant_id=tenants["chipotle"].id,
            lease_type="in_place", lease_start_date=date(2022, 6, 1), lease_end_date=date(2032, 5, 31),
            base_rent_per_unit=Decimal("35"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.03"),
            recovery_type="nnn",
        ))
        # Pad B: VACANT
        session.add(Lease(
            id=uid(), suite_id=p2_suite_ids["Inline 1"], tenant_id=tenants["allstate"].id,
            lease_type="in_place", lease_start_date=date(2023, 1, 1), lease_end_date=date(2028, 12, 31),
            base_rent_per_unit=Decimal("32"), rent_payment_frequency="annual",
            escalation_type="flat",
            recovery_type="modified_gross", expense_stop_per_sf=Decimal("8"),
        ))
        session.add(Lease(
            id=uid(), suite_id=p2_suite_ids["Inline 2"], tenant_id=tenants["cushman"].id,
            lease_type="in_place", lease_start_date=date(2024, 9, 1), lease_end_date=date(2029, 8, 31),
            base_rent_per_unit=Decimal("30"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.025"),
            recovery_type="nnn",
        ))

        # P2 Expenses
        for cat, desc, amt, gr in [
            ("real_estate_taxes", "Property Taxes", Decimal("425000"), Decimal("0.03")),
            ("insurance", "Insurance", Decimal("85000"), Decimal("0.03")),
            ("cam", "CAM", Decimal("340000"), Decimal("0.025")),
            ("utilities", "Utilities", Decimal("127500"), Decimal("0.03")),
        ]:
            session.add(PropertyExpense(
                id=uid(), property_id=p2_id, category=cat, description=desc,
                base_year_amount=amt, growth_rate_pct=gr, is_recoverable=True,
            ))
        session.add(PropertyExpense(
            id=uid(), property_id=p2_id, category="management_fee", description="Management",
            base_year_amount=Decimal("0"), growth_rate_pct=Decimal("0"),
            is_recoverable=False, is_pct_of_egi=True, pct_of_egi=Decimal("0.05"),
        ))

        # P2 Market Profile
        session.add(MarketLeasingProfile(
            id=uid(), property_id=p2_id, space_type="retail",
            description="Dallas Suburban Retail",
            market_rent_per_unit=Decimal("32"), rent_growth_rate_pct=Decimal("0.025"),
            new_lease_term_months=84, new_tenant_ti_per_sf=Decimal("30"),
            new_tenant_lc_pct=Decimal("0.05"), new_tenant_free_rent_months=3, downtime_months=4,
            renewal_probability=Decimal("0.60"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("10"), renewal_lc_pct=Decimal("0.02"),
            renewal_rent_adjustment_pct=Decimal("0.02"),
            general_vacancy_pct=Decimal("0.07"), credit_loss_pct=Decimal("0.02"),
        ))

        v2_id = uid()
        session.add(Valuation(
            id=v2_id, property_id=p2_id, name="Acquisition Model",
            description="Retail acquisition underwriting",
            discount_rate=Decimal("0.085"), exit_cap_rate=Decimal("0.07"),
            exit_costs_pct=Decimal("0.02"), capital_reserves_per_unit=Decimal("0.25"),
        ))

        print("  Created: Westfield Town Center (Retail, Dallas)")

        # ──────────────────────────────────────────────
        # PROPERTY 3: Pacific Gateway Industrial (Industrial, LA)
        # ──────────────────────────────────────────────
        p3_id = uid()
        p3 = Property(
            id=p3_id, name="Pacific Gateway Industrial",
            address_line1="2100 E. Carson Street", city="Los Angeles", state="CA", zip_code="90810",
            property_type="industrial", total_area=Decimal("175000"), area_unit="sf",
            year_built=2015, analysis_start_date=date(2025, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
        )
        session.add(p3)

        p3_suites = [
            ("Warehouse A", 1, Decimal("65000"), "industrial"),
            ("Warehouse B", 1, Decimal("50000"), "industrial"),
            ("Warehouse C", 1, Decimal("35000"), "industrial"),
            ("Flex Office", 2, Decimal("25000"), "office"),
        ]
        p3_suite_ids = {}
        for name, floor, area, stype in p3_suites:
            sid = uid()
            p3_suite_ids[name] = sid
            session.add(Suite(id=sid, property_id=p3_id, suite_name=name,
                              floor=floor, area=area, space_type=stype, is_available=True))

        session.add(Lease(
            id=uid(), suite_id=p3_suite_ids["Warehouse A"], tenant_id=tenants["amazon"].id,
            lease_type="in_place", lease_start_date=date(2023, 1, 1), lease_end_date=date(2032, 12, 31),
            base_rent_per_unit=Decimal("16.50"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.035"),
            recovery_type="nnn",
        ))
        session.add(Lease(
            id=uid(), suite_id=p3_suite_ids["Warehouse B"], tenant_id=tenants["fedex"].id,
            lease_type="in_place", lease_start_date=date(2022, 7, 1), lease_end_date=date(2029, 6, 30),
            base_rent_per_unit=Decimal("15"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.03"),
            recovery_type="nnn",
        ))
        session.add(Lease(
            id=uid(), suite_id=p3_suite_ids["Warehouse C"], tenant_id=tenants["deloitte"].id,
            lease_type="in_place", lease_start_date=date(2024, 3, 1), lease_end_date=date(2029, 2, 28),
            base_rent_per_unit=Decimal("14"), rent_payment_frequency="annual",
            escalation_type="cpi", cpi_floor=Decimal("0.02"), cpi_cap=Decimal("0.04"),
            recovery_type="nnn",
        ))
        session.add(Lease(
            id=uid(), suite_id=p3_suite_ids["Flex Office"], tenant_id=tenants["bloomberg"].id,
            lease_type="in_place", lease_start_date=date(2024, 1, 1), lease_end_date=date(2028, 12, 31),
            base_rent_per_unit=Decimal("28"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.025"),
            recovery_type="modified_gross", expense_stop_per_sf=Decimal("10"),
        ))

        for cat, desc, amt, gr in [
            ("real_estate_taxes", "Property Taxes", Decimal("437500"), Decimal("0.035")),
            ("insurance", "Insurance", Decimal("131250"), Decimal("0.025")),
            ("cam", "CAM", Decimal("262500"), Decimal("0.02")),
            ("utilities", "Utilities", Decimal("43750"), Decimal("0.03")),
        ]:
            session.add(PropertyExpense(
                id=uid(), property_id=p3_id, category=cat, description=desc,
                base_year_amount=amt, growth_rate_pct=gr, is_recoverable=True,
            ))
        session.add(PropertyExpense(
            id=uid(), property_id=p3_id, category="management_fee", description="Management",
            base_year_amount=Decimal("0"), growth_rate_pct=Decimal("0"),
            is_recoverable=False, is_pct_of_egi=True, pct_of_egi=Decimal("0.03"),
        ))

        # P3 Market Profiles (two space types)
        session.add(MarketLeasingProfile(
            id=uid(), property_id=p3_id, space_type="industrial",
            description="LA Industrial / Logistics",
            market_rent_per_unit=Decimal("17"), rent_growth_rate_pct=Decimal("0.03"),
            new_lease_term_months=120, new_tenant_ti_per_sf=Decimal("5"),
            new_tenant_lc_pct=Decimal("0.04"), new_tenant_free_rent_months=0, downtime_months=2,
            renewal_probability=Decimal("0.70"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("2.50"), renewal_lc_pct=Decimal("0.02"),
            renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0.03"), credit_loss_pct=Decimal("0.005"),
        ))
        session.add(MarketLeasingProfile(
            id=uid(), property_id=p3_id, space_type="office",
            description="Flex Office in Industrial Park",
            market_rent_per_unit=Decimal("30"), rent_growth_rate_pct=Decimal("0.03"),
            new_lease_term_months=60, new_tenant_ti_per_sf=Decimal("35"),
            new_tenant_lc_pct=Decimal("0.06"), new_tenant_free_rent_months=1, downtime_months=3,
            renewal_probability=Decimal("0.65"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("15"), renewal_lc_pct=Decimal("0.03"),
            renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0.05"), credit_loss_pct=Decimal("0.01"),
        ))

        v3_id = uid()
        session.add(Valuation(
            id=v3_id, property_id=p3_id, name="Hold Analysis",
            description="Long-term industrial hold with strong credit tenants",
            discount_rate=Decimal("0.07"), exit_cap_rate=Decimal("0.055"),
            exit_costs_pct=Decimal("0.02"), capital_reserves_per_unit=Decimal("0.15"),
        ))

        print("  Created: Pacific Gateway Industrial (Industrial, LA)")

        # ──────────────────────────────────────────────
        # PROPERTY 4: Meridian Tower (Mixed-Use, Chicago)
        # ──────────────────────────────────────────────
        p4_id = uid()
        p4 = Property(
            id=p4_id, name="Meridian Tower",
            address_line1="200 N. Michigan Avenue", city="Chicago", state="IL", zip_code="60601",
            property_type="mixed_use", total_area=Decimal("120000"), area_unit="sf",
            year_built=1998, analysis_start_date=date(2025, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
        )
        session.add(p4)

        p4_suites = [
            ("Ground Retail", 1, Decimal("15000"), "retail"),
            ("Suite 200", 2, Decimal("22000"), "office"),
            ("Suite 300", 3, Decimal("20000"), "office"),
            ("Suite 400", 4, Decimal("23000"), "office"),
            ("Suite 500", 5, Decimal("20000"), "office"),
            ("Suite 600", 6, Decimal("20000"), "office"),
        ]
        p4_suite_ids = {}
        for name, floor, area, stype in p4_suites:
            sid = uid()
            p4_suite_ids[name] = sid
            session.add(Suite(id=sid, property_id=p4_id, suite_name=name,
                              floor=floor, area=area, space_type=stype, is_available=True))

        session.add(Lease(
            id=uid(), suite_id=p4_suite_ids["Ground Retail"], tenant_id=tenants["chipotle"].id,
            lease_type="in_place", lease_start_date=date(2023, 6, 1), lease_end_date=date(2033, 5, 31),
            base_rent_per_unit=Decimal("42"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.03"),
            recovery_type="nnn",
        ))
        session.add(Lease(
            id=uid(), suite_id=p4_suite_ids["Suite 200"], tenant_id=tenants["goldman"].id,
            lease_type="in_place", lease_start_date=date(2023, 1, 1), lease_end_date=date(2030, 12, 31),
            base_rent_per_unit=Decimal("48"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.025"),
            recovery_type="base_year_stop", base_year=2023, base_year_stop_amount=Decimal("242000"),
        ))
        session.add(Lease(
            id=uid(), suite_id=p4_suite_ids["Suite 300"], tenant_id=tenants["kirkland"].id,
            lease_type="in_place", lease_start_date=date(2024, 4, 1), lease_end_date=date(2031, 3, 31),
            base_rent_per_unit=Decimal("52"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.03"),
            recovery_type="full_service_gross",
        ))
        # Suite 400: VACANT
        session.add(Lease(
            id=uid(), suite_id=p4_suite_ids["Suite 500"], tenant_id=tenants["allstate"].id,
            lease_type="in_place", lease_start_date=date(2022, 7, 1), lease_end_date=date(2027, 6, 30),
            base_rent_per_unit=Decimal("45"), rent_payment_frequency="annual",
            escalation_type="cpi", cpi_floor=Decimal("0.015"), cpi_cap=Decimal("0.035"),
            recovery_type="nnn",
        ))
        session.add(Lease(
            id=uid(), suite_id=p4_suite_ids["Suite 600"], tenant_id=tenants["cushman"].id,
            lease_type="in_place", lease_start_date=date(2024, 10, 1), lease_end_date=date(2029, 9, 30),
            base_rent_per_unit=Decimal("46"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.025"),
            recovery_type="nnn",
        ))

        for cat, desc, amt, gr in [
            ("real_estate_taxes", "Property Taxes", Decimal("840000"), Decimal("0.03")),
            ("insurance", "Insurance", Decimal("144000"), Decimal("0.025")),
            ("cam", "CAM", Decimal("480000"), Decimal("0.025")),
            ("utilities", "Utilities", Decimal("216000"), Decimal("0.03")),
        ]:
            session.add(PropertyExpense(
                id=uid(), property_id=p4_id, category=cat, description=desc,
                base_year_amount=amt, growth_rate_pct=gr, is_recoverable=True,
            ))
        session.add(PropertyExpense(
            id=uid(), property_id=p4_id, category="management_fee", description="Management",
            base_year_amount=Decimal("0"), growth_rate_pct=Decimal("0"),
            is_recoverable=False, is_pct_of_egi=True, pct_of_egi=Decimal("0.045"),
        ))

        session.add(MarketLeasingProfile(
            id=uid(), property_id=p4_id, space_type="retail",
            description="Chicago Ground Floor Retail",
            market_rent_per_unit=Decimal("45"), rent_growth_rate_pct=Decimal("0.025"),
            new_lease_term_months=84, new_tenant_ti_per_sf=Decimal("40"),
            new_tenant_lc_pct=Decimal("0.05"), new_tenant_free_rent_months=2, downtime_months=4,
            renewal_probability=Decimal("0.55"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("15"), renewal_lc_pct=Decimal("0.025"),
            renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0.08"), credit_loss_pct=Decimal("0.02"),
        ))
        session.add(MarketLeasingProfile(
            id=uid(), property_id=p4_id, space_type="office",
            description="Chicago Class B+ Office",
            market_rent_per_unit=Decimal("48"), rent_growth_rate_pct=Decimal("0.03"),
            new_lease_term_months=60, new_tenant_ti_per_sf=Decimal("40"),
            new_tenant_lc_pct=Decimal("0.06"), new_tenant_free_rent_months=1, downtime_months=3,
            renewal_probability=Decimal("0.65"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("20"), renewal_lc_pct=Decimal("0.03"),
            renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0.05"), credit_loss_pct=Decimal("0.01"),
        ))

        v4_id = uid()
        session.add(Valuation(
            id=v4_id, property_id=p4_id, name="Reposition Strategy",
            description="Mixed-use value-add with vacant suite lease-up",
            discount_rate=Decimal("0.0825"), exit_cap_rate=Decimal("0.0675"),
            exit_costs_pct=Decimal("0.02"), capital_reserves_per_unit=Decimal("0.30"),
        ))

        print("  Created: Meridian Tower (Mixed-Use, Chicago)")

        # ──────────────────────────────────────────────
        # PROPERTY 5: Harbor Point Business Center (Office, Boston)
        # ──────────────────────────────────────────────
        p5_id = uid()
        p5 = Property(
            id=p5_id, name="Harbor Point Business Center",
            address_line1="75 State Street", city="Boston", state="MA", zip_code="02109",
            property_type="office", total_area=Decimal("95000"), area_unit="sf",
            year_built=2010, analysis_start_date=date(2025, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
        )
        session.add(p5)

        p5_suites = [
            ("Suite 100", 1, Decimal("22000"), "office"),
            ("Suite 200", 2, Decimal("20000"), "office"),
            ("Suite 300", 3, Decimal("18000"), "office"),
            ("Suite 400", 4, Decimal("18000"), "office"),
            ("Suite 500", 5, Decimal("17000"), "office"),
        ]
        p5_suite_ids = {}
        for name, floor, area, stype in p5_suites:
            sid = uid()
            p5_suite_ids[name] = sid
            session.add(Suite(id=sid, property_id=p5_id, suite_name=name,
                              floor=floor, area=area, space_type=stype, is_available=True))

        session.add(Lease(
            id=uid(), suite_id=p5_suite_ids["Suite 100"], tenant_id=tenants["deloitte"].id,
            lease_type="in_place", lease_start_date=date(2023, 3, 1), lease_end_date=date(2030, 2, 28),
            base_rent_per_unit=Decimal("52"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.03"),
            recovery_type="nnn",
        ))
        session.add(Lease(
            id=uid(), suite_id=p5_suite_ids["Suite 200"], tenant_id=tenants["goldman"].id,
            lease_type="in_place", lease_start_date=date(2024, 1, 1), lease_end_date=date(2029, 12, 31),
            base_rent_per_unit=Decimal("58"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.025"),
            recovery_type="full_service_gross",
        ))
        session.add(Lease(
            id=uid(), suite_id=p5_suite_ids["Suite 300"], tenant_id=tenants["fedex"].id,
            lease_type="in_place", lease_start_date=date(2022, 6, 1), lease_end_date=date(2027, 5, 31),
            base_rent_per_unit=Decimal("48"), rent_payment_frequency="annual",
            escalation_type="flat",
            recovery_type="nnn",
        ))
        # Suite 400: VACANT
        session.add(Lease(
            id=uid(), suite_id=p5_suite_ids["Suite 500"], tenant_id=tenants["kirkland"].id,
            lease_type="in_place", lease_start_date=date(2024, 7, 1), lease_end_date=date(2031, 6, 30),
            base_rent_per_unit=Decimal("54"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.03"),
            recovery_type="nnn",
        ))

        for cat, desc, amt, gr in [
            ("real_estate_taxes", "Property Taxes", Decimal("760000"), Decimal("0.035")),
            ("insurance", "Insurance", Decimal("142500"), Decimal("0.03")),
            ("cam", "CAM", Decimal("380000"), Decimal("0.025")),
            ("utilities", "Utilities", Decimal("190000"), Decimal("0.03")),
        ]:
            session.add(PropertyExpense(
                id=uid(), property_id=p5_id, category=cat, description=desc,
                base_year_amount=amt, growth_rate_pct=gr, is_recoverable=True,
            ))
        session.add(PropertyExpense(
            id=uid(), property_id=p5_id, category="management_fee", description="Management",
            base_year_amount=Decimal("0"), growth_rate_pct=Decimal("0"),
            is_recoverable=False, is_pct_of_egi=True, pct_of_egi=Decimal("0.04"),
        ))

        session.add(MarketLeasingProfile(
            id=uid(), property_id=p5_id, space_type="office",
            description="Boston Class B+ Office",
            market_rent_per_unit=Decimal("52"), rent_growth_rate_pct=Decimal("0.03"),
            new_lease_term_months=60, new_tenant_ti_per_sf=Decimal("40"),
            new_tenant_lc_pct=Decimal("0.06"), new_tenant_free_rent_months=1, downtime_months=3,
            renewal_probability=Decimal("0.65"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("18"), renewal_lc_pct=Decimal("0.03"),
            renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0.05"), credit_loss_pct=Decimal("0.01"),
        ))

        v5_id = uid()
        session.add(Valuation(
            id=v5_id, property_id=p5_id, name="Investment Hold",
            description="Class B+ office core hold analysis",
            discount_rate=Decimal("0.0775"), exit_cap_rate=Decimal("0.0625"),
            exit_costs_pct=Decimal("0.02"), capital_reserves_per_unit=Decimal("0.25"),
        ))

        print("  Created: Harbor Point Business Center (Office, Boston)")

        # ──────────────────────────────────────────────
        # PROPERTY 6: Stabilized Gross-Up Demo (Office, Atlanta)
        # ──────────────────────────────────────────────
        p6_id = uid()
        p6 = Property(
            id=p6_id, name="Peachtree Plaza Office",
            address_line1="1200 Peachtree Street NE", city="Atlanta", state="GA", zip_code="30309",
            property_type="office", total_area=Decimal("60000"), area_unit="sf",
            year_built=2006, analysis_start_date=date(2025, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
        )
        session.add(p6)

        p6_suites = [
            ("Suite 100", 1, Decimal("15000"), "office"),
            ("Suite 200", 2, Decimal("15000"), "office"),
            ("Suite 300", 3, Decimal("15000"), "office"),
            ("Suite 400", 4, Decimal("15000"), "office"),
        ]
        p6_suite_ids = {}
        for name, floor, area, stype in p6_suites:
            sid = uid()
            p6_suite_ids[name] = sid
            session.add(Suite(
                id=sid, property_id=p6_id, suite_name=name, floor=floor, area=area,
                space_type=stype, is_available=True
            ))

        # 2 leased suites + 2 vacant suites to demonstrate occupancy-driven gross-up.
        session.add(Lease(
            id=uid(), suite_id=p6_suite_ids["Suite 100"], tenant_id=tenants["goldman"].id,
            lease_type="in_place", lease_start_date=date(2023, 1, 1), lease_end_date=date(2030, 12, 31),
            base_rent_per_unit=Decimal("36"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct_annual=Decimal("0.025"),
            recovery_type="nnn",
        ))
        session.add(Lease(
            id=uid(), suite_id=p6_suite_ids["Suite 200"], tenant_id=tenants["deloitte"].id,
            lease_type="in_place", lease_start_date=date(2024, 4, 1), lease_end_date=date(2029, 3, 31),
            base_rent_per_unit=Decimal("34"), rent_payment_frequency="annual",
            escalation_type="flat",
            recovery_type="modified_gross", expense_stop_per_sf=Decimal("11"),
        ))
        # Suite 300 + Suite 400 intentionally vacant

        p6_expenses = [
            ("real_estate_taxes", "Property Taxes", Decimal("540000"), Decimal("0.03"), True, False, None),
            ("insurance", "Insurance", Decimal("108000"), Decimal("0.025"), True, False, None),
            # Variable expenses flagged for gross-up
            ("cam", "Common Area Maintenance", Decimal("360000"), Decimal("0.03"), True, True, Decimal("0.95")),
            ("utilities", "Utilities", Decimal("240000"), Decimal("0.03"), True, True, Decimal("0.95")),
            ("repairs_maintenance", "Repairs & Maintenance", Decimal("150000"), Decimal("0.025"), True, False, None),
        ]
        for cat, desc, amt, gr, rec, gross_up, gross_up_target in p6_expenses:
            session.add(PropertyExpense(
                id=uid(), property_id=p6_id, category=cat, description=desc,
                base_year_amount=amt, growth_rate_pct=gr, is_recoverable=rec,
                is_gross_up_eligible=gross_up, gross_up_vacancy_pct=gross_up_target,
            ))
        session.add(PropertyExpense(
            id=uid(), property_id=p6_id, category="management_fee", description="Management",
            base_year_amount=Decimal("0"), growth_rate_pct=Decimal("0"),
            is_recoverable=False, is_pct_of_egi=True, pct_of_egi=Decimal("0.04"),
        ))

        session.add(MarketLeasingProfile(
            id=uid(), property_id=p6_id, space_type="office",
            description="Atlanta Class A- Office",
            market_rent_per_unit=Decimal("35"), rent_growth_rate_pct=Decimal("0.025"),
            new_lease_term_months=60, new_tenant_ti_per_sf=Decimal("32"),
            new_tenant_lc_pct=Decimal("0.055"), new_tenant_free_rent_months=2, downtime_months=5,
            renewal_probability=Decimal("0.60"), renewal_lease_term_months=60,
            renewal_ti_per_sf=Decimal("16"), renewal_lc_pct=Decimal("0.03"),
            renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0.10"), credit_loss_pct=Decimal("0.015"),
        ))

        v6_id = uid()
        session.add(Valuation(
            id=v6_id, property_id=p6_id, name="Gross-Up Demonstration Case",
            description="Office underwriting example with valuation-level stabilized gross-up enabled",
            discount_rate=Decimal("0.0825"), exit_cap_rate=Decimal("0.0675"),
            exit_costs_pct=Decimal("0.02"), capital_reserves_per_unit=Decimal("0.25"),
            apply_stabilized_gross_up=True, stabilized_occupancy_pct=Decimal("0.95"),
        ))

        print("  Created: Peachtree Plaza Office (Office, Atlanta, Gross-Up Demo)")

        # ──────────────────────────────────────────────
        # PROPERTY 7 — Marina (Harborview Marina, Annapolis MD)
        # ──────────────────────────────────────────────
        # Marina properties use the marina valuation engine (slip-based).
        # The engine generates revenue, expenses, and cash flows from
        # slip inventory rather than lease-based tenants. Setting area_unit
        # = "unit" tells the marina service layer that total_area = slip count.
        p7_id = uid()
        p7 = Property(
            id=p7_id, name="Harborview Marina",
            address_line1="200 Compromise St", city="Annapolis", state="MD", zip_code="21401",
            property_type="marina", total_area=Decimal("390"), area_unit="unit",
            year_built=1998, analysis_start_date=date(2026, 1, 1),
            analysis_period_months=84, fiscal_year_end_month=12,
        )
        session.add(p7)

        # Marina properties don't use suites/leases/tenants in the DB — the marina
        # engine models slip classes, demand, and ancillary revenue internally.
        # We only need a valuation record so the /run endpoint picks up the marina path.
        import json as _json
        marina_assumptions = {
            "slip_classes": [
                {
                    "name": "Wet Slips", "kind": "wet_slip", "length_class": "30-45 ft",
                    "utility_service_level": "fifty_amp", "count": 234,
                    "annual_contract_share": "0.60", "seasonal_contract_share": "0.20",
                    "transient_share": "0.20", "annual_contract_rate": "7900",
                    "seasonal_contract_rate": "4300", "transient_daily_rate": "62",
                    "utility_fee_monthly": "45", "utility_fee_transient_daily": "6",
                    "repair_service_revenue_per_occupied_day": "2.8",
                    "retail_fnb_revenue_per_occupied_day": "1.6",
                    "storage_fee_per_month": "18", "launch_fee_per_transient_arrival": "12",
                    "base_annual_occupancy": "0.94", "base_seasonal_occupancy": "0.78",
                    "base_transient_capture": "0.55",
                },
                {
                    "name": "Dry Stack", "kind": "dry_stack", "length_class": "25-35 ft",
                    "utility_service_level": "water_only", "count": 97,
                    "annual_contract_share": "0.45", "seasonal_contract_share": "0.20",
                    "transient_share": "0.35", "annual_contract_rate": "5200",
                    "seasonal_contract_rate": "2900", "transient_daily_rate": "44",
                    "utility_fee_monthly": "16", "utility_fee_transient_daily": "2",
                    "repair_service_revenue_per_occupied_day": "2.0",
                    "retail_fnb_revenue_per_occupied_day": "1.0",
                    "storage_fee_per_month": "14", "launch_fee_per_transient_arrival": "8",
                    "base_annual_occupancy": "0.91", "base_seasonal_occupancy": "0.72",
                    "base_transient_capture": "0.60",
                },
                {
                    "name": "Moorings", "kind": "mooring", "length_class": "20-35 ft",
                    "utility_service_level": "none", "count": 59,
                    "annual_contract_share": "0.65", "seasonal_contract_share": "0.10",
                    "transient_share": "0.25", "annual_contract_rate": "2800",
                    "seasonal_contract_rate": "1700", "transient_daily_rate": "26",
                    "utility_fee_monthly": "0", "utility_fee_transient_daily": "0",
                    "repair_service_revenue_per_occupied_day": "0.8",
                    "retail_fnb_revenue_per_occupied_day": "0.6",
                    "storage_fee_per_month": "6", "launch_fee_per_transient_arrival": "4",
                    "base_annual_occupancy": "0.89", "base_seasonal_occupancy": "0.65",
                    "base_transient_capture": "0.50",
                },
            ],
            "demand": {
                "annual_churn_pct": "0.12", "seasonal_churn_pct": "0.16", "seasonal_replacement_pct": "0.50",
                "waitlist_start_count": "31", "waitlist_conversion_pct": "0.55",
                "waitlist_new_demand_per_year": "12",
                "annual_reprice_growth_pct": "0.03", "seasonal_reprice_growth_pct": "0.035",
                "transient_reprice_growth_pct": "0.03", "ancillary_growth_pct": "0.03",
                "vacancy_collection_loss_pct": "0.02", "management_fee_pct": "0.04",
            },
            "additional_revenue_lines": [
                {"name": "Boat Club Memberships", "annual_fixed": "120000", "per_occupied_day": "0", "growth_pct": "0.03"},
                {"name": "Parking & Trailer Storage", "annual_fixed": "85000", "per_occupied_day": "0", "growth_pct": "0.02"},
                {"name": "Ship Store & Chandlery", "annual_fixed": "0", "per_occupied_day": "1.50", "growth_pct": "0.03"},
            ],
            "operating_cost_lines": [
                {"name": "Dock Labor", "annual_fixed": "936000", "per_occupied_day": "2.0", "growth_pct": "0.03"},
                {"name": "Utilities", "annual_fixed": "429000", "per_occupied_day": "0.75", "growth_pct": "0.03"},
                {"name": "Insurance & Environmental", "annual_fixed": "253500", "per_occupied_day": "0.0", "growth_pct": "0.045"},
            ],
            "cyclical_costs": [
                {"name": "Dredging", "base_amount": "585000", "first_year": 3, "every_n_years": 4, "growth_pct": "0.03", "treat_as_capex": True},
            ],
            "legal_tenure": {
                "tenure_type": "fee_simple",
                "annual_submerged_land_lease": "148200",
                "annual_permit_concession_fees": "93600",
            },
            "capex_lifecycle": [
                {"name": "Floating Docks", "asset_type": "floating_docks", "base_amount": "468000", "first_year": 4, "every_n_years": 5, "growth_pct": "0.03"},
            ],
            "fuel_dock": {"enabled": True, "fuel_sales_per_occupied_day": "25", "fuel_margin_pct": "0.22"},
            "valuation": {
                "hold_years": 7, "terminal_noi_growth_pct": "0.02",
                "dock_replacement_reserve_per_slip_year": "220", "reserve_growth_pct": "0.03",
                "initial_purchase_price": "23400000",
            },
        }

        v7_id = uid()
        session.add(Valuation(
            id=v7_id, property_id=p7_id, name="Marina Base Case — 7yr Hold",
            description=(
                "390-slip marina: 234 wet slips, 97 dry stack, 59 moorings. "
                "Submerged-land lease + permits. Debt: $12.5M at 6.75%, 25yr amort, "
                "7yr term, 12mo IO. Fee-simple with submerged-land and permit costs."
            ),
            discount_rate=Decimal("0.095"), exit_cap_rate=Decimal("0.0825"),
            exit_costs_pct=Decimal("0.02"),
            use_mid_year_convention=True,
            capital_reserves_per_unit=Decimal("220"),
            loan_amount=Decimal("12500000"),
            interest_rate=Decimal("0.0675"),
            amortization_months=300,
            loan_term_months=84,
            io_period_months=12,
        ))
        p7.marina_assumptions_json = _json.dumps(marina_assumptions)  # moved onto its first valuation below

        print("  Created: Harborview Marina (Marina, Annapolis, 390 slips)")

        # ──────────────────────────────────────────────
        # PROPERTY 8 — Seniors Housing (Brookdale Sunrise, Scottsdale AZ)
        # ──────────────────────────────────────────────
        # Seniors housing uses the seniors_housing valuation engine.
        # Like marina, it's a going-concern model — revenue is driven by
        # monthly fees, care levels, and census rather than traditional leases.
        p8_id = uid()
        p8 = Property(
            id=p8_id, name="Brookdale Sunrise Senior Living",
            address_line1="8700 E. Pinnacle Peak Road", city="Scottsdale", state="AZ", zip_code="85255",
            property_type="seniors_housing", total_area=Decimal("134"), area_unit="unit",
            year_built=2012, analysis_start_date=date(2026, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
        )
        session.add(p8)

        import json as _json2
        sh_assumptions = {
            "community_name": "Brookdale Sunrise Senior Living",
            "unit_types": [
                # ── Independent Living ──
                {
                    "name": "IL Studio",
                    "acuity": "independent_living",
                    "unit_type": "studio",
                    "count": 12,
                    "avg_sf": "450",
                    "monthly_base_fee": "2800",
                    "second_person_fee_monthly": "700",
                    "second_person_pct": "0.15",
                    "community_fee": "2800",
                    "avg_length_of_stay_months": "30",
                    "stabilized_occupancy": "0.93",
                    "annual_turnover_rate": "0.25",
                },
                {
                    "name": "IL 1-Bedroom",
                    "acuity": "independent_living",
                    "unit_type": "one_br",
                    "count": 20,
                    "avg_sf": "700",
                    "monthly_base_fee": "3400",
                    "second_person_fee_monthly": "800",
                    "second_person_pct": "0.30",
                    "community_fee": "3400",
                    "avg_length_of_stay_months": "28",
                    "stabilized_occupancy": "0.92",
                    "annual_turnover_rate": "0.22",
                },
                {
                    "name": "IL 2-Bedroom",
                    "acuity": "independent_living",
                    "unit_type": "two_br",
                    "count": 8,
                    "avg_sf": "1050",
                    "monthly_base_fee": "4200",
                    "second_person_fee_monthly": "900",
                    "second_person_pct": "0.45",
                    "community_fee": "4200",
                    "avg_length_of_stay_months": "32",
                    "stabilized_occupancy": "0.90",
                    "annual_turnover_rate": "0.20",
                },
                # ── Assisted Living ──
                {
                    "name": "AL Studio",
                    "acuity": "assisted_living",
                    "unit_type": "studio",
                    "count": 32,
                    "avg_sf": "340",
                    "monthly_base_fee": "5200",
                    "second_person_fee_monthly": "1200",
                    "second_person_pct": "0.08",
                    "community_fee": "5200",
                    "avg_length_of_stay_months": "22",
                    "stabilized_occupancy": "0.88",
                    "annual_turnover_rate": "0.45",
                    "care_level_tiers": [
                        {"name": "Level 1 — Minimal", "monthly_surcharge": "450", "pct_of_residents": "0.25"},
                        {"name": "Level 2 — Moderate", "monthly_surcharge": "1100", "pct_of_residents": "0.40"},
                        {"name": "Level 3 — High", "monthly_surcharge": "2000", "pct_of_residents": "0.25"},
                        {"name": "Level 4 — Extensive", "monthly_surcharge": "3000", "pct_of_residents": "0.10"},
                    ],
                },
                {
                    "name": "AL 1-Bedroom",
                    "acuity": "assisted_living",
                    "unit_type": "one_br",
                    "count": 18,
                    "avg_sf": "520",
                    "monthly_base_fee": "6100",
                    "second_person_fee_monthly": "1300",
                    "second_person_pct": "0.15",
                    "community_fee": "6100",
                    "avg_length_of_stay_months": "24",
                    "stabilized_occupancy": "0.90",
                    "annual_turnover_rate": "0.42",
                    "care_level_tiers": [
                        {"name": "Level 1 — Minimal", "monthly_surcharge": "450", "pct_of_residents": "0.30"},
                        {"name": "Level 2 — Moderate", "monthly_surcharge": "1100", "pct_of_residents": "0.40"},
                        {"name": "Level 3 — High", "monthly_surcharge": "2000", "pct_of_residents": "0.20"},
                        {"name": "Level 4 — Extensive", "monthly_surcharge": "3000", "pct_of_residents": "0.10"},
                    ],
                },
                # ── Memory Care ──
                {
                    "name": "MC Private Room",
                    "acuity": "memory_care",
                    "unit_type": "private",
                    "count": 20,
                    "avg_sf": "300",
                    "monthly_base_fee": "7200",
                    "community_fee": "7200",
                    "avg_length_of_stay_months": "20",
                    "stabilized_occupancy": "0.86",
                    "annual_turnover_rate": "0.38",
                    "care_level_tiers": [
                        {"name": "MC Standard", "monthly_surcharge": "1600", "pct_of_residents": "0.55"},
                        {"name": "MC High Acuity", "monthly_surcharge": "2800", "pct_of_residents": "0.45"},
                    ],
                },
                {
                    "name": "MC Semi-Private",
                    "acuity": "memory_care",
                    "unit_type": "semi_private",
                    "count": 8,
                    "avg_sf": "220",
                    "monthly_base_fee": "5800",
                    "community_fee": "5800",
                    "avg_length_of_stay_months": "18",
                    "stabilized_occupancy": "0.82",
                    "annual_turnover_rate": "0.42",
                    "care_level_tiers": [
                        {"name": "MC Standard", "monthly_surcharge": "1600", "pct_of_residents": "0.50"},
                        {"name": "MC High Acuity", "monthly_surcharge": "2800", "pct_of_residents": "0.50"},
                    ],
                },
                # ── Skilled Nursing ──
                {
                    "name": "SNF Private Room",
                    "acuity": "skilled_nursing",
                    "unit_type": "private",
                    "count": 16,
                    "avg_sf": "250",
                    "monthly_base_fee": "0",
                    "stabilized_occupancy": "0.84",
                    "annual_turnover_rate": "0.30",
                },
            ],
            "snf_payer_mix": [
                {"payer": "medicare", "pct_of_days": "0.18", "daily_rate": "560", "annual_rate_growth": "0.02"},
                {"payer": "medicaid", "pct_of_days": "0.52", "daily_rate": "265", "annual_rate_growth": "0.015"},
                {"payer": "private_pay", "pct_of_days": "0.18", "daily_rate": "380", "annual_rate_growth": "0.035"},
                {"payer": "medicare_advantage", "pct_of_days": "0.08", "daily_rate": "420", "annual_rate_growth": "0.02"},
                {"payer": "insurance", "pct_of_days": "0.04", "daily_rate": "400", "annual_rate_growth": "0.025"},
            ],
            "ancillary_revenue": [
                {"name": "Respite / Short-Stay Care", "annual_fixed": "72000", "growth_pct": "0.03"},
                {"name": "Beauty Salon & Barber", "per_occupied_unit_month": "22", "growth_pct": "0.02"},
                {"name": "Guest Meals & Catering", "annual_fixed": "24000", "growth_pct": "0.02"},
                {"name": "Transportation Services", "per_occupied_unit_month": "15", "growth_pct": "0.03",
                 "applies_to_acuity": ["assisted_living", "memory_care"]},
                {"name": "Personal Laundry", "per_occupied_unit_month": "12", "growth_pct": "0.02",
                 "applies_to_acuity": ["assisted_living", "memory_care", "skilled_nursing"]},
                {"name": "Medication Management", "per_occupied_unit_month": "45", "growth_pct": "0.03",
                 "applies_to_acuity": ["assisted_living"]},
                {"name": "Therapy Services (PT/OT)", "annual_fixed": "36000", "growth_pct": "0.03",
                 "applies_to_acuity": ["skilled_nursing"]},
            ],
            "expenses": [
                # ── Labor ──
                {"name": "Nursing & Caregiving Staff", "category": "labor",
                 "annual_fixed": "920000", "per_occupied_unit_month": "1950",
                 "growth_pct": "0.035",
                 "applies_to_acuity": ["assisted_living", "memory_care"]},
                {"name": "Skilled Nursing Staff (RN/LPN/CNA)", "category": "labor",
                 "annual_fixed": "480000", "per_occupied_unit_month": "3200",
                 "growth_pct": "0.035",
                 "applies_to_acuity": ["skilled_nursing"]},
                {"name": "Dietary & Kitchen Staff", "category": "labor",
                 "annual_fixed": "340000", "growth_pct": "0.03"},
                {"name": "Housekeeping & Laundry", "category": "labor",
                 "annual_fixed": "210000", "growth_pct": "0.03"},
                {"name": "Maintenance & Groundskeeping", "category": "labor",
                 "annual_fixed": "165000", "growth_pct": "0.03"},
                {"name": "Activities & Programming", "category": "labor",
                 "annual_fixed": "110000", "growth_pct": "0.025"},
                {"name": "Executive Director & Admin", "category": "labor",
                 "annual_fixed": "480000", "growth_pct": "0.03"},
                {"name": "Receptionist & Concierge", "category": "labor",
                 "annual_fixed": "95000", "growth_pct": "0.025"},
                # ── Food ──
                {"name": "Raw Food & Dietary Costs", "category": "food",
                 "per_occupied_unit_month": "380", "growth_pct": "0.035"},
                # ── Insurance ──
                {"name": "General Liability Insurance", "category": "insurance",
                 "annual_fixed": "135000", "growth_pct": "0.04"},
                {"name": "Professional Liability Insurance", "category": "insurance",
                 "annual_fixed": "110000", "growth_pct": "0.045"},
                {"name": "Workers Compensation", "category": "insurance",
                 "annual_fixed": "185000", "growth_pct": "0.035"},
                # ── Marketing ──
                {"name": "Marketing & Advertising", "category": "marketing",
                 "annual_fixed": "195000", "growth_pct": "0.03"},
                {"name": "Move-In Incentives & Referral Fees", "category": "marketing",
                 "annual_fixed": "48000", "growth_pct": "0.02"},
                # ── Utilities ──
                {"name": "Electric, Gas & Water", "category": "utilities",
                 "annual_fixed": "185000", "per_occupied_unit_month": "85", "growth_pct": "0.03"},
                {"name": "Cable, Internet & Phone", "category": "utilities",
                 "annual_fixed": "62000", "growth_pct": "0.02"},
                # ── Property Tax ──
                {"name": "Property Taxes", "category": "property_tax",
                 "annual_fixed": "310000", "growth_pct": "0.025"},
                # ── Medical Supplies ──
                {"name": "Medical Supplies & Equipment", "category": "medical_supplies",
                 "per_occupied_unit_month": "130", "growth_pct": "0.03",
                 "applies_to_acuity": ["assisted_living", "memory_care"]},
                {"name": "SNF Medical Supplies & Pharmacy", "category": "medical_supplies",
                 "per_occupied_unit_month": "280", "growth_pct": "0.03",
                 "applies_to_acuity": ["skilled_nursing"]},
                # ── Management Fee ──
                {"name": "Management Fee (5% of Revenue)", "category": "management_fee",
                 "pct_of_revenue": "0.05"},
                # ── Other ──
                {"name": "Corporate Allocations (IT, HR, Legal)", "category": "other",
                 "annual_fixed": "120000", "growth_pct": "0.025"},
                {"name": "Licensing & Regulatory Compliance", "category": "other",
                 "annual_fixed": "45000", "growth_pct": "0.03"},
            ],
            "capex": [
                {"name": "Capital Reserves", "annual_per_unit": "425", "growth_pct": "0.03"},
                {"name": "FF&E Replacement", "annual_fixed": "65000", "growth_pct": "0.025"},
                {"name": "Life Safety & ADA Compliance", "annual_fixed": "22000", "growth_pct": "0.03"},
            ],
            "valuation": {
                "hold_years": 10,
                "discount_rate": "0.09",
                "exit_cap_rate": "0.075",
                "exit_costs_pct": "0.02",
                "use_mid_year_convention": True,
                "terminal_noi_growth_pct": "0.02",
                "fee_growth_rate": "0.04",
                "expense_growth_rate": "0.035",
                "initial_purchase_price": "38500000",
            },
        }

        v8_id = uid()
        session.add(Valuation(
            id=v8_id, property_id=p8_id, name="Seniors Housing Base Case — 10yr Hold",
            description=(
                "134-bed CCRC: 40 IL, 50 AL (4 care tiers), 28 MC, 16 SNF. "
                "Full payer mix (Medicare/Medicaid/Private). "
                "4% annual fee growth, 3.5% expense growth. "
                "Going-concern valuation at 7.5% exit cap."
            ),
            discount_rate=Decimal("0.09"), exit_cap_rate=Decimal("0.075"),
            exit_costs_pct=Decimal("0.02"),
            use_mid_year_convention=True,
            capital_reserves_per_unit=Decimal("425"),
        ))
        p8.seniors_housing_assumptions_json = _json2.dumps(sh_assumptions)  # moved onto its first valuation below

        print("  Created: Brookdale Sunrise Senior Living (Seniors Housing, Scottsdale, 134 beds)")

        # ──────────────────────────────────────────────
        # PROPERTY 9 — Self Storage (Prairie Lock Storage, Overland Park KS)
        # ──────────────────────────────────────────────
        # Valued from its unit mix: street vs in-place rates, churn, rate increases on
        # existing customers (ECRI) and tenant protection income.
        storage_units = [
            # name, SF, climate controlled, access, count, occupied, in-place $/mo, street $/mo
            ("5x5 CC", 25, True, "interior", 120, 108, 62, 55),
            ("5x10 CC", 50, True, "interior", 180, 164, 96, 85),
            ("10x10 CC", 100, True, "interior", 160, 146, 162, 145),
            ("10x10 drive-up", 100, False, "drive_up", 80, 72, 131, 120),
            ("10x15 drive-up", 150, False, "drive_up", 60, 54, 165, 150),
            ("10x20 drive-up", 200, False, "drive_up", 50, 45, 205, 185),
            ("10x30 drive-up", 300, False, "drive_up", 40, 35, 285, 260),
            ("RV parking", 400, False, "parking", 20, 18, 125, 120),
        ]
        storage_model = {
            "unit_types": [
                {"name": n, "sf_per_unit": sf, "climate_controlled": cc, "access": access, "count": count,
                 "occupied_units": occ, "in_place_rate": rate, "street_rate": street, "stabilized_occupancy": "0.90"}
                for n, sf, cc, access, count, occ, rate, street in storage_units
            ],
            "street_rate_growth_pct": "0.03",
            "churn": {"monthly_move_out_pct": "0.045"},
            "ecri": {"enabled": True, "first_after_months": 6, "interval_months": 12, "increase_pct": "0.08",
                     "extra_move_out_pct": "0.04"},
            "concessions": {"first_month_discount_pct": "0.5"},
            "credit_loss_pct": "0.015",
            "ancillary_lines": [
                {"name": "Tenant protection", "basis": "per_occupied_unit_month", "amount": "12",
                 "participation_pct": "0.65", "growth_pct": "0.02"},
                {"name": "Admin fees", "basis": "per_move_in", "amount": "25"},
                {"name": "Late fees", "basis": "pct_of_rental", "amount": "0.015"},
                {"name": "Retail and truck rental", "basis": "annual_fixed", "amount": "18000", "growth_pct": "0.02"},
            ],
        }
        p9_id = uid()
        p9 = Property(
            id=p9_id, name="Prairie Lock Storage",
            address_line1="11950 W. 135th Street", city="Overland Park", state="KS", zip_code="66221",
            property_type="self_storage", total_area=Decimal("75000"), area_unit="sf",
            year_built=2016, analysis_start_date=date(2026, 1, 1),
            analysis_period_months=120, fiscal_year_end_month=12,
            self_storage_assumptions_json=_json2.dumps(storage_model),
        )
        session.add(p9)
        for category, desc, amount, growth, variable in [
            ("payroll", "Site managers and relief", "140000", "0.035", "0"),
            ("real_estate_taxes", "Johnson County taxes", "105000", "0.025", "0"),
            ("insurance", "Property and liability", "32000", "0.04", "0"),
            ("utilities", "Electric (climate control), water", "38000", "0.03", "0.3"),
            ("marketing", "Online search and listings", "30000", "0.03", "0"),
            ("repairs_maintenance", "Doors, gates, paving", "24000", "0.03", "0"),
            ("general_admin", "Software, office, bank", "18000", "0.03", "0"),
        ]:
            session.add(PropertyExpense(
                id=uid(), property_id=p9_id, category=category, description=desc,
                base_year_amount=Decimal(amount), growth_rate_pct=Decimal(growth),
                is_recoverable=False, variable_pct=Decimal(variable),
            ))
        for category, desc, pct in [("management_fee", "Third-party management", "0.06"),
                                    ("card_fees", "Credit card processing", "0.02")]:
            session.add(PropertyExpense(
                id=uid(), property_id=p9_id, category=category, description=desc,
                base_year_amount=Decimal(0), growth_rate_pct=Decimal(0), is_recoverable=False,
                is_pct_of_egi=True, pct_of_egi=Decimal(pct),
            ))
        v9_id = uid()
        session.add(Valuation(
            id=v9_id, property_id=p9_id, name="Self Storage Base Case — 10yr Hold",
            description="710 units / 75,000 SF, 90% occupied. 8% ECRI, 4.5% monthly move-outs, 3% street growth.",
            discount_rate=Decimal("0.085"), exit_cap_rate=Decimal("0.0625"),
            exit_costs_pct=Decimal("0.02"), capital_reserves_per_unit=Decimal("0.15"),
        ))
        print("  Created: Prairie Lock Storage (Self Storage, Overland Park, 710 units)")

        # Commit all data
        # Each valuation owns its model: give each property's rows, dates and operating model
        # to its first valuation; a tenant leasing in several properties gets a copy in each
        pending = list(session.new)
        first_valuation = {}
        for obj in pending:
            if isinstance(obj, Valuation):
                first_valuation.setdefault(obj.property_id, obj)
        props = {o.id: o for o in pending if isinstance(o, Property)}
        for prop_id, v in first_valuation.items():
            prop = props[prop_id]
            v.analysis_start_date_override = v.analysis_start_date_override or prop.analysis_start_date
            if prop.property_type not in ("marina", "seniors_housing"):  # their model's hold_years applies
                v.analysis_period_months_override = v.analysis_period_months_override or prop.analysis_period_months
            for column in ("marina_assumptions_json", "seniors_housing_assumptions_json",
                           "self_storage_assumptions_json"):
                setattr(v, column, getattr(v, column) or getattr(prop, column))
        owned = (Suite, PropertyExpense, MarketLeasingProfile)
        for obj in pending:
            if isinstance(obj, owned):
                obj.valuation_id = first_valuation[obj.property_id].id
        suites = {o.id: o for o in pending if isinstance(o, Suite)}
        tenant_rows = {o.id: o for o in pending if isinstance(o, Tenant)}
        copies = {}
        for lease in [o for o in pending if isinstance(o, Lease) and o.tenant_id]:
            suite = suites[lease.suite_id]
            tenant = tenant_rows[lease.tenant_id]
            if tenant.valuation_id in (None, suite.valuation_id):
                tenant.property_id, tenant.valuation_id = suite.property_id, suite.valuation_id
                continue
            key = (tenant.id, suite.valuation_id)
            if key not in copies:
                copies[key] = Tenant(id=uid(), name=tenant.name, credit_rating=tenant.credit_rating,
                                     industry=tenant.industry, property_id=suite.property_id,
                                     valuation_id=suite.valuation_id)
                session.add(copies[key])
            lease.tenant_id = copies[key].id
        for tenant in tenant_rows.values():
            if tenant.valuation_id is None:  # leases nothing
                session.expunge(tenant)
        await session.commit()
        print("\nAll data committed. Running valuations...")

        # ──────────────────────────────────────────────
        # RUN VALUATIONS
        # ──────────────────────────────────────────────
        valuation_ids = [v1_id, v2_id, v3_id, v4_id, v5_id, v6_id, v7_id, v8_id, v9_id]
        for vid in valuation_ids:
            try:
                service = ValuationService(session)
                result = await service.execute_valuation(vid)
                npv = result.key_metrics.npv if result.key_metrics else "N/A"
                irr = result.key_metrics.irr if result.key_metrics else "N/A"
                print(f"  Valuation {vid[:8]}... → NPV: ${npv:,.0f}  IRR: {float(irr)*100:.2f}%"
                      if result.key_metrics and irr != "N/A"
                      else f"  Valuation {vid[:8]}... → completed")
            except Exception as e:
                print(f"  Valuation {vid[:8]}... → FAILED: {e}")

        print("\nDone! Start the server with: uvicorn src.main:app --reload")
        print("Then open http://localhost:8000 in your browser.")


if __name__ == "__main__":
    asyncio.run(seed())
