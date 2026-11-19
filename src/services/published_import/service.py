"""
Bulk import: parse a workbook into a previewable payload, then commit it as
properties (with suites, tenants, leases, market profiles, expenses, other
income, capital projects and a valuation), optional portfolio membership, and
assumption profiles.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.engine.date_utils import add_months, start_of_month
from src.models.capital import PropertyCapitalProject
from src.models.expense import PropertyExpense
from src.models.lease import FreeRentPeriod, Lease, RentStep, Tenant
from src.models.loan import MortgageLoan
from src.models.market import MarketLeasingProfile
from src.models.other_income import PropertyOtherIncome
from src.models.portfolio import AssumptionProfile, ImportJob, Portfolio
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.schemas.imports import (
    ImportCommitRequest,
    ImportedLoan,
    ImportedProperty,
    ImportJobRead,
    ImportOptions,
    ImportPayload,
    LoanPreview,
    PropertyPreview,
    SheetReport,
)
from src.services.published_import.mapper import ImportMapper
from src.services.published_import.workbook import read_workbook

# Used when a workbook has no discount / exit cap; flagged in warnings
_DEFAULT_DISCOUNT = Decimal("0.08")
_DEFAULT_EXIT_CAP = Decimal("0.065")


def _preview(p: ImportedProperty) -> PropertyPreview:
    return PropertyPreview(
        external_id=p.external_id,
        name=p.name,
        property_type=p.property_type,
        market=p.market,
        total_area=p.total_area,
        suites=len(p.suites),
        leases=len(p.leases),
        market_profiles=len(p.market_profiles),
        expenses=len(p.expenses),
        other_income=len(p.other_income),
        capital_projects=len(p.capital_projects),
        has_valuation=p.valuation is not None,
        warnings=p.warnings,
    )


def job_to_read(job: ImportJob) -> ImportJobRead:
    report = json.loads(job.report_json or "{}")
    return ImportJobRead(
        id=job.id,
        filename=job.filename,
        status=job.status,
        created_at=job.created_at,
        sheets=[SheetReport.model_validate(s) for s in report.get("sheets", [])],
        properties=[PropertyPreview.model_validate(p) for p in report.get("properties", [])],
        loans=[LoanPreview.model_validate(p) for p in report.get("loans", [])],
        assumption_profiles=report.get("assumption_profiles", 0),
        warnings=report.get("warnings", []),
        errors=report.get("errors", []),
        created_property_ids=json.loads(job.created_property_ids_json or "[]"),
        created_loan_count=report.get("created_loan_count", 0),
        portfolio_id=job.portfolio_id,
    )


class ImportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def preview(self, data: bytes, filename: str, options: ImportOptions) -> ImportJob:
        try:
            sheets = read_workbook(data)
        except Exception as exc:  # corrupt / non-xlsx upload
            raise ValueError(f"Could not read workbook: {exc}") from exc
        mapper = ImportMapper(sheets, options, filename)
        payload, sheet_reports = mapper.build()
        workbook_refs = {p.external_id for p in payload.properties} | {p.name for p in payload.properties}
        loan_previews = [await self._loan_preview(l, workbook_refs) for l in payload.loans]
        report = {
            "sheets": [s.model_dump(mode="json") for s in sheet_reports],
            "properties": [_preview(p).model_dump(mode="json") for p in payload.properties],
            "loans": [lp.model_dump(mode="json") for lp in loan_previews],
            "assumption_profiles": len(payload.assumption_profiles),
            "warnings": mapper.warnings,
            "errors": mapper.errors,
        }
        job = ImportJob(
            filename=filename[:255],
            status="failed"
            if mapper.errors and not payload.properties and not payload.assumption_profiles and not payload.loans
            else "previewed",
            report_json=json.dumps(report),
            payload_json=payload.model_dump_json(),
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def _existing_property(self, ref: str | None) -> Property | None:
        if not ref:
            return None
        return (await self.db.execute(
            select(Property).where(Property.external_id == ref).limit(1)
        )).scalar_one_or_none()

    async def _loan_preview(self, loan: ImportedLoan, workbook_refs: set[str]) -> LoanPreview:
        warnings = list(loan.warnings)
        if loan.property_ref and loan.property_ref in workbook_refs:
            link = "workbook"
        elif await self._existing_property(loan.property_ref) is not None:
            link = "existing"
        else:
            link = "new"
            if loan.tape_noi is None or loan.tape_value is None:
                warnings.append("New tape-only collateral without NOI and value cannot be simulated")
        return LoanPreview(
            external_id=loan.external_id,
            property_ref=loan.property_ref,
            property_name=loan.property_name,
            property_link=link,
            lien_position=loan.lien_position,
            original_balance=loan.original_balance,
            reported_balance=loan.reported_balance,
            origination_date=loan.origination_date,
            maturity_date=loan.maturity_date,
            rate_type=loan.rate_type,
            rate=loan.coupon if loan.rate_type == "fixed" else loan.spread,
            delinquency_status=loan.delinquency_status,
            has_tape_collateral=loan.tape_noi is not None and loan.tape_value is not None,
            warnings=warnings,
        )

    async def _portfolio_by_name(self, name: str) -> Portfolio:
        existing = (
            await self.db.execute(
                select(Portfolio).where(Portfolio.name == name).options(selectinload(Portfolio.properties))
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        portfolio = Portfolio(name=name)
        portfolio.properties = []
        self.db.add(portfolio)
        await self.db.flush()
        return portfolio

    async def commit(self, job: ImportJob, req: ImportCommitRequest) -> ImportJob:
        if job.status == "committed":
            raise ValueError("Import already committed")
        if job.status == "failed":
            raise ValueError("Import has errors and cannot be committed")
        payload = ImportPayload.model_validate_json(job.payload_json)

        portfolio: Portfolio | None = None
        if req.portfolio_id:
            portfolio = (
                await self.db.execute(
                    select(Portfolio).where(Portfolio.id == req.portfolio_id)
                    .options(selectinload(Portfolio.properties))
                )
            ).scalar_one_or_none()
            if portfolio is None:
                raise LookupError("Portfolio not found")
        elif req.portfolio_name:
            portfolio = await self._portfolio_by_name(req.portfolio_name)

        created: list[str] = []
        named_portfolios: dict[str, Portfolio] = {}
        props_by_ref: dict[str, Property] = {}
        for ip in payload.properties:
            if req.replace_existing:
                old = (
                    await self.db.execute(select(Property).where(Property.external_id == ip.external_id))
                ).scalars().all()
                for o in old:
                    await self.db.delete(o)
                await self.db.flush()
            prop = await self._create_property(ip)
            created.append(prop.id)
            props_by_ref[ip.external_id] = props_by_ref[ip.name] = prop
            target = portfolio
            if target is None and ip.portfolio_name:
                target = named_portfolios.get(ip.portfolio_name) or await self._portfolio_by_name(ip.portfolio_name)
                named_portfolios[ip.portfolio_name] = target
            if target is not None:
                target.properties.append(prop)

        for ap in payload.assumption_profiles:
            pf_id = None
            if ap.portfolio_name:
                pf = named_portfolios.get(ap.portfolio_name) or await self._portfolio_by_name(ap.portfolio_name)
                named_portfolios[ap.portfolio_name] = pf
                pf_id = pf.id
            elif portfolio is not None:
                pf_id = portfolio.id
            # Same scope as an existing profile: update it, so a library can be re-imported
            scope = {"portfolio_id": pf_id, "property_type": ap.property_type, "cbsa_code": ap.cbsa_code,
                     "market": ap.market, "state": ap.state, "quality_score": ap.quality_score}
            stmt = select(AssumptionProfile)
            for col, value in scope.items():
                column = getattr(AssumptionProfile, col)
                stmt = stmt.where(column.is_(None) if value is None else column == value)
            profile = (await self.db.execute(stmt)).scalars().first()
            if profile is None:
                profile = AssumptionProfile(**scope)
                self.db.add(profile)
            profile.name = ap.name
            profile.values_json = ap.values.model_dump_json(exclude_none=True)
            profile.ranges_json = json.dumps({k: {"low": str(r.low), "high": str(r.high)} for k, r in ap.ranges.items()})
            profile.as_of, profile.source = ap.as_of, ap.source
            if ap.comment is not None:
                profile.comment = ap.comment

        loan_count = 0
        for il in payload.loans:
            prop = await self._collateral_for_loan(il, props_by_ref, created)
            if req.replace_existing:
                for old in (await self.db.execute(
                    select(MortgageLoan).where(MortgageLoan.external_id == il.external_id)
                )).scalars().all():
                    await self.db.delete(old)
            target = portfolio
            if target is None and il.portfolio_name:
                target = named_portfolios.get(il.portfolio_name) or await self._portfolio_by_name(il.portfolio_name)
                named_portfolios[il.portfolio_name] = target
            if target is not None and all(p.id != prop.id for p in target.properties):
                target.properties.append(prop)
            self.db.add(MortgageLoan(
                property_id=prop.id,
                portfolio_id=target.id if target else None,
                **il.model_dump(exclude={
                    "property_ref", "property_name", "property_type", "market", "address_line1", "city",
                    "state", "zip_code", "total_area", "area_unit", "portfolio_name", "warnings",
                }),
                comment="; ".join(il.warnings)[:2000] or None,
            ))
            loan_count += 1

        report = json.loads(job.report_json or "{}")
        report["created_loan_count"] = loan_count
        job.report_json = json.dumps(report)
        job.status = "committed"
        job.created_property_ids_json = json.dumps(created)
        job.portfolio_id = portfolio.id if portfolio else None
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def _collateral_for_loan(
        self, il: ImportedLoan, props_by_ref: dict[str, Property], created: list[str]
    ) -> Property:
        """The workbook property, an existing property with the same external id, or a new tape-only one."""
        ref = il.property_ref or il.property_name
        if ref and ref in props_by_ref:
            return props_by_ref[ref]
        existing = await self._existing_property(il.property_ref)
        if existing is not None:
            props_by_ref[ref] = existing
            return existing
        start = start_of_month(il.balance_as_of_date or date.today())
        prop = Property(
            name=(il.property_name or il.property_ref or f"Collateral for {il.external_id}")[:255],
            external_id=(il.property_ref or f"LOAN-{il.external_id}")[:100],
            property_type=il.property_type or "office",
            market=il.market,
            address_line1=il.address_line1,
            city=il.city,
            state=il.state,
            zip_code=il.zip_code,
            total_area=il.total_area if il.total_area and il.total_area > 0 else Decimal(1),
            area_unit=il.area_unit,
            analysis_start_date=start,
            analysis_period_months=120,
            fiscal_year_end_month=12,
            ownership_pct=Decimal(1),
            comment="Created from loan tape" + ("" if il.total_area else "; area not on tape"),
        )
        self.db.add(prop)
        await self.db.flush()
        created.append(prop.id)
        if ref:
            props_by_ref[ref] = prop
        return prop

    async def _create_property(self, ip: ImportedProperty) -> Property:
        prop = Property(
            name=ip.name[:255],
            external_id=ip.external_id[:100],
            address_line1=ip.address_line1,
            city=ip.city,
            state=ip.state,
            zip_code=ip.zip_code,
            market=ip.market,
            property_type=ip.property_type,
            total_area=ip.total_area,
            area_unit=ip.area_unit,
            year_built=ip.year_built,
            analysis_start_date=ip.analysis_start_date,
            analysis_period_months=ip.analysis_period_months,
            fiscal_year_end_month=ip.fiscal_year_end_month,
            ownership_pct=Decimal(1),
            comment="Imported" + (f": {'; '.join(ip.warnings)[:2000]}" if ip.warnings else ""),
        )
        self.db.add(prop)
        await self.db.flush()

        # The model belongs to a valuation, so one is always created
        v = ip.valuation
        defaulted = v is None or v.discount_rate is None or v.exit_cap_rate is None
        valuation = Valuation(
            property_id=prop.id,
            name="Imported",
            description=(
                "Discount rate / exit cap not in workbook; defaults used" if defaulted else None
            ),
            discount_rate=(v.discount_rate if v and v.discount_rate else _DEFAULT_DISCOUNT),
            exit_cap_rate=(v.exit_cap_rate if v and v.exit_cap_rate else _DEFAULT_EXIT_CAP),
            exit_cap_applied_to_year=-1,
            exit_costs_pct=(v.exit_costs_pct if v and v.exit_costs_pct is not None else Decimal("0.02")),
            transfer_tax_preset="none",
            apply_stabilized_gross_up=True,
            capital_reserves_per_unit=Decimal("0.25") if ip.area_unit == "sf" else Decimal("250"),
            use_mid_year_convention=False,
            purchase_price=v.purchase_price if v else None,
            acquisition_costs_pct=Decimal(0),
            loan_amount=v.loan_amount if v else None,
            interest_rate=v.interest_rate if v else None,
            amortization_months=v.amortization_months if v else None,
            loan_term_months=v.loan_term_months if v else None,
            io_period_months=(v.io_period_months or 0) if v else 0,
            loan_fees_pct=(v.loan_fees_pct or Decimal(0)) if v else Decimal(0),
            additional_loans=v.additional_loans if v else [],
            exit_deduct_forward_capital=False,
            analysis_start_date_override=ip.analysis_start_date,
            analysis_period_months_override=ip.analysis_period_months,
            self_storage_assumptions_json=ip.self_storage_assumptions_json,
        )
        self.db.add(valuation)
        await self.db.flush()

        profiles: dict[str, MarketLeasingProfile] = {}
        for mp in ip.market_profiles:
            row = MarketLeasingProfile(
                property_id=prop.id, valuation_id=valuation.id,
                space_type=mp.space_type,
                description=mp.key[:255],
                market_rent_per_unit=mp.market_rent_per_unit,
                rent_growth_rate_pct=mp.rent_growth_rate_pct,
                rent_growth_schedule=mp.rent_growth_schedule,
                new_lease_term_months=mp.new_lease_term_months,
                new_tenant_ti_per_sf=mp.new_tenant_ti_per_sf,
                new_tenant_lc_pct=mp.new_tenant_lc_pct,
                new_tenant_free_rent_months=mp.new_tenant_free_rent_months,
                downtime_months=mp.downtime_months,
                renewal_probability=mp.renewal_probability,
                renewal_lease_term_months=mp.renewal_lease_term_months,
                renewal_ti_per_sf=mp.renewal_ti_per_sf,
                renewal_lc_pct=mp.renewal_lc_pct,
                renewal_free_rent_months=mp.renewal_free_rent_months,
                renewal_rent_adjustment_pct=mp.renewal_rent_adjustment_pct,
                general_vacancy_pct=mp.general_vacancy_pct,
                credit_loss_pct=mp.credit_loss_pct,
                general_vacancy_schedule=mp.general_vacancy_schedule,
                credit_loss_schedule=mp.credit_loss_schedule,
                renewal_probability_schedule=mp.renewal_probability_schedule,
                downtime_schedule=[Decimal(d) for d in mp.downtime_schedule],
                new_free_rent_schedule=mp.new_free_rent_schedule,
                renewal_free_rent_schedule=mp.renewal_free_rent_schedule,
                concession_timing_mode="blended",
                rollover_method="blended",   # published DCF software market leasing weights renewal and new terms into one lease
            )
            self.db.add(row)
            profiles[mp.space_type] = row

        suites: dict[str, Suite] = {}
        for s in ip.suites:
            suite = Suite(
                property_id=prop.id, valuation_id=valuation.id, suite_name=s.suite_name, area=s.area, space_type=s.space_type,
                floor=s.floor, is_available=True,
            )
            self.db.add(suite)
            suites[s.suite_name] = suite
        await self.db.flush()

        tenants: dict[str, Tenant] = {}
        for il in ip.leases:
            suite = suites.get(il.suite_name)
            if suite is None:
                continue
            tenant = None
            if il.tenant_name:
                tenant = tenants.get(il.tenant_name)
                if tenant is None:
                    tenant = Tenant(property_id=prop.id, valuation_id=valuation.id, name=il.tenant_name)
                    self.db.add(tenant)
                    await self.db.flush()
                    tenants[il.tenant_name] = tenant
            lease = Lease(
                suite_id=suite.id,
                tenant_id=tenant.id if tenant else None,
                lease_type=il.lease_type,
                lease_start_date=il.lease_start_date,
                lease_end_date=il.lease_end_date,
                base_rent_per_unit=il.base_rent_per_unit,
                rent_payment_frequency=il.rent_payment_frequency,
                escalation_type=il.escalation_type,
                escalation_pct_annual=il.escalation_pct_annual,
                cpi_floor=il.cpi_floor,
                cpi_cap=il.cpi_cap,
                recovery_type=il.recovery_type,
                pro_rata_share_pct=il.pro_rata_share_pct,
                base_year=il.base_year,
                expense_stop_per_sf=il.expense_stop_per_sf,
                pct_rent_breakpoint=il.pct_rent_breakpoint,
                pct_rent_rate=il.pct_rent_rate,
                projected_annual_sales_per_sf=il.projected_annual_sales_per_sf,
                renewal_probability=il.renewal_probability,
                upon_expiration=il.upon_expiration or "market",
            )
            self.db.add(lease)
            await self.db.flush()
            for step in il.rent_steps:
                self.db.add(RentStep(
                    lease_id=lease.id, effective_date=step.effective_date, rent_per_unit=step.rent_per_unit,
                ))
            if il.free_rent_months > 0:
                self.db.add(FreeRentPeriod(
                    lease_id=lease.id,
                    start_date=il.lease_start_date,
                    end_date=add_months(il.lease_start_date, il.free_rent_months) - timedelta(days=1),
                    applies_to_base_rent=True,
                    applies_to_recoveries=False,
                ))

        for e in ip.expenses:
            self.db.add(PropertyExpense(
                property_id=prop.id, valuation_id=valuation.id, category=e.category[:50], description=e.description,
                base_year_amount=e.base_year_amount, growth_rate_pct=e.growth_rate_pct,
                growth_schedule=e.growth_schedule,
                is_recoverable=e.is_recoverable, is_gross_up_eligible=e.is_gross_up_eligible,
                gross_up_vacancy_pct=e.gross_up_vacancy_pct, is_pct_of_egi=e.is_pct_of_egi,
                pct_of_egi=e.pct_of_egi, is_memo=e.is_memo,
            ))
        for oi in ip.other_income:
            self.db.add(PropertyOtherIncome(
                property_id=prop.id, valuation_id=valuation.id, category=oi.category, description=oi.description,
                base_year_amount=oi.base_year_amount, growth_rate_pct=oi.growth_rate_pct,
                growth_schedule=oi.growth_schedule,
            ))
        for cp in ip.capital_projects:
            self.db.add(PropertyCapitalProject(
                property_id=prop.id, valuation_id=valuation.id, description=cp.description, total_amount=cp.total_amount,
                start_date=cp.start_date, duration_months=max(1, cp.duration_months),
            ))

        await self.db.flush()
        return prop
