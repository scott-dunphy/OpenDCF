"""
ValuationService: bridge between the DB/ORM layer and the pure-Python engine.

Responsibilities:
  1. Load all required data from the DB (property, suites, leases, market, expenses, valuation)
  2. Convert SQLAlchemy models → engine dataclasses
  3. Call engine.property_cashflow.run_valuation()
  4. Persist results back to the Valuation row
  5. Convert EngineResult → response schemas
"""
from __future__ import annotations

import calendar
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    AnalysisPeriod,
    CapitalProjectInput,
    ExpenseInput,
    OtherIncomeInput,
    ExpenseRecoveryOverride,
    FreeRentPeriodInput,
    LeaseInput,
    MarketAssumptions,
    RentStepInput,
    SuiteInput,
    ValuationParams,
)
from src.models.expense import PropertyExpense
from src.models.lease import FreeRentPeriod, Lease, LeaseExpenseRecovery, RentStep, Tenant
from src.models.market import MarketLeasingProfile
from src.models.recovery_structure import RecoveryStructure
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.schemas.cashflow import (
    AnnualCashFlowSummary,
    KeyMetricsSummary,
    LeaseExpirationEntry,
    RentRollEntry,
    TenantCashFlowDetail,
    ValuationRunResponse,
)
from src.schemas.common import ValuationStatus


class ValuationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Public interface
    # =========================================================================

    async def execute_valuation(self, valuation_id: str) -> ValuationRunResponse:
        """Load data, run engine, persist results, return response."""
        # Load valuation
        valuation = await self._load_valuation(valuation_id)
        if valuation is None:
            raise ValueError(f"Valuation {valuation_id} not found")

        # Mark as running
        valuation.status = ValuationStatus.RUNNING.value
        await self.db.commit()

        try:
            # Load related entities
            property_ = await self._load_property(valuation.property_id)
            if property_ is None:
                raise ValueError(f"Property {valuation.property_id} not found")

            suites = await self._load_suites(property_.id)
            leases = await self._load_all_leases(property_.id)
            market_profiles = await self._load_market_profiles(property_.id)
            expenses = await self._load_expenses(property_.id)
            cap_projects = await self._load_capital_projects(property_.id)
            oi_items = await self._load_other_income(property_.id)

            # Convert to engine types
            engine_suites = [self._to_suite_input(s) for s in suites]
            engine_leases = [self._to_lease_input(l) for l in leases]
            rent_freq = "monthly" if property_.area_unit == "unit" else "annual"
            engine_market = {m.space_type: self._to_market_assumptions(m, rent_freq) for m in market_profiles}
            engine_expenses = [self._to_expense_input(e) for e in expenses]
            engine_params = self._to_valuation_params(valuation, property_)
            engine_cap_projects = [self._to_capital_project_input(cp) for cp in cap_projects]
            engine_oi = [self._to_other_income_input(oi) for oi in oi_items]

            # Run the engine
            result = run_valuation(
                property_start_date=property_.analysis_start_date,
                analysis_period_months=property_.analysis_period_months,
                fiscal_year_end_month=property_.fiscal_year_end_month,
                suites=engine_suites,
                leases=engine_leases,
                market_assumptions=engine_market,
                expenses=engine_expenses,
                params=engine_params,
                property_type=property_.property_type,
                capital_projects=engine_cap_projects,
                other_income_items=engine_oi,
            )

            # Build tenant CFs before persist (needed for JSON serialization)
            tenant_cfs = self._build_tenant_cash_flows(result, leases)

            # Persist results
            valuation.status = ValuationStatus.COMPLETED.value
            valuation.result_npv = result.npv
            valuation.result_irr = result.irr
            valuation.result_going_in_cap_rate = result.going_in_cap_rate
            valuation.result_exit_value = result.terminal_value
            valuation.result_equity_multiple = result.equity_multiple
            valuation.result_terminal_noi_basis = result.terminal_noi_basis
            valuation.result_terminal_gross_value = result.terminal_gross_value
            valuation.result_terminal_exit_costs_amount = result.terminal_exit_costs_amount
            valuation.result_terminal_transfer_tax_amount = result.terminal_transfer_tax_amount
            valuation.result_terminal_transfer_tax_preset = result.terminal_transfer_tax_preset
            valuation.result_cash_flows_json = json.dumps(
                [self._serialize_annual_cf(cf) for cf in result.annual_cash_flows]
            )
            valuation.result_tenant_cash_flows_json = json.dumps(
                [t.model_dump(mode='json') for t in tenant_cfs]
            )
            await self.db.commit()

            # Build response
            return self._to_run_response(valuation, property_, suites, leases, result)

        except Exception as exc:
            valuation.status = ValuationStatus.FAILED.value
            valuation.error_message = str(exc)
            await self.db.commit()
            raise

    async def get_results(self, valuation_id: str) -> ValuationRunResponse | None:
        """Return cached results for a completed valuation."""
        valuation = await self._load_valuation(valuation_id)
        if valuation is None:
            return None
        if valuation.status != ValuationStatus.COMPLETED.value:
            return ValuationRunResponse(
                valuation_id=valuation_id,
                status=valuation.status,
                error_message=valuation.error_message,
            )

        property_ = await self._load_property(valuation.property_id)
        suites = await self._load_suites(valuation.property_id)
        leases = await self._load_all_leases(valuation.property_id)

        # Reconstruct basic response from persisted JSON
        annual_cfs = []
        if valuation.result_cash_flows_json:
            raw = json.loads(valuation.result_cash_flows_json)
            for item in raw:
                annual_cfs.append(AnnualCashFlowSummary(**item))

        tenant_cfs = []
        if valuation.result_tenant_cash_flows_json:
            raw = json.loads(valuation.result_tenant_cash_flows_json)
            for item in raw:
                tenant_cfs.append(TenantCashFlowDetail(**item))

        return ValuationRunResponse(
            valuation_id=valuation_id,
            status=valuation.status,
            key_metrics=self._build_key_metrics_from_valuation(valuation, annual_cfs),
            annual_cash_flows=annual_cfs,
            tenant_cash_flows=tenant_cfs,
            rent_roll=self._build_rent_roll(suites, leases, property_),
            lease_expiration_schedule=self._build_expiration_schedule(suites, leases, property_),
        )

    # =========================================================================
    # DB loaders
    # =========================================================================

    async def _load_valuation(self, valuation_id: str) -> Valuation | None:
        result = await self.db.execute(
            select(Valuation).where(Valuation.id == valuation_id)
        )
        return result.scalar_one_or_none()

    async def _load_property(self, property_id: str) -> Property | None:
        result = await self.db.execute(
            select(Property).where(Property.id == property_id)
        )
        return result.scalar_one_or_none()

    async def _load_suites(self, property_id: str) -> list[Suite]:
        result = await self.db.execute(
            select(Suite)
            .where(Suite.property_id == property_id)
            .options(selectinload(Suite.market_leasing_profile))
        )
        return list(result.scalars().all())

    async def _load_all_leases(self, property_id: str) -> list[Lease]:
        """Load all leases for all suites in a property, with sub-relationships."""
        result = await self.db.execute(
            select(Lease)
            .join(Suite, Lease.suite_id == Suite.id)
            .where(Suite.property_id == property_id)
            .options(
                selectinload(Lease.rent_steps),
                selectinload(Lease.free_rent_periods),
                selectinload(Lease.expense_recovery_overrides),
                selectinload(Lease.suite),
                selectinload(Lease.tenant),
                selectinload(Lease.recovery_structure).selectinload(
                    RecoveryStructure.items
                ),
            )
        )
        return list(result.scalars().all())

    async def _load_market_profiles(self, property_id: str) -> list[MarketLeasingProfile]:
        result = await self.db.execute(
            select(MarketLeasingProfile).where(MarketLeasingProfile.property_id == property_id)
        )
        return list(result.scalars().all())

    async def _load_capital_projects(self, property_id: str):
        from src.models.capital import PropertyCapitalProject
        result = await self.db.execute(
            select(PropertyCapitalProject).where(PropertyCapitalProject.property_id == property_id)
        )
        return list(result.scalars().all())

    async def _load_other_income(self, property_id: str):
        from src.models.other_income import PropertyOtherIncome
        result = await self.db.execute(
            select(PropertyOtherIncome).where(PropertyOtherIncome.property_id == property_id)
        )
        return list(result.scalars().all())

    async def _load_expenses(self, property_id: str) -> list[PropertyExpense]:
        result = await self.db.execute(
            select(PropertyExpense).where(PropertyExpense.property_id == property_id)
        )
        return list(result.scalars().all())

    # =========================================================================
    # Model → Engine type converters
    # =========================================================================

    def _to_suite_input(self, suite: Suite) -> SuiteInput:
        # If suite has an explicitly assigned MLA, use its space_type
        # so the engine matches the correct market profile.
        effective_space_type = suite.space_type
        if suite.market_leasing_profile_id and suite.market_leasing_profile:
            effective_space_type = suite.market_leasing_profile.space_type
        return SuiteInput(
            suite_id=suite.id,
            suite_name=suite.suite_name,
            area=suite.area,
            space_type=effective_space_type,
        )

    def _to_lease_input(self, lease: Lease) -> LeaseInput:
        rent_steps = tuple(
            RentStepInput(
                effective_date=rs.effective_date,
                rent_per_unit=rs.rent_per_unit,
            )
            for rs in sorted(lease.rent_steps, key=lambda r: r.effective_date)
        )
        free_rents = tuple(
            FreeRentPeriodInput(
                start_date=frp.start_date,
                end_date=frp.end_date,
                applies_to_base_rent=frp.applies_to_base_rent,
                applies_to_recoveries=frp.applies_to_recoveries,
            )
            for frp in lease.free_rent_periods
        )
        # Build recovery overrides: per-lease overrides take priority over template items
        overrides_by_cat: dict[str, ExpenseRecoveryOverride] = {}
        # 1. Template items (lower priority)
        if lease.recovery_structure and lease.recovery_structure.items:
            for item in lease.recovery_structure.items:
                overrides_by_cat[item.expense_category] = ExpenseRecoveryOverride(
                    expense_category=item.expense_category,
                    recovery_type=item.recovery_type,
                    base_year_stop_amount=item.base_year_stop_amount,
                    cap_per_sf_annual=item.cap_per_sf_annual,
                    floor_per_sf_annual=item.floor_per_sf_annual,
                    admin_fee_pct=item.admin_fee_pct,
                )
        # 2. Per-lease overrides (higher priority, overwrites template)
        for o in lease.expense_recovery_overrides:
            overrides_by_cat[o.expense_category] = ExpenseRecoveryOverride(
                expense_category=o.expense_category,
                recovery_type=o.recovery_type,
                base_year_stop_amount=o.base_year_stop_amount,
                cap_per_sf_annual=o.cap_per_sf_annual,
                floor_per_sf_annual=o.floor_per_sf_annual,
                admin_fee_pct=o.admin_fee_pct,
            )
        overrides = tuple(overrides_by_cat.values())
        # Get tenant name via relationship (may be None for vacant/spec)
        tenant_name: str | None = None
        if lease.tenant and hasattr(lease, 'tenant') and lease.tenant is not None:
            tenant_name = lease.tenant.name

        # MTM leases are treated as expiring at the end of their current month
        # so the renewal engine generates speculative leases for the remainder.
        end_date = lease.lease_end_date
        if lease.lease_type == "month_to_month":
            _, last_day = calendar.monthrange(end_date.year, end_date.month)
            end_date = date(end_date.year, end_date.month, last_day)

        return LeaseInput(
            lease_id=lease.id,
            suite_id=lease.suite_id,
            tenant_name=tenant_name,
            area=self._suite_area_for_lease(lease),
            start_date=lease.lease_start_date,
            end_date=end_date,
            base_rent_per_unit=lease.base_rent_per_unit,
            rent_payment_frequency=lease.rent_payment_frequency,
            escalation_type=lease.escalation_type,
            escalation_pct=lease.escalation_pct_annual,
            cpi_floor=lease.cpi_floor,
            cpi_cap=lease.cpi_cap,
            rent_steps=rent_steps,
            free_rent_periods=free_rents,
            recovery_type=(
                lease.recovery_structure.default_recovery_type
                if lease.recovery_structure
                else lease.recovery_type
            ),
            pro_rata_share=lease.pro_rata_share_pct,
            base_year=lease.base_year,
            base_year_stop_amount=lease.base_year_stop_amount,
            expense_stop_per_sf=lease.expense_stop_per_sf,
            recovery_overrides=overrides,
            pct_rent_breakpoint=lease.pct_rent_breakpoint,
            pct_rent_rate=lease.pct_rent_rate,
            renewal_probability_override=lease.renewal_probability,
            renewal_rent_spread_override=lease.renewal_rent_spread_pct,
            projected_annual_sales_per_sf=lease.projected_annual_sales_per_sf,
        )

    def _suite_area_for_lease(self, lease: Lease) -> Decimal:
        """Get the area of the suite associated with this lease."""
        if hasattr(lease, 'suite') and lease.suite is not None:
            return lease.suite.area
        return Decimal(0)

    def _to_market_assumptions(self, m: MarketLeasingProfile, rent_freq: str = "annual") -> MarketAssumptions:
        return MarketAssumptions(
            space_type=m.space_type,
            market_rent_per_unit=m.market_rent_per_unit,
            rent_growth_rate=m.rent_growth_rate_pct,
            rent_payment_frequency=rent_freq,
            new_lease_term_months=m.new_lease_term_months,
            new_ti_per_sf=m.new_tenant_ti_per_sf,
            new_lc_pct=m.new_tenant_lc_pct,
            new_free_rent_months=m.new_tenant_free_rent_months,
            downtime_months=m.downtime_months,
            renewal_probability=m.renewal_probability,
            renewal_term_months=m.renewal_lease_term_months,
            renewal_ti_per_sf=m.renewal_ti_per_sf,
            renewal_lc_pct=m.renewal_lc_pct,
            renewal_free_rent_months=m.renewal_free_rent_months,
            renewal_rent_adjustment_pct=m.renewal_rent_adjustment_pct,
            general_vacancy_pct=m.general_vacancy_pct,
            credit_loss_pct=m.credit_loss_pct,
        )

    def _to_expense_input(self, e: PropertyExpense) -> ExpenseInput:
        return ExpenseInput(
            expense_id=e.id,
            category=e.category,
            base_amount=e.base_year_amount,
            growth_rate=e.growth_rate_pct,
            is_recoverable=e.is_recoverable,
            is_gross_up_eligible=e.is_gross_up_eligible,
            gross_up_vacancy_pct=e.gross_up_vacancy_pct,
            is_pct_of_egi=e.is_pct_of_egi,
            pct_of_egi=e.pct_of_egi,
        )

    def _to_other_income_input(self, oi) -> OtherIncomeInput:
        return OtherIncomeInput(
            income_id=oi.id,
            category=oi.category,
            base_amount=oi.base_year_amount,
            growth_rate=oi.growth_rate_pct,
        )

    def _to_capital_project_input(self, cp) -> CapitalProjectInput:
        return CapitalProjectInput(
            project_id=cp.id,
            description=cp.description,
            total_amount=cp.total_amount,
            start_date=cp.start_date,
            duration_months=cp.duration_months,
        )

    def _to_valuation_params(self, v: Valuation, p: Property) -> ValuationParams:
        return ValuationParams(
            discount_rate=v.discount_rate,
            exit_cap_rate=v.exit_cap_rate,
            exit_cap_year=v.exit_cap_applied_to_year,
            exit_costs_pct=v.exit_costs_pct,
            transfer_tax_preset=v.transfer_tax_preset or "none",
            transfer_tax_custom_rate=v.transfer_tax_custom_rate,
            capital_reserves_per_unit=v.capital_reserves_per_unit,
            total_property_area=p.total_area,
            use_mid_year_convention=v.use_mid_year_convention,
            loan_amount=v.loan_amount,
            interest_rate=v.interest_rate,
            amortization_months=v.amortization_months,
            loan_term_months=v.loan_term_months,
            io_period_months=v.io_period_months or 0,
        )

    # =========================================================================
    # Serialization helpers
    # =========================================================================

    def _serialize_annual_cf(self, cf) -> dict:
        return {
            "year": cf.year,
            "period_start": cf.period_start.isoformat(),
            "period_end": cf.period_end.isoformat(),
            "gross_potential_rent": str(cf.gross_potential_rent),
            "absorption_vacancy": str(cf.absorption_vacancy),
            "free_rent": str(cf.free_rent),
            "loss_to_lease": str(cf.loss_to_lease),
            "expense_detail": {k: str(v) for k, v in cf.expense_detail.items()},
            "other_income_detail": {k: str(v) for k, v in cf.other_income_detail.items()},
            "expense_recoveries": str(cf.expense_recoveries),
            "percentage_rent": str(cf.percentage_rent),
            "other_income": str(cf.other_income),
            "gross_potential_income": str(cf.gross_potential_income),
            "general_vacancy_loss": str(cf.general_vacancy_loss),
            "credit_loss": str(cf.credit_loss),
            "effective_gross_income": str(cf.effective_gross_income),
            "operating_expenses": str(cf.operating_expenses),
            "net_operating_income": str(cf.net_operating_income),
            "tenant_improvements": str(cf.tenant_improvements),
            "leasing_commissions": str(cf.leasing_commissions),
            "capital_reserves": str(cf.capital_reserves),
            "building_improvements": str(cf.building_improvements),
            "cash_flow_before_debt": str(cf.cash_flow_before_debt),
            "debt_service": str(cf.debt_service),
            "levered_cash_flow": str(cf.levered_cash_flow),
        }

    def _to_run_response(
        self,
        valuation: Valuation,
        property_: Property,
        suites: list[Suite],
        leases: list[Lease],
        result,
    ) -> ValuationRunResponse:
        annual_cfs = [
            AnnualCashFlowSummary(
                year=cf.year,
                period_start=cf.period_start,
                period_end=cf.period_end,
                gross_potential_rent=cf.gross_potential_rent,
                free_rent=cf.free_rent,
                absorption_vacancy=cf.absorption_vacancy,
                loss_to_lease=cf.loss_to_lease,
                expense_recoveries=cf.expense_recoveries,
                percentage_rent=cf.percentage_rent,
                other_income=cf.other_income,
                gross_potential_income=cf.gross_potential_income,
                general_vacancy_loss=cf.general_vacancy_loss,
                credit_loss=cf.credit_loss,
                effective_gross_income=cf.effective_gross_income,
                operating_expenses=cf.operating_expenses,
                expense_detail=cf.expense_detail,
                other_income_detail=cf.other_income_detail,
                net_operating_income=cf.net_operating_income,
                tenant_improvements=cf.tenant_improvements,
                leasing_commissions=cf.leasing_commissions,
                capital_reserves=cf.capital_reserves,
                building_improvements=cf.building_improvements,
                cash_flow_before_debt=cf.cash_flow_before_debt,
                debt_service=cf.debt_service,
                levered_cash_flow=cf.levered_cash_flow,
            )
            for cf in result.annual_cash_flows
        ]

        tenant_cfs = self._build_tenant_cash_flows(result, leases)
        walt = self._compute_walt(suites, leases, property_.analysis_start_date)
        key_metrics = self._build_key_metrics(valuation, result, annual_cfs, walt)
        expiration_schedule = self._build_expiration_schedule(suites, leases, property_)
        rent_roll = self._build_rent_roll(suites, leases, property_)

        return ValuationRunResponse(
            valuation_id=valuation.id,
            status=valuation.status,
            key_metrics=key_metrics,
            annual_cash_flows=annual_cfs,
            tenant_cash_flows=tenant_cfs,
            lease_expiration_schedule=expiration_schedule,
            rent_roll=rent_roll,
        )

    def _build_key_metrics(
        self, valuation: Valuation, result, annual_cfs: list, walt: Decimal | None = None
    ) -> KeyMetricsSummary:
        y1 = annual_cfs[0] if annual_cfs else None
        return KeyMetricsSummary(
            npv=result.npv,
            irr=result.irr,
            going_in_cap_rate=result.going_in_cap_rate,
            exit_cap_rate=valuation.exit_cap_rate,
            terminal_value=result.terminal_value,
            pv_of_cash_flows=result.pv_cash_flows,
            pv_of_terminal_value=result.pv_terminal,
            equity_multiple=result.equity_multiple,
            avg_occupancy_pct=result.avg_occupancy_pct,
            weighted_avg_lease_term_years=walt,
            terminal_noi_basis=result.terminal_noi_basis,
            terminal_gross_value=result.terminal_gross_value,
            terminal_exit_costs_amount=result.terminal_exit_costs_amount,
            terminal_transfer_tax_amount=result.terminal_transfer_tax_amount,
            terminal_transfer_tax_preset=result.terminal_transfer_tax_preset,
            year1_gpi=y1.gross_potential_income if y1 else Decimal(0),
            year1_egi=y1.effective_gross_income if y1 else Decimal(0),
            year1_noi=y1.net_operating_income if y1 else Decimal(0),
            year1_cfbd=y1.cash_flow_before_debt if y1 else Decimal(0),
        )

    def _build_key_metrics_from_valuation(
        self, valuation: Valuation, annual_cfs: list
    ) -> KeyMetricsSummary | None:
        if valuation.result_npv is None:
            return None
        y1 = annual_cfs[0] if annual_cfs else None
        return KeyMetricsSummary(
            npv=valuation.result_npv or Decimal(0),
            irr=valuation.result_irr,
            going_in_cap_rate=valuation.result_going_in_cap_rate or Decimal(0),
            exit_cap_rate=valuation.exit_cap_rate,
            terminal_value=valuation.result_exit_value or Decimal(0),
            pv_of_cash_flows=Decimal(0),
            pv_of_terminal_value=Decimal(0),
            equity_multiple=valuation.result_equity_multiple,
            avg_occupancy_pct=Decimal(0),
            weighted_avg_lease_term_years=None,
            terminal_noi_basis=valuation.result_terminal_noi_basis,
            terminal_gross_value=valuation.result_terminal_gross_value,
            terminal_exit_costs_amount=valuation.result_terminal_exit_costs_amount,
            terminal_transfer_tax_amount=valuation.result_terminal_transfer_tax_amount,
            terminal_transfer_tax_preset=valuation.result_terminal_transfer_tax_preset,
            year1_gpi=Decimal(y1.gross_potential_income) if y1 else Decimal(0),
            year1_egi=Decimal(y1.effective_gross_income) if y1 else Decimal(0),
            year1_noi=Decimal(y1.net_operating_income) if y1 else Decimal(0),
            year1_cfbd=Decimal(y1.cash_flow_before_debt) if y1 else Decimal(0),
        )

    def _build_tenant_cash_flows(self, result, leases: list[Lease]) -> list[TenantCashFlowDetail]:
        from collections import defaultdict
        # Group suite_annual_details by suite_id
        by_suite: dict[str, list] = defaultdict(list)
        for detail in result.suite_annual_details:
            by_suite[detail.suite_id].append(detail)

        # Index in-place leases by suite_id for lease date lookup
        inplace_by_suite: dict[str, Lease] = {}
        for lease in leases:
            if lease.lease_type == "in_place":
                # Keep the earliest-starting in-place lease per suite
                existing = inplace_by_suite.get(lease.suite_id)
                if existing is None or lease.lease_start_date < existing.lease_start_date:
                    inplace_by_suite[lease.suite_id] = lease

        result_list = []
        for suite_id, details in by_suite.items():
            details_sorted = sorted(details, key=lambda d: d.year)
            if not details_sorted:
                continue
            first = details_sorted[0]
            in_place = inplace_by_suite.get(suite_id)
            result_list.append(TenantCashFlowDetail(
                suite_id=suite_id,
                suite_name=first.suite_name,
                tenant_name=first.tenant_name,
                space_type=first.space_type,
                area=first.area,
                lease_start=in_place.lease_start_date if in_place else None,
                lease_end=in_place.lease_end_date if in_place else None,
                scenario=first.scenario,
                annual_base_rent=[d.base_rent for d in details_sorted],
                annual_free_rent=[d.free_rent for d in details_sorted],
                annual_recoveries=[d.expense_recovery for d in details_sorted],
                annual_turnover_vacancy=[d.turnover_vacancy for d in details_sorted],
                annual_loss_to_lease=[d.loss_to_lease for d in details_sorted],
                annual_ti=[d.ti_cost for d in details_sorted],
                annual_lc=[d.lc_cost for d in details_sorted],
                annual_ti_lc=[d.ti_lc_cost for d in details_sorted],
            ))
        return result_list

    def _build_rent_roll(
        self, suites: list[Suite], leases: list[Lease], property_: Property
    ) -> list[RentRollEntry]:
        lease_by_suite: dict[str, Lease | None] = {s.id: None for s in suites}
        today = property_.analysis_start_date
        for lease in leases:
            if lease.lease_start_date <= today <= lease.lease_end_date:
                lease_by_suite[lease.suite_id] = lease

        entries = []
        for suite in suites:
            lease = lease_by_suite.get(suite.id)
            annual_rent = None
            if lease:
                if lease.rent_payment_frequency == "monthly":
                    annual_rent = lease.base_rent_per_unit * suite.area * Decimal(12)
                else:
                    annual_rent = lease.base_rent_per_unit * suite.area
            entries.append(RentRollEntry(
                suite_name=suite.suite_name,
                space_type=suite.space_type,
                area=suite.area,
                tenant_name=lease.tenant.name if lease and lease.tenant else None,
                lease_start=lease.lease_start_date if lease else None,
                lease_end=lease.lease_end_date if lease else None,
                lease_type=lease.lease_type if lease else "vacant",
                base_rent_per_unit=lease.base_rent_per_unit if lease else None,
                annual_rent=annual_rent,
                recovery_type=lease.recovery_type if lease else None,
                escalation_type=lease.escalation_type if lease else None,
            ))
        return entries

    def _compute_walt(
        self, suites: list[Suite], leases: list[Lease], analysis_start: date
    ) -> Decimal | None:
        """
        Weighted Average Lease Term (WALT) in years, weighted by leased area.
        Only in-place leases active at analysis_start are included.
        Vacant suites are excluded from both numerator and denominator.
        """
        total_weighted = Decimal(0)
        total_leased_area = Decimal(0)

        # Map suite_id → area for fast lookup
        area_map = {s.id: s.area for s in suites}

        # Find the active lease for each suite at analysis_start
        active_by_suite: dict[str, Lease] = {}
        for lease in leases:
            if lease.lease_start_date <= analysis_start <= lease.lease_end_date:
                active_by_suite[lease.suite_id] = lease

        for suite_id, lease in active_by_suite.items():
            area = area_map.get(suite_id, Decimal(0))
            if area == Decimal(0):
                continue
            # Remaining days from analysis_start to lease_end_date
            remaining_days = (lease.lease_end_date - analysis_start).days
            remaining_years = Decimal(str(max(0, remaining_days))) / Decimal("365.25")
            total_weighted += area * remaining_years
            total_leased_area += area

        if total_leased_area == Decimal(0):
            return None
        return total_weighted / total_leased_area

    def _build_expiration_schedule(
        self, suites: list[Suite], leases: list[Lease], property_: Property
    ) -> list[LeaseExpirationEntry]:
        from collections import defaultdict
        analysis_start = property_.analysis_start_date
        analysis_end_year = analysis_start.year + (property_.analysis_period_months // 12) + 1

        by_year: dict[int, list[Lease]] = defaultdict(list)
        suite_area: dict[str, Decimal] = {s.id: s.area for s in suites}
        total_area = sum(suite_area.values())

        for lease in leases:
            exp_year = lease.lease_end_date.year
            if analysis_start.year <= exp_year <= analysis_end_year:
                by_year[exp_year].append(lease)

        result = []
        for year in sorted(by_year.keys()):
            year_leases = by_year[year]
            area = sum(suite_area.get(l.suite_id, Decimal(0)) for l in year_leases)
            rents = [l.base_rent_per_unit for l in year_leases if l.base_rent_per_unit]
            avg_rent = sum(rents) / Decimal(len(rents)) if rents else Decimal(0)
            result.append(LeaseExpirationEntry(
                year=year,
                expiring_leases=len(year_leases),
                expiring_area=area,
                pct_of_total_gla=area / total_area if total_area > 0 else Decimal(0),
                weighted_avg_rent_per_sf=avg_rent,
            ))
        return result
