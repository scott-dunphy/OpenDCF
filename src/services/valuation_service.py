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
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.engine.date_utils import add_months
from src.engine.marina_valuation import (
    AdditionalRevenueLineInput as MarinaAdditionalRevenueLineInput,
    CapexLifecycleInput as MarinaCapexLifecycleInput,
    CyclicalCostInput as MarinaCyclicalCostInput,
    DebtInput as MarinaDebtInput,
    DemandModelInput as MarinaDemandModelInput,
    FuelDockInput as MarinaFuelDockInput,
    LegalTenureInput as MarinaLegalTenureInput,
    MarinaModelInput,
    MarinaValuationResult,
    OperatingCostLineInput as MarinaOperatingCostLineInput,
    SlipClassInput as MarinaSlipClassInput,
    ValuationInput as MarinaValuationInput,
    run_marina_valuation,
)
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
    TenantRecoveryAuditEntry,
    ValuationRunResponse,
)
from src.schemas.common import ValuationStatus


MARINA_MONTHLY_SEASONALITY = (
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

            if property_.property_type == "marina":
                return await self._execute_marina_valuation(valuation, property_)

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
            analysis_start = self._effective_analysis_start_date(valuation, property_)

            # Run the engine
            result = run_valuation(
                property_start_date=analysis_start,
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
            recovery_audit = self._build_recovery_audit(result, suites)

            # Persist results
            valuation.status = ValuationStatus.COMPLETED.value
            valuation.result_npv = result.npv
            valuation.result_irr = result.irr
            valuation.result_going_in_cap_rate = result.going_in_cap_rate
            valuation.result_exit_value = result.terminal_value
            valuation.result_pv_cash_flows = result.pv_cash_flows
            valuation.result_pv_terminal_value = result.pv_terminal
            valuation.result_equity_multiple = result.equity_multiple
            valuation.result_avg_occupancy_pct = result.avg_occupancy_pct
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
            valuation.result_recovery_audit_json = json.dumps(
                [r.model_dump(mode='json') for r in recovery_audit]
            )
            await self.db.commit()

            # Build response
            return self._to_run_response(
                valuation,
                property_,
                suites,
                leases,
                result,
                analysis_start,
            )

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
        recovery_audit = []
        if valuation.result_recovery_audit_json:
            raw = json.loads(valuation.result_recovery_audit_json)
            for item in raw:
                recovery_audit.append(TenantRecoveryAuditEntry(**item))
        analysis_start = (
            self._effective_analysis_start_date(valuation, property_)
            if property_ is not None
            else None
        )
        walt = (
            self._compute_walt(suites, leases, analysis_start)
            if analysis_start is not None
            else None
        )

        return ValuationRunResponse(
            valuation_id=valuation_id,
            status=valuation.status,
            key_metrics=self._build_key_metrics_from_valuation(valuation, annual_cfs, walt),
            annual_cash_flows=annual_cfs,
            tenant_cash_flows=tenant_cfs,
            recovery_audit=recovery_audit,
            rent_roll=(
                self._build_rent_roll(suites, leases, analysis_start)
                if analysis_start is not None
                else []
            ),
            lease_expiration_schedule=(
                self._build_expiration_schedule(suites, leases, property_, analysis_start)
                if property_ is not None and analysis_start is not None
                else []
            ),
        )

    async def _execute_marina_valuation(
        self, valuation: Valuation, property_: Property
    ) -> ValuationRunResponse:
        analysis_start = self._effective_analysis_start_date(valuation, property_)
        if valuation.marina_assumptions_json:
            marina_model = self._build_marina_model_from_json(
                valuation, property_, analysis_start
            )
        else:
            marina_model = self._build_default_marina_model(valuation, property_, analysis_start)
        result = run_marina_valuation(marina_model)
        annual_cfs = self._build_marina_annual_cash_flows(result, analysis_start)

        is_levered = (
            marina_model.debt is not None
            and marina_model.debt.loan_amount is not None
            and marina_model.debt.loan_amount > Decimal(0)
        )
        npv = result.npv_levered if is_levered else result.npv_unlevered
        irr = result.irr_levered if is_levered else result.irr_unlevered
        pv_cash_flows = (
            result.pv_levered_cash_flows if is_levered else result.pv_unlevered_cash_flows
        )
        pv_terminal = (
            result.npv_levered - result.pv_levered_cash_flows
            if is_levered
            else result.pv_unlevered_terminal
        )
        year1_noi = result.annual_cash_flows[0].noi if result.annual_cash_flows else Decimal(0)
        purchase_price = marina_model.valuation.initial_purchase_price
        going_in_cap_rate = (
            year1_noi / purchase_price
            if purchase_price is not None and purchase_price > Decimal(0)
            else Decimal(0)
        )
        avg_occupancy_pct = (
            sum((row.avg_occupancy_pct for row in result.annual_cash_flows), Decimal(0))
            / Decimal(str(len(result.annual_cash_flows)))
            if result.annual_cash_flows
            else Decimal(0)
        )
        equity_multiple = None
        if purchase_price is not None and purchase_price > Decimal(0):
            if is_levered:
                debt_amount = marina_model.debt.loan_amount if marina_model.debt else Decimal(0)
                equity_invested = purchase_price - (debt_amount or Decimal(0))
                exit_loan_balance = result.covenants[-1].ending_loan_balance if result.covenants else Decimal(0)
                levered_terminal = result.terminal_value_after_tenure_risk - exit_loan_balance
                total_distributions = sum(
                    (cf.levered_cash_flow for cf in annual_cfs), Decimal(0)
                ) + levered_terminal
                equity_multiple = (
                    total_distributions / equity_invested
                    if equity_invested > Decimal(0) else None
                )
            else:
                total_distributions = sum(
                    (cf.cash_flow_before_debt for cf in annual_cfs), Decimal(0)
                ) + result.terminal_value_after_tenure_risk
                equity_multiple = total_distributions / purchase_price

        valuation.status = ValuationStatus.COMPLETED.value
        valuation.error_message = None
        valuation.result_npv = npv
        valuation.result_irr = irr
        valuation.result_going_in_cap_rate = going_in_cap_rate
        valuation.result_exit_value = result.terminal_value_after_tenure_risk
        valuation.result_pv_cash_flows = pv_cash_flows
        valuation.result_pv_terminal_value = pv_terminal
        valuation.result_equity_multiple = equity_multiple
        valuation.result_avg_occupancy_pct = avg_occupancy_pct
        valuation.result_terminal_noi_basis = result.terminal_noi
        valuation.result_terminal_gross_value = result.terminal_value_gross
        valuation.result_terminal_exit_costs_amount = (
            result.terminal_value_gross - result.terminal_value_net
        )
        valuation.result_terminal_transfer_tax_amount = Decimal(0)
        valuation.result_terminal_transfer_tax_preset = "none"
        valuation.result_cash_flows_json = json.dumps(
            [self._serialize_annual_cf(cf) for cf in annual_cfs]
        )
        valuation.result_tenant_cash_flows_json = "[]"
        valuation.result_recovery_audit_json = "[]"
        await self.db.commit()

        return ValuationRunResponse(
            valuation_id=valuation.id,
            status=valuation.status,
            key_metrics=self._build_key_metrics_from_valuation(valuation, annual_cfs, None),
            annual_cash_flows=annual_cfs,
            tenant_cash_flows=[],
            recovery_audit=[],
            lease_expiration_schedule=[],
            rent_roll=[],
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
            concession_timing_mode=m.concession_timing_mode or "blended",
            concession_year1_months=m.concession_year1_months,
            concession_year2_months=m.concession_year2_months,
            concession_year3_months=m.concession_year3_months,
            concession_year4_months=m.concession_year4_months,
            concession_year5_months=m.concession_year5_months,
            concession_stabilized_months=m.concession_stabilized_months,
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
            apply_stabilized_gross_up=v.apply_stabilized_gross_up,
            stabilized_occupancy_pct=v.stabilized_occupancy_pct,
            capital_reserves_per_unit=v.capital_reserves_per_unit,
            total_property_area=p.total_area,
            use_mid_year_convention=v.use_mid_year_convention,
            loan_amount=v.loan_amount,
            interest_rate=v.interest_rate,
            amortization_months=v.amortization_months,
            loan_term_months=v.loan_term_months,
            io_period_months=v.io_period_months or 0,
        )

    def _build_default_marina_model(
        self,
        valuation: Valuation,
        property_: Property,
        analysis_start: date,
    ) -> MarinaModelInput:
        if property_.area_unit == "unit":
            total_slips = max(int(property_.total_area), 1)
        else:
            total_slips = max(int(property_.total_area / Decimal("40")), 1)

        wet_count = max(1, int(total_slips * 0.60))
        dry_count = max(0, int(total_slips * 0.25))
        if wet_count + dry_count > total_slips:
            dry_count = max(0, total_slips - wet_count)
        mooring_count = max(0, total_slips - wet_count - dry_count)

        slips = [
            MarinaSlipClassInput(
                name="Wet Slips",
                kind="wet_slip",
                length_class="30-45 ft",
                utility_service_level="fifty_amp",
                count=wet_count,
                annual_contract_share=Decimal("0.60"),
                seasonal_contract_share=Decimal("0.20"),
                transient_share=Decimal("0.20"),
                annual_contract_rate=Decimal("7900"),
                seasonal_contract_rate=Decimal("4300"),
                transient_daily_rate=Decimal("62"),
                utility_fee_monthly=Decimal("45"),
                utility_fee_transient_daily=Decimal("6"),
                repair_service_revenue_per_occupied_day=Decimal("2.8"),
                retail_fnb_revenue_per_occupied_day=Decimal("1.6"),
                storage_fee_per_month=Decimal("18"),
                launch_fee_per_transient_arrival=Decimal("12"),
            ),
            MarinaSlipClassInput(
                name="Dry Stack",
                kind="dry_stack",
                length_class="25-35 ft",
                utility_service_level="water_only",
                count=dry_count,
                annual_contract_share=Decimal("0.45"),
                seasonal_contract_share=Decimal("0.20"),
                transient_share=Decimal("35") / Decimal("100"),
                annual_contract_rate=Decimal("5200"),
                seasonal_contract_rate=Decimal("2900"),
                transient_daily_rate=Decimal("44"),
                utility_fee_monthly=Decimal("16"),
                utility_fee_transient_daily=Decimal("2"),
                repair_service_revenue_per_occupied_day=Decimal("2.0"),
                retail_fnb_revenue_per_occupied_day=Decimal("1.0"),
                storage_fee_per_month=Decimal("14"),
                launch_fee_per_transient_arrival=Decimal("8"),
            ),
        ]
        if mooring_count > 0:
            slips.append(
                MarinaSlipClassInput(
                    name="Moorings",
                    kind="mooring",
                    length_class="20-35 ft",
                    utility_service_level="none",
                    count=mooring_count,
                    annual_contract_share=Decimal("0.65"),
                    seasonal_contract_share=Decimal("0.10"),
                    transient_share=Decimal("0.25"),
                    annual_contract_rate=Decimal("2800"),
                    seasonal_contract_rate=Decimal("1700"),
                    transient_daily_rate=Decimal("26"),
                    utility_fee_monthly=Decimal("0"),
                    utility_fee_transient_daily=Decimal("0"),
                    repair_service_revenue_per_occupied_day=Decimal("0.8"),
                    retail_fnb_revenue_per_occupied_day=Decimal("0.6"),
                    storage_fee_per_month=Decimal("6"),
                    launch_fee_per_transient_arrival=Decimal("4"),
                )
            )

        total_slips_dec = Decimal(str(total_slips))
        waitlist_start = max(Decimal("10"), total_slips_dec * Decimal("0.08"))
        waitlist_new = max(Decimal("4"), total_slips_dec * Decimal("0.03"))
        reserve_per_slip = (
            valuation.capital_reserves_per_unit
            if valuation.capital_reserves_per_unit >= Decimal("25")
            else Decimal("220")
        )
        hold_years = max(1, (property_.analysis_period_months + 11) // 12)

        purchase_price = total_slips_dec * Decimal("60000")
        if valuation.loan_amount is not None and valuation.loan_amount > Decimal(0):
            purchase_price = max(purchase_price, valuation.loan_amount * Decimal("1.35"))

        debt = None
        if valuation.loan_amount is not None and valuation.loan_amount > Decimal(0):
            debt = MarinaDebtInput(
                loan_amount=valuation.loan_amount,
                interest_rate=valuation.interest_rate or Decimal("0.0675"),
                amortization_months=valuation.amortization_months or 300,
                term_months=valuation.loan_term_months or hold_years * 12,
                io_period_months=valuation.io_period_months or 0,
            )

        return MarinaModelInput(
            as_of_date=analysis_start,
            slip_classes=tuple(slips),
            demand=MarinaDemandModelInput(
                monthly_seasonality=MARINA_MONTHLY_SEASONALITY,
                monthly_weather_shock_pct=tuple(Decimal("0.00") for _ in range(12)),
                seasonal_active_months=(4, 5, 6, 7, 8, 9, 10),
                annual_churn_pct=Decimal("0.12"),
                waitlist_start_count=waitlist_start,
                waitlist_conversion_pct=Decimal("0.55"),
                waitlist_new_demand_per_year=waitlist_new,
                annual_reprice_growth_pct=Decimal("0.03"),
                seasonal_reprice_growth_pct=Decimal("0.035"),
                transient_reprice_growth_pct=Decimal("0.03"),
            ),
            operating_cost_lines=(
                MarinaOperatingCostLineInput(
                    name="dock_labor",
                    annual_fixed=total_slips_dec * Decimal("2400"),
                    per_occupied_day=Decimal("2.0"),
                    growth_pct=Decimal("0.03"),
                ),
                MarinaOperatingCostLineInput(
                    name="utilities",
                    annual_fixed=total_slips_dec * Decimal("1100"),
                    per_occupied_day=Decimal("0.75"),
                    growth_pct=Decimal("0.03"),
                ),
                MarinaOperatingCostLineInput(
                    name="insurance_env",
                    annual_fixed=total_slips_dec * Decimal("650"),
                    per_occupied_day=Decimal("0.00"),
                    growth_pct=Decimal("0.035"),
                ),
            ),
            cyclical_costs=(
                MarinaCyclicalCostInput(
                    name="dredging",
                    base_amount=total_slips_dec * Decimal("1500"),
                    first_year=3,
                    every_n_years=4,
                    growth_pct=Decimal("0.03"),
                    treat_as_capex=True,
                ),
            ),
            legal_tenure=MarinaLegalTenureInput(
                tenure_type="fee_simple",
                annual_submerged_land_lease=total_slips_dec * Decimal("380"),
                annual_permit_concession_fees=total_slips_dec * Decimal("240"),
            ),
            capex_lifecycle=(
                MarinaCapexLifecycleInput(
                    name="floating_docks",
                    asset_type="floating_docks",
                    base_amount=total_slips_dec * Decimal("1200"),
                    first_year=4,
                    every_n_years=5,
                    growth_pct=Decimal("0.03"),
                ),
            ),
            valuation=MarinaValuationInput(
                hold_years=hold_years,
                discount_rate=valuation.discount_rate,
                exit_cap_rate=valuation.exit_cap_rate,
                exit_costs_pct=valuation.exit_costs_pct,
                use_mid_year_convention=valuation.use_mid_year_convention,
                terminal_noi_growth_pct=Decimal("0.02"),
                dock_replacement_reserve_per_slip_year=reserve_per_slip,
                reserve_growth_pct=Decimal("0.03"),
                initial_purchase_price=purchase_price,
            ),
            debt=debt,
        )

    def _build_marina_model_from_json(
        self,
        valuation: Valuation,
        property_: Property,
        analysis_start: date,
    ) -> MarinaModelInput:
        data = json.loads(valuation.marina_assumptions_json)

        def _parse_slip_class(s: dict) -> "MarinaSlipClassInput":
            return MarinaSlipClassInput(
                name=s["name"],
                kind=s["kind"],
                length_class=s["length_class"],
                utility_service_level=s["utility_service_level"],
                count=int(s["count"]),
                annual_contract_share=Decimal(str(s["annual_contract_share"])),
                seasonal_contract_share=Decimal(str(s["seasonal_contract_share"])),
                transient_share=Decimal(str(s["transient_share"])),
                annual_contract_rate=Decimal(str(s["annual_contract_rate"])),
                seasonal_contract_rate=Decimal(str(s["seasonal_contract_rate"])),
                transient_daily_rate=Decimal(str(s["transient_daily_rate"])),
                utility_fee_monthly=Decimal(str(s.get("utility_fee_monthly", 0))),
                utility_fee_transient_daily=Decimal(str(s.get("utility_fee_transient_daily", 0))),
                repair_service_revenue_per_occupied_day=Decimal(str(s.get("repair_service_revenue_per_occupied_day", 0))),
                retail_fnb_revenue_per_occupied_day=Decimal(str(s.get("retail_fnb_revenue_per_occupied_day", 0))),
                storage_fee_per_month=Decimal(str(s.get("storage_fee_per_month", 0))),
                launch_fee_per_transient_arrival=Decimal(str(s.get("launch_fee_per_transient_arrival", 0))),
                avg_transient_stay_days=Decimal(str(s.get("avg_transient_stay_days", "2.0"))),
                base_annual_occupancy=Decimal(str(s.get("base_annual_occupancy", "0.95"))),
                base_seasonal_occupancy=Decimal(str(s.get("base_seasonal_occupancy", "0.70"))),
                base_transient_capture=Decimal(str(s.get("base_transient_capture", "0.55"))),
            )

        slips = tuple(_parse_slip_class(s) for s in data["slip_classes"])
        demand_data = data.get("demand", {})
        demand = MarinaDemandModelInput(
            monthly_seasonality=tuple(Decimal(str(v)) for v in demand_data.get("monthly_seasonality", MARINA_MONTHLY_SEASONALITY)),
            monthly_weather_shock_pct=tuple(Decimal(str(v)) for v in demand_data.get("monthly_weather_shock_pct", [0]*12)),
            seasonal_active_months=tuple(demand_data.get("seasonal_active_months", [4,5,6,7,8,9,10])),
            annual_churn_pct=Decimal(str(demand_data.get("annual_churn_pct", "0.12"))),
            seasonal_churn_pct=Decimal(str(demand_data.get("seasonal_churn_pct", "0.15"))),
            seasonal_replacement_pct=Decimal(str(demand_data.get("seasonal_replacement_pct", "0.50"))),
            waitlist_start_count=Decimal(str(demand_data.get("waitlist_start_count", "20"))),
            waitlist_conversion_pct=Decimal(str(demand_data.get("waitlist_conversion_pct", "0.55"))),
            waitlist_new_demand_per_year=Decimal(str(demand_data.get("waitlist_new_demand_per_year", "8"))),
            annual_reprice_growth_pct=Decimal(str(demand_data.get("annual_reprice_growth_pct", "0.03"))),
            seasonal_reprice_growth_pct=Decimal(str(demand_data.get("seasonal_reprice_growth_pct", "0.035"))),
            transient_reprice_growth_pct=Decimal(str(demand_data.get("transient_reprice_growth_pct", "0.03"))),
            ancillary_growth_pct=Decimal(str(demand_data.get("ancillary_growth_pct", "0.03"))),
            repricing_churn_sensitivity=Decimal(str(demand_data.get("repricing_churn_sensitivity", "0.20"))),
            transient_weather_sensitivity=Decimal(str(demand_data.get("transient_weather_sensitivity", "1.0"))),
            vacancy_collection_loss_pct=Decimal(str(demand_data.get("vacancy_collection_loss_pct", "0.00"))),
            management_fee_pct=Decimal(str(demand_data.get("management_fee_pct", "0.00"))),
        )
        additional_revenue = tuple(
            MarinaAdditionalRevenueLineInput(
                name=line["name"],
                annual_fixed=Decimal(str(line["annual_fixed"])),
                per_occupied_day=Decimal(str(line.get("per_occupied_day", 0))),
                growth_pct=Decimal(str(line.get("growth_pct", "0.03"))),
            )
            for line in data.get("additional_revenue_lines", [])
        )
        opex = tuple(
            MarinaOperatingCostLineInput(
                name=line["name"],
                annual_fixed=Decimal(str(line["annual_fixed"])),
                per_occupied_day=Decimal(str(line.get("per_occupied_day", 0))),
                growth_pct=Decimal(str(line.get("growth_pct", "0.03"))),
            )
            for line in data.get("operating_cost_lines", [])
        )
        cyclical = tuple(
            MarinaCyclicalCostInput(
                name=c["name"],
                base_amount=Decimal(str(c["base_amount"])),
                first_year=c["first_year"],
                every_n_years=c["every_n_years"],
                growth_pct=Decimal(str(c.get("growth_pct", "0.02"))),
                probability_pct=Decimal(str(c.get("probability_pct", "1.0"))),
                treat_as_capex=c.get("treat_as_capex", False),
            )
            for c in data.get("cyclical_costs", [])
        )
        legal_data = data.get("legal_tenure", {})
        remaining_lease_years_raw = legal_data.get("remaining_lease_years")
        legal = MarinaLegalTenureInput(
            tenure_type=legal_data.get("tenure_type", "fee_simple"),
            annual_ground_lease=Decimal(str(legal_data.get("annual_ground_lease", 0))),
            ground_lease_growth_pct=Decimal(str(legal_data.get("ground_lease_growth_pct", "0.02"))),
            annual_submerged_land_lease=Decimal(str(legal_data.get("annual_submerged_land_lease", 0))),
            submerged_land_lease_growth_pct=Decimal(str(legal_data.get("submerged_land_lease_growth_pct", "0.02"))),
            annual_permit_concession_fees=Decimal(str(legal_data.get("annual_permit_concession_fees", 0))),
            permit_growth_pct=Decimal(str(legal_data.get("permit_growth_pct", "0.02"))),
            remaining_lease_years=int(remaining_lease_years_raw) if remaining_lease_years_raw is not None else None,
            lease_extension_probability=Decimal(str(legal_data.get("lease_extension_probability", "0.70"))),
            reversion_value_loss_pct=Decimal(str(legal_data.get("reversion_value_loss_pct", "1.00"))),
            expiry_warning_horizon_years=int(legal_data.get("expiry_warning_horizon_years", 5)),
        )
        capex = tuple(
            MarinaCapexLifecycleInput(
                name=c["name"],
                asset_type=c["asset_type"],
                base_amount=Decimal(str(c["base_amount"])),
                first_year=c["first_year"],
                every_n_years=c["every_n_years"],
                growth_pct=Decimal(str(c.get("growth_pct", "0.02"))),
                deferred_maintenance_catchup_year=c.get("deferred_maintenance_catchup_year"),
                deferred_maintenance_amount=Decimal(str(c.get("deferred_maintenance_amount", 0))),
            )
            for c in data.get("capex_lifecycle", [])
        )
        val_data = data.get("valuation", {})
        hold_years = val_data.get("hold_years", max(1, (property_.analysis_period_months + 11) // 12))
        total_slips = sum(s.count for s in slips)
        purchase_price = Decimal(str(val_data.get("initial_purchase_price", total_slips * 60000)))

        debt = None
        if valuation.loan_amount is not None and valuation.loan_amount > Decimal(0):
            debt = MarinaDebtInput(
                loan_amount=valuation.loan_amount,
                interest_rate=valuation.interest_rate or Decimal("0.0675"),
                amortization_months=valuation.amortization_months or 300,
                term_months=valuation.loan_term_months or hold_years * 12,
                io_period_months=valuation.io_period_months or 0,
            )

        fuel_data = data.get("fuel_dock", {})
        fuel_dock = MarinaFuelDockInput(
            enabled=fuel_data.get("enabled", True),
            fuel_sales_per_occupied_day=Decimal(str(fuel_data.get("fuel_sales_per_occupied_day", "25"))),
            fuel_margin_pct=Decimal(str(fuel_data.get("fuel_margin_pct", "0.22"))),
            annual_growth_pct=Decimal(str(fuel_data.get("annual_growth_pct", "0.02"))),
        )

        return MarinaModelInput(
            as_of_date=analysis_start,
            slip_classes=slips,
            demand=demand,
            additional_revenue_lines=additional_revenue,
            operating_cost_lines=opex,
            cyclical_costs=cyclical,
            legal_tenure=legal,
            capex_lifecycle=capex,
            valuation=MarinaValuationInput(
                hold_years=hold_years,
                discount_rate=valuation.discount_rate,
                exit_cap_rate=valuation.exit_cap_rate,
                exit_costs_pct=valuation.exit_costs_pct,
                use_mid_year_convention=valuation.use_mid_year_convention,
                terminal_noi_growth_pct=Decimal(str(val_data.get("terminal_noi_growth_pct", "0.02"))),
                dock_replacement_reserve_per_slip_year=Decimal(str(val_data.get("dock_replacement_reserve_per_slip_year", "220"))),
                reserve_growth_pct=Decimal(str(val_data.get("reserve_growth_pct", "0.03"))),
                initial_purchase_price=purchase_price,
                levered_discount_rate=(
                    Decimal(str(val_data["levered_discount_rate"]))
                    if val_data.get("levered_discount_rate") else None
                ),
            ),
            fuel_dock=fuel_dock,
            debt=debt,
        )

    def _build_marina_annual_cash_flows(
        self,
        result: MarinaValuationResult,
        analysis_start: date,
    ) -> list[AnnualCashFlowSummary]:
        rows: list[AnnualCashFlowSummary] = []
        for idx, row in enumerate(result.annual_cash_flows):
            period_start = add_months(analysis_start, idx * 12)
            period_end = add_months(period_start, 12) - timedelta(days=1)
            rent_revenue = (
                row.annual_contract_revenue
                + row.seasonal_contract_revenue
                + row.transient_revenue
            )
            ancillary_income = (
                row.utility_service_revenue
                + row.fuel_margin_revenue
                + row.repair_service_revenue
                + row.retail_fnb_revenue
                + row.storage_revenue
                + row.launch_fee_revenue
                + row.additional_revenue
            )
            total_operating_costs = (
                row.operating_expenses + row.management_fee
                + row.legal_tenure_costs + row.cyclical_opex
            )
            rows.append(
                AnnualCashFlowSummary(
                    year=row.year,
                    period_start=period_start,
                    period_end=period_end,
                    gross_potential_rent=rent_revenue,
                    free_rent=Decimal(0),
                    absorption_vacancy=Decimal(0),
                    loss_to_lease=Decimal(0),
                    expense_recoveries=Decimal(0),
                    percentage_rent=Decimal(0),
                    other_income=ancillary_income,
                    gross_potential_income=row.potential_gross_revenue,
                    general_vacancy_loss=-row.vacancy_collection_loss,
                    credit_loss=Decimal(0),
                    effective_gross_income=row.effective_gross_income,
                    operating_expenses=-total_operating_costs,
                    expense_detail={"marina_operating_costs": -total_operating_costs},
                    other_income_detail={
                        "per_slip_ancillary": ancillary_income - row.additional_revenue,
                        "additional_revenue": row.additional_revenue,
                    },
                    net_operating_income=row.noi,
                    tenant_improvements=Decimal(0),
                    leasing_commissions=Decimal(0),
                    capital_reserves=-row.reserve_costs,
                    building_improvements=-row.capex,
                    cash_flow_before_debt=row.cash_flow_before_debt,
                    debt_service=-row.debt_service,
                    levered_cash_flow=row.levered_cash_flow,
                )
            )
        return rows

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
        analysis_start: date,
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
        walt = self._compute_walt(suites, leases, analysis_start)
        key_metrics = self._build_key_metrics(valuation, result, annual_cfs, walt)
        expiration_schedule = self._build_expiration_schedule(
            suites, leases, property_, analysis_start
        )
        rent_roll = self._build_rent_roll(suites, leases, analysis_start)

        return ValuationRunResponse(
            valuation_id=valuation.id,
            status=valuation.status,
            key_metrics=key_metrics,
            annual_cash_flows=annual_cfs,
            tenant_cash_flows=tenant_cfs,
            recovery_audit=self._build_recovery_audit(result, suites),
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
        self, valuation: Valuation, annual_cfs: list, walt: Decimal | None = None
    ) -> KeyMetricsSummary | None:
        if valuation.result_npv is None:
            return None
        terminal_value = valuation.result_exit_value or Decimal(0)
        y1 = annual_cfs[0] if annual_cfs else None
        return KeyMetricsSummary(
            npv=valuation.result_npv or Decimal(0),
            irr=valuation.result_irr,
            going_in_cap_rate=valuation.result_going_in_cap_rate or Decimal(0),
            exit_cap_rate=valuation.exit_cap_rate,
            terminal_value=terminal_value,
            pv_of_cash_flows=valuation.result_pv_cash_flows or Decimal(0),
            pv_of_terminal_value=valuation.result_pv_terminal_value or Decimal(0),
            equity_multiple=valuation.result_equity_multiple,
            avg_occupancy_pct=valuation.result_avg_occupancy_pct or Decimal(0),
            weighted_avg_lease_term_years=walt,
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

    def _build_recovery_audit(self, result, suites: list[Suite]) -> list[TenantRecoveryAuditEntry]:
        suite_name_map = {s.id: s.suite_name for s in suites}
        rows: list[TenantRecoveryAuditEntry] = []
        for row in result.recovery_audit:
            rows.append(
                TenantRecoveryAuditEntry(
                    year=row.year,
                    period_start=row.period_start,
                    period_end=row.period_end,
                    suite_id=row.suite_id,
                    suite_name=suite_name_map.get(row.suite_id, row.suite_id),
                    lease_id=row.lease_id,
                    tenant_name=row.tenant_name,
                    expense_category=row.expense_category,
                    recovery_type=row.recovery_type,
                    annual_expense_before_gross_up=row.annual_expense_before_gross_up,
                    annual_expense_after_gross_up=row.annual_expense_after_gross_up,
                    actual_occupancy_pct=row.actual_occupancy_pct,
                    gross_up_reference_occupancy_pct=row.gross_up_reference_occupancy_pct,
                    gross_up_factor=row.gross_up_factor,
                    pro_rata_share_pct=row.pro_rata_share_pct,
                    base_year_stop_amount=row.base_year_stop_amount,
                    expense_stop_per_sf=row.expense_stop_per_sf,
                    cap_per_sf_annual=row.cap_per_sf_annual,
                    floor_per_sf_annual=row.floor_per_sf_annual,
                    admin_fee_pct=row.admin_fee_pct,
                    annual_recovery_before_proration=row.annual_recovery_before_proration,
                    monthly_recovery_before_free_rent=row.monthly_recovery_before_free_rent,
                    proration_factor=row.proration_factor,
                    is_recovery_free_rent_abatement=row.is_recovery_free_rent_abatement,
                    monthly_recovery_after_free_rent=row.monthly_recovery_after_free_rent,
                    scenario_weight=row.scenario_weight,
                    weighted_monthly_recovery=row.weighted_monthly_recovery,
                )
            )
        return rows

    def _build_rent_roll(
        self, suites: list[Suite], leases: list[Lease], analysis_start: date
    ) -> list[RentRollEntry]:
        lease_by_suite: dict[str, Lease | None] = {s.id: None for s in suites}
        today = analysis_start
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
        self,
        suites: list[Suite],
        leases: list[Lease],
        property_: Property,
        analysis_start: date,
    ) -> list[LeaseExpirationEntry]:
        from collections import defaultdict
        analysis_end = add_months(analysis_start, property_.analysis_period_months) - timedelta(days=1)

        by_year: dict[int, list[Lease]] = defaultdict(list)
        suite_area: dict[str, Decimal] = {s.id: s.area for s in suites}
        total_area = sum(suite_area.values())

        for lease in leases:
            if analysis_start <= lease.lease_end_date <= analysis_end:
                analysis_year = self._analysis_year_number(
                    analysis_start,
                    lease.lease_end_date,
                )
                by_year[analysis_year].append(lease)

        result = []
        for year in sorted(by_year.keys()):
            year_leases = by_year[year]
            area = sum(suite_area.get(l.suite_id, Decimal(0)) for l in year_leases)
            weighted_sum = Decimal(0)
            weighted_area = Decimal(0)
            for l in year_leases:
                if l.base_rent_per_unit:
                    l_area = suite_area.get(l.suite_id, Decimal(0))
                    weighted_sum += l.base_rent_per_unit * l_area
                    weighted_area += l_area
            avg_rent = weighted_sum / weighted_area if weighted_area > 0 else Decimal(0)
            result.append(LeaseExpirationEntry(
                year=year,
                expiring_leases=len(year_leases),
                expiring_area=area,
                pct_of_total_gla=area / total_area if total_area > 0 else Decimal(0),
                weighted_avg_rent_per_sf=avg_rent,
            ))
        return result

    def _analysis_year_number(self, analysis_start: date, d: date) -> int:
        """Map a date into analysis-year buckets anchored to analysis_start."""
        year = 1
        start = analysis_start
        while d > (add_months(start, 12) - timedelta(days=1)):
            year += 1
            start = add_months(start, 12)
        return year

    def _effective_analysis_start_date(self, valuation: Valuation, property_: Property) -> date:
        return valuation.analysis_start_date_override or property_.analysis_start_date
