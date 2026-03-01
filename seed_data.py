"""
Seed example data for OpenDCF — Commercial Real Estate Valuation Engine.

Usage:
    python seed_data.py

Creates 5 example properties with realistic tenants, leases, expenses,
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

        # Commit all data
        await session.commit()
        print("\nAll data committed. Running valuations...")

        # ──────────────────────────────────────────────
        # RUN VALUATIONS
        # ──────────────────────────────────────────────
        valuation_ids = [v1_id, v2_id, v3_id, v4_id, v5_id]
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
