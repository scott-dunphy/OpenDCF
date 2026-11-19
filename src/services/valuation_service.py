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
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

import src.engine
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
from src.engine.seniors_housing import (
    _build_debt_service as sh_build_debt_service,
    AncillaryRevenueInput as SHAncillaryInput,
    CapexInput as SHCapexInput,
    CareLevelTier as SHCareLevelTier,
    DebtInput as SHDebtInput,
    ExpenseLineInput as SHExpenseInput,
    OccupancyRampInput as SHRampInput,
    SeniorsHousingModelInput as SHModelInput,
    SeniorsHousingValuationResult as SHValuationResult,
    SNFPayerMixInput as SHSNFPayerInput,
    UnitTypeInput as SHUnitTypeInput,
    ValuationAssumptions as SHValuationAssumptions,
    run_seniors_housing_valuation,
)
from src.engine.lease_projector import _current_rent
from src.engine.property_cashflow import run_valuation
from src.engine.self_storage import run_self_storage
from src.engine.dcf import (
    calculate_terminal_value_breakdown,
    discount_cash_flows,
    discount_monthly_cash_flows,
)
from src.engine.returns import SensitivityGrid, compute_investment_returns
from src.engine.types import (
    RecoveryPoolInput,
    rent_area,
    CapitalProjectInput,
    ExpenseInput,
    OtherIncomeInput,
    ExpenseRecoveryOverride,
    FreeRentPeriodInput,
    LeaseInput,
    MarketAssumptions,
    RentStepInput,
    SuiteInput,
    LoanParams,
    ValuationParams,
)
from src.models.expense import PropertyExpense
from src.models.lease import Lease
from src.models.market import MarketLeasingProfile
from src.models.recovery_pool import RecoveryPool
from src.models.recovery_structure import RecoveryStructure
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.schemas.cashflow import (
    AnnualCashFlowSummary,
    InvestmentReturnsSummary,
    KeyMetricsSummary,
    LeaseExpirationEntry,
    NcreifForecast,
    RentRollEntry,
    SensitivityMatrix,
    SlipClassRevenueSummary,
    TenantCashFlowDetail,
    TenantRecoveryAuditEntry,
    ValuationRunResponse,
    WhatIfResult,
)
from src.services.ncreif_performance import forecast_ncreif_returns
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


@dataclass
class EngineInputs:
    """Everything run_valuation needs for one property, plus the source DB rows."""
    suites_db: list
    leases_db: list
    analysis_start: date
    analysis_period_months: int
    fiscal_year_end_month: int
    property_type: str
    suites: list[SuiteInput]
    leases: list[LeaseInput]
    market: dict[str, MarketAssumptions]
    expenses: list[ExpenseInput]
    params: ValuationParams
    capital_projects: list[CapitalProjectInput]
    other_income: list[OtherIncomeInput]
    cpi_assumption: Decimal = Decimal("0.025")
    cpi_schedule: tuple[Decimal, ...] = ()
    recovery_pools: tuple[RecoveryPoolInput, ...] = ()

    def run(self, include_monthly: bool = False):
        return run_valuation(
            property_start_date=self.analysis_start,
            analysis_period_months=self.analysis_period_months,
            fiscal_year_end_month=self.fiscal_year_end_month,
            suites=self.suites,
            leases=self.leases,
            market_assumptions=self.market,
            expenses=self.expenses,
            params=self.params,
            property_type=self.property_type,
            capital_projects=self.capital_projects,
            other_income_items=self.other_income,
            cpi_assumption=self.cpi_assumption,
            cpi_schedule=self.cpi_schedule,
            include_monthly=include_monthly,
            recovery_pools=self.recovery_pools,
        )



@dataclass
class StorageEngineInputs(EngineInputs):
    """A self storage facility valued from its operating model (no suites, leases or markets)."""
    storage_model: object = None

    def run(self, include_monthly: bool = False):
        return run_self_storage(
            self.storage_model,
            self.analysis_start,
            self.analysis_period_months,
            self.fiscal_year_end_month,
            self.expenses,
            self.params,
            capital_projects=self.capital_projects,
            other_income_items=self.other_income,
            include_monthly=include_monthly,
        )



# (valuation id, last run, valuation edit, property inputs edit) -> (params, engine result), oldest first
_REPRICE_RUNS: dict[tuple, tuple] = {}


def _naive_dt(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


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

            if property_.property_type == "seniors_housing":
                return await self._execute_seniors_housing_valuation(valuation, property_)

            inputs = await self.build_engine_inputs(valuation, property_)
            suites, leases = inputs.suites_db, inputs.leases_db
            analysis_start = inputs.analysis_start
            result = inputs.run()

            # Build tenant CFs before persist (needed for JSON serialization)
            tenant_cfs = self._build_tenant_cash_flows(result, leases)
            recovery_audit = self._build_recovery_audit(result, suites)

            # Persist results
            valuation.status = ValuationStatus.COMPLETED.value
            valuation.last_run_at = datetime.now(timezone.utc)
            valuation.result_engine_version = src.engine.ENGINE_VERSION
            valuation.error_message = None
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
            valuation.result_terminal_capital_deduction_amount = result.terminal_capital_deduction_amount
            valuation.result_direct_cap_value = result.direct_cap_value
            returns = self._returns_summary(result.returns)
            valuation.result_levered_irr = returns.levered_irr if returns else None
            valuation.result_returns_json = returns.model_dump_json() if returns else None
            valuation.result_cash_flows_json = json.dumps(
                self._with_storage_detail(
                    [self._serialize_annual_cf(cf) for cf in result.annual_cash_flows], result
                )
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
            # Discard anything half-written (or a failed commit) before recording the failure
            await self.db.rollback()
            await self.db.refresh(valuation)
            valuation.status = ValuationStatus.FAILED.value
            valuation.error_message = str(exc)
            await self.db.commit()
            raise

    async def build_engine_inputs(self, valuation: Valuation, property_: Property) -> "EngineInputs":
        """Load a valuation's model and convert it to engine inputs."""
        if property_.property_type == "self_storage" and valuation.self_storage_assumptions_json:
            return await self._storage_engine_inputs(valuation, property_)
        suites = await self._load_suites(valuation.id)
        leases = await self._load_all_leases(valuation.id)
        market_profiles = await self._load_market_profiles(valuation.id)
        structures = await self._load_recovery_structures(valuation.id)
        expenses = await self._load_expenses(valuation.id)
        cap_projects = await self._load_capital_projects(valuation.id)
        oi_items = await self._load_other_income(valuation.id)

        rent_freq = "monthly" if property_.area_unit == "unit" else "annual"
        profile_types = {m.id: m.space_type for m in market_profiles}
        lease_inputs = [self._to_lease_input(l) for l in leases]
        if property_.property_type in ("multifamily", "self_storage"):
            # Residents and storage tenants pay no recoveries (the form hides them, and market
            # occupancy after expiry has none), whatever type the lease was saved with
            lease_inputs = [replace(l, recovery_type="none", recovery_overrides=()) for l in lease_inputs]
        return EngineInputs(
            suites_db=suites,
            leases_db=leases,
            analysis_start=self._effective_analysis_start_date(valuation, property_),
            analysis_period_months=self._effective_period_months(valuation, property_),
            fiscal_year_end_month=property_.fiscal_year_end_month,
            property_type=property_.property_type,
            suites=[self._to_suite_input(s) for s in suites],
            leases=lease_inputs,
            market={
                m.space_type: self._to_market_assumptions(
                    m, rent_freq, next_space_type=profile_types.get(m.next_profile_id or ""),
                    recovery_structure=structures.get(m.recovery_structure_id or ""),
                )
                for m in market_profiles
            },
            expenses=[self._to_expense_input(e, property_.total_area) for e in expenses],
            params=self._to_valuation_params(valuation, property_),
            capital_projects=[self._to_capital_project_input(cp) for cp in cap_projects],
            other_income=[self._to_other_income_input(oi) for oi in oi_items],
            cpi_assumption=valuation.cpi_rate if valuation.cpi_rate is not None else Decimal("0.025"),
            cpi_schedule=tuple(valuation.cpi_schedule or ()),
            recovery_pools=await self._load_recovery_pools(valuation.id),
        )

    async def _storage_engine_inputs(self, valuation: Valuation, property_: Property) -> StorageEngineInputs:
        """Engine inputs for a self storage operating model; expenses, capital and other income
        come from the valuation's usual tables."""
        from src.schemas.self_storage import parse_storage_model

        expenses = await self._load_expenses(valuation.id)
        cap_projects = await self._load_capital_projects(valuation.id)
        oi_items = await self._load_other_income(valuation.id)
        return StorageEngineInputs(
            suites_db=[],
            leases_db=[],
            analysis_start=self._effective_analysis_start_date(valuation, property_),
            analysis_period_months=self._effective_period_months(valuation, property_),
            fiscal_year_end_month=property_.fiscal_year_end_month,
            property_type=property_.property_type,
            suites=[],
            leases=[],
            market={},
            expenses=[self._to_expense_input(e, property_.total_area) for e in expenses],
            params=self._to_valuation_params(valuation, property_),
            capital_projects=[self._to_capital_project_input(cp) for cp in cap_projects],
            other_income=[self._to_other_income_input(oi) for oi in oi_items],
            cpi_assumption=valuation.cpi_rate if valuation.cpi_rate is not None else Decimal("0.025"),
            cpi_schedule=tuple(valuation.cpi_schedule or ()),
            storage_model=parse_storage_model(valuation.self_storage_assumptions_json),
        )

    async def get_results(
        self, valuation_id: str, include_recovery_audit: bool = True
    ) -> ValuationRunResponse | None:
        """Return cached results for a completed valuation.

        The recovery audit can hold ~100k rows; callers that don't return it skip parsing it.
        """
        valuation = await self._load_valuation(valuation_id)
        if valuation is None:
            return None
        columns = ("results_json", "recovery_audit_json") if include_recovery_audit else ("results_json",)
        snapshot = await self._frozen_snapshot(valuation, *columns)
        if snapshot is not None:
            # Exactly what was reviewed, whatever has changed in the live model since
            response = ValuationRunResponse.model_validate_json(snapshot.results_json)
            if include_recovery_audit and snapshot.recovery_audit_json:
                response.recovery_audit = [
                    TenantRecoveryAuditEntry(**row) for row in json.loads(snapshot.recovery_audit_json)
                ]
            return response
        if valuation.status != ValuationStatus.COMPLETED.value:
            return ValuationRunResponse(
                valuation_id=valuation_id,
                status=valuation.status,
                error_message=valuation.error_message,
            )

        property_ = await self._load_property(valuation.property_id)
        suites = await self._load_suites(valuation.id)
        leases = await self._load_all_leases(valuation.id)
        if property_ is not None and property_.property_type == "self_storage" and valuation.self_storage_assumptions_json:
            suites, leases = [], []  # valued from the unit mix; any old rent roll is not part of it

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
        self._attach_current_rent(tenant_cfs, leases, valuation)
        recovery_audit = []
        if include_recovery_audit and valuation.result_recovery_audit_json:
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
                self._build_expiration_schedule(
                    suites, leases, self._effective_period_months(valuation, property_), analysis_start
                )
                if property_ is not None and analysis_start is not None
                else []
            ),
        )

    async def _execute_marina_valuation(
        self, valuation: Valuation, property_: Property
    ) -> ValuationRunResponse:
        analysis_start = self._effective_analysis_start_date(valuation, property_)
        if self._operating_model_json(valuation, property_, "marina"):
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
        valuation.last_run_at = datetime.now(timezone.utc)
        valuation.result_engine_version = src.engine.ENGINE_VERSION
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

    async def _execute_seniors_housing_valuation(
        self, valuation: Valuation, property_: Property
    ) -> ValuationRunResponse:
        analysis_start = self._effective_analysis_start_date(valuation, property_)
        model_json = self._operating_model_json(valuation, property_, "seniors_housing")
        if not model_json:
            raise ValueError("Add the community's unit mix and operating model on the property before running")

        data = json.loads(model_json)
        v = data.get("valuation", {})

        unit_types = tuple(
            SHUnitTypeInput(
                name=ut["name"],
                acuity=ut["acuity"],
                unit_type=ut["unit_type"],
                count=int(ut["count"]),
                avg_sf=Decimal(str(ut.get("avg_sf", 0))),
                monthly_base_fee=Decimal(str(ut.get("monthly_base_fee", 0))),
                second_person_fee_monthly=Decimal(str(ut.get("second_person_fee_monthly", 0))),
                second_person_pct=Decimal(str(ut.get("second_person_pct", 0))),
                community_fee=Decimal(str(ut.get("community_fee", 0))),
                avg_length_of_stay_months=Decimal(str(ut.get("avg_length_of_stay_months", 24))),
                stabilized_occupancy=Decimal(str(ut.get("stabilized_occupancy", "0.90"))),
                annual_turnover_rate=Decimal(str(ut.get("annual_turnover_rate", "0.40"))),
                care_level_tiers=tuple(
                    SHCareLevelTier(
                        name=t["name"],
                        monthly_surcharge=Decimal(str(t["monthly_surcharge"])),
                        pct_of_residents=Decimal(str(t["pct_of_residents"])),
                    )
                    for t in ut.get("care_level_tiers", [])
                ),
            )
            for ut in data.get("unit_types", [])
        )
        snf_payer = tuple(
            SHSNFPayerInput(
                payer=p["payer"],
                pct_of_days=Decimal(str(p["pct_of_days"])),
                daily_rate=Decimal(str(p["daily_rate"])),
                annual_rate_growth=Decimal(str(p.get("annual_rate_growth", "0.02"))),
            )
            for p in data.get("snf_payer_mix", [])
        )
        ancillary = tuple(
            SHAncillaryInput(
                name=a["name"],
                annual_fixed=Decimal(str(a.get("annual_fixed", 0))),
                per_occupied_unit_month=Decimal(str(a.get("per_occupied_unit_month", 0))),
                growth_pct=Decimal(str(a.get("growth_pct", "0.03"))),
                applies_to_acuity=tuple(a.get("applies_to_acuity", [])),
            )
            for a in data.get("ancillary_revenue", [])
        )
        expenses = tuple(
            SHExpenseInput(
                name=e["name"],
                category=e["category"],
                annual_fixed=Decimal(str(e.get("annual_fixed", 0))),
                per_occupied_unit_month=Decimal(str(e.get("per_occupied_unit_month", 0))),
                pct_of_revenue=Decimal(str(e.get("pct_of_revenue", 0))),
                growth_pct=Decimal(str(e["growth_pct"])) if e.get("growth_pct") is not None else None,
                is_variable=e.get("is_variable", True),
                applies_to_acuity=tuple(e.get("applies_to_acuity", [])),
            )
            for e in data.get("expenses", [])
        )
        capex = tuple(
            SHCapexInput(
                name=c["name"],
                annual_per_unit=Decimal(str(c.get("annual_per_unit", 0))),
                annual_fixed=Decimal(str(c.get("annual_fixed", 0))),
                growth_pct=Decimal(str(c.get("growth_pct", "0.03"))),
            )
            for c in data.get("capex", [])
        )

        hold_years = self._hold_years(valuation, property_, v.get("hold_years"))
        # The valuation's own price wins; the operating model's is a legacy fallback
        purchase_price = valuation.purchase_price or (
            Decimal(str(v["initial_purchase_price"]))
            if v.get("initial_purchase_price") is not None
            else None
        )

        debt = None
        if (
            valuation.loan_amount is not None
            and valuation.loan_amount > Decimal(0)
            and valuation.interest_rate is not None
        ):
            debt = SHDebtInput(
                loan_amount=valuation.loan_amount,
                interest_rate=valuation.interest_rate,
                amortization_months=valuation.amortization_months,
                term_months=valuation.loan_term_months,
                io_period_months=valuation.io_period_months or 0,
            )
        ramp = None
        ramp_data = data.get("occupancy_ramp")
        if ramp_data is not None:
            ramp = SHRampInput(
                start_occupancy=Decimal(str(ramp_data.get("start_occupancy", "0.30"))),
                monthly_absorption_units=Decimal(str(ramp_data.get("monthly_absorption_units", "5"))),
                stabilization_month=(
                    int(ramp_data["stabilization_month"])
                    if ramp_data.get("stabilization_month") is not None
                    else None
                ),
            )

        sh_model = SHModelInput(
            as_of_date=analysis_start,
            community_name=data.get("community_name", property_.name),
            unit_types=unit_types,
            snf_payer_mix=snf_payer,
            ancillary_revenue=ancillary,
            expenses=expenses,
            capex=capex,
            valuation=SHValuationAssumptions(
                hold_years=hold_years,
                discount_rate=valuation.discount_rate,
                exit_cap_rate=valuation.exit_cap_rate,
                exit_costs_pct=(
                    valuation.exit_costs_pct
                    if valuation.exit_costs_pct is not None
                    else Decimal("0.02")
                ),
                use_mid_year_convention=valuation.use_mid_year_convention or False,
                terminal_noi_growth_pct=Decimal(str(v.get("terminal_noi_growth_pct", "0.02"))),
                fee_growth_rate=Decimal(str(v.get("fee_growth_rate", "0.04"))),
                expense_growth_rate=Decimal(str(v.get("expense_growth_rate", "0.035"))),
                initial_purchase_price=purchase_price,
                levered_discount_rate=(
                    Decimal(str(v["levered_discount_rate"]))
                    if v.get("levered_discount_rate") is not None
                    else None
                ),
            ),
            occupancy_ramp=ramp,
            debt=debt,
        )

        result = run_seniors_housing_valuation(sh_model)
        annual_cfs = self._build_sh_annual_cash_flows(result, analysis_start)

        is_levered = (
            sh_model.debt is not None
            and sh_model.debt.loan_amount is not None
            and sh_model.debt.loan_amount > Decimal(0)
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

        going_in_cap_rate = result.going_in_cap_rate or Decimal(0)
        avg_occ = (
            sum((r.avg_occupancy_pct for r in result.annual_cash_flows), Decimal(0))
            / Decimal(str(len(result.annual_cash_flows)))
            if result.annual_cash_flows else Decimal(0)
        )

        equity_multiple = None
        if purchase_price and purchase_price > Decimal(0):
            if is_levered:
                debt_amount = sh_model.debt.loan_amount if sh_model.debt else Decimal(0)
                equity_invested = purchase_price - (debt_amount or Decimal(0))
                _, _, debt_balances = sh_build_debt_service(sh_model.debt, hold_years)
                exit_loan_balance = debt_balances[-1] if debt_balances else Decimal(0)
                levered_terminal = result.terminal_value_net - exit_loan_balance
                total_cfs = sum((cf.levered_cash_flow for cf in annual_cfs), Decimal(0))
                equity_multiple = (
                    (total_cfs + levered_terminal) / equity_invested
                    if equity_invested > Decimal(0)
                    else None
                )
            else:
                total_cfs = sum((cf.cash_flow_before_debt for cf in annual_cfs), Decimal(0))
                equity_multiple = (total_cfs + result.terminal_value_net) / purchase_price

        valuation.status = ValuationStatus.COMPLETED.value
        valuation.last_run_at = datetime.now(timezone.utc)
        valuation.result_engine_version = src.engine.ENGINE_VERSION
        valuation.error_message = None
        valuation.result_npv = npv
        valuation.result_irr = irr
        valuation.result_going_in_cap_rate = going_in_cap_rate
        valuation.result_exit_value = result.terminal_value_net
        valuation.result_pv_cash_flows = pv_cash_flows
        valuation.result_pv_terminal_value = pv_terminal
        valuation.result_equity_multiple = equity_multiple
        valuation.result_avg_occupancy_pct = avg_occ
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

    def _build_sh_annual_cash_flows(
        self, result: SHValuationResult, analysis_start: date
    ) -> list[AnnualCashFlowSummary]:
        rows: list[AnnualCashFlowSummary] = []
        for idx, row in enumerate(result.annual_cash_flows):
            period_start = add_months(analysis_start, idx * 12)
            period_end = add_months(period_start, 12) - timedelta(days=1)

            other_income = (
                row.care_level_revenue + row.second_person_revenue
                + row.community_fee_revenue + row.snf_payer_revenue
                + row.ancillary_revenue
            )

            rows.append(AnnualCashFlowSummary(
                year=row.year,
                period_start=period_start,
                period_end=period_end,
                gross_potential_rent=row.base_rent_revenue,
                free_rent=Decimal(0),
                absorption_vacancy=Decimal(0),
                loss_to_lease=Decimal(0),
                expense_recoveries=Decimal(0),
                percentage_rent=Decimal(0),
                other_income=other_income,
                gross_potential_income=row.potential_gross_revenue,
                general_vacancy_loss=Decimal(0),
                credit_loss=Decimal(0),
                effective_gross_income=row.effective_gross_income,
                operating_expenses=-row.total_operating_expenses,
                expense_detail={
                    "labor": -row.total_labor,
                    "food_dietary": -row.total_food_dietary,
                    "insurance": -row.total_insurance,
                    "marketing": -row.total_marketing,
                    "utilities": -row.total_utilities,
                    "property_tax": -row.total_property_tax,
                    "medical_supplies": -row.total_medical_supplies,
                    "management_fee": -row.management_fee,
                    "other": -row.total_other_expenses,
                },
                other_income_detail={
                    "ancillary_revenue": row.ancillary_revenue,
                    "care_level_revenue": row.care_level_revenue,
                    "second_person_revenue": row.second_person_revenue,
                    "community_fee_revenue": row.community_fee_revenue,
                    "snf_payer_revenue": row.snf_payer_revenue,
                },
                net_operating_income=row.noi,
                tenant_improvements=Decimal(0),
                leasing_commissions=Decimal(0),
                capital_reserves=-row.total_capex,
                cash_flow_before_debt=row.cash_flow_before_debt,
                debt_service=-row.debt_service if row.debt_service else Decimal(0),
                balloon_payment=-row.balloon_payment if row.balloon_payment else Decimal(0),
                levered_cash_flow=row.levered_cash_flow,
            ))
        return rows

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

    async def _load_suites(self, valuation_id: str) -> list[Suite]:
        result = await self.db.execute(
            select(Suite).where(Suite.valuation_id == valuation_id)
        )
        return list(result.scalars().all())

    async def _load_all_leases(self, valuation_id: str) -> list[Lease]:
        """Load all leases on the valuation's suites, with sub-relationships."""
        result = await self.db.execute(
            select(Lease)
            .join(Suite, Lease.suite_id == Suite.id)
            .where(Suite.valuation_id == valuation_id)
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

    async def _load_recovery_pools(self, valuation_id: str) -> tuple[RecoveryPoolInput, ...]:
        result = await self.db.execute(
            select(RecoveryPool).where(RecoveryPool.valuation_id == valuation_id).order_by(RecoveryPool.created_at)
        )
        return tuple(
            RecoveryPoolInput(
                pool_id=p.id, name=p.name, expense_categories=tuple(p.expense_categories or ()),
                denominator=p.denominator, fixed_area=p.fixed_area,
                minimum_occupancy_pct=p.minimum_occupancy_pct,
                excluded_suite_ids=tuple(p.excluded_suite_ids or ()),
                deduct_excluded_recoveries=p.deduct_excluded_recoveries,
            )
            for p in result.scalars()
        )

    async def _load_recovery_structures(self, valuation_id: str) -> dict[str, RecoveryStructure]:
        result = await self.db.execute(
            select(RecoveryStructure)
            .where(RecoveryStructure.valuation_id == valuation_id)
            .options(selectinload(RecoveryStructure.items))
        )
        return {rs.id: rs for rs in result.scalars()}

    async def _load_market_profiles(self, valuation_id: str | None) -> list[MarketLeasingProfile]:
        """The valuation's own market leasing profiles (none for an unsaved valuation)."""
        if valuation_id is None:
            return []
        result = await self.db.execute(
            select(MarketLeasingProfile).where(MarketLeasingProfile.valuation_id == valuation_id)
        )
        return list(result.scalars().all())

    async def _load_capital_projects(self, valuation_id: str):
        from src.models.capital import PropertyCapitalProject
        result = await self.db.execute(
            select(PropertyCapitalProject).where(PropertyCapitalProject.valuation_id == valuation_id)
        )
        return list(result.scalars().all())

    async def _load_other_income(self, valuation_id: str):
        from src.models.other_income import PropertyOtherIncome
        result = await self.db.execute(
            select(PropertyOtherIncome).where(PropertyOtherIncome.valuation_id == valuation_id)
        )
        return list(result.scalars().all())

    async def _load_expenses(self, valuation_id: str) -> list[PropertyExpense]:
        result = await self.db.execute(
            select(PropertyExpense).where(PropertyExpense.valuation_id == valuation_id)
        )
        return list(result.scalars().all())

    # =========================================================================
    # Model → Engine type converters
    # =========================================================================

    def _to_suite_input(self, suite: Suite) -> SuiteInput:
        # A suite can re-lease under another space type's market profile
        return SuiteInput(
            suite_id=suite.id,
            suite_name=suite.suite_name,
            area=suite.area,
            space_type=suite.market_space_type or suite.space_type,
            absorption_start_date=suite.absorption_start_date,
            lease_up_months=suite.lease_up_months,
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
        if lease.recovery_structure:
            overrides_by_cat.update(
                (o.expense_category, o) for o in self._structure_overrides(lease.recovery_structure)
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
                cap_group=o.cap_group,
                cap_growth_pct=o.cap_growth_pct,
                expense_stop_per_sf=o.expense_stop_per_sf,
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
            rent_basis=lease.rent_basis or "per_area",
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
            # The structure governs recovery when assigned; its stop, when set, replaces the lease's
            expense_stop_per_sf=(
                lease.recovery_structure.expense_stop_per_sf
                if lease.recovery_structure and lease.recovery_structure.expense_stop_per_sf is not None
                else lease.expense_stop_per_sf
            ),
            recovery_overrides=overrides,
            pct_rent_breakpoint=lease.pct_rent_breakpoint,
            pct_rent_rate=lease.pct_rent_rate,
            renewal_probability_override=lease.renewal_probability,
            renewal_rent_spread_override=lease.renewal_rent_spread_pct,
            projected_annual_sales_per_sf=lease.projected_annual_sales_per_sf,
            exclude_from_general_vacancy=bool(lease.exclude_from_general_vacancy),
            vacancy_exclusion_ends_at_rollover=lease.vacancy_exclusion_ends_at_rollover is not False,
            prorate_rent_steps=bool(lease.prorate_rent_steps),
            upon_expiration=lease.upon_expiration or "market",
            option_rent_per_unit=lease.option_rent_per_unit,
            option_term_months=lease.option_term_months,
            option_ti_per_sf=lease.option_ti_per_sf or Decimal(0),
            option_lc_pct=lease.option_lc_pct or Decimal(0),
            committed_ti_amount=lease.committed_ti_amount or Decimal(0),
            committed_lc_amount=lease.committed_lc_amount or Decimal(0),
        )

    def _suite_area_for_lease(self, lease: Lease) -> Decimal:
        """Get the area of the suite associated with this lease."""
        if hasattr(lease, 'suite') and lease.suite is not None:
            return lease.suite.area
        return Decimal(0)

    @staticmethod
    def _structure_overrides(structure: RecoveryStructure) -> tuple[ExpenseRecoveryOverride, ...]:
        """A recovery structure's per-category rules as engine overrides."""
        return tuple(
            ExpenseRecoveryOverride(
                expense_category=item.expense_category,
                recovery_type=item.recovery_type,
                base_year_stop_amount=item.base_year_stop_amount,
                cap_per_sf_annual=item.cap_per_sf_annual,
                floor_per_sf_annual=item.floor_per_sf_annual,
                admin_fee_pct=item.admin_fee_pct,
                cap_group=item.cap_group,
                cap_growth_pct=item.cap_growth_pct,
                expense_stop_per_sf=item.expense_stop_per_sf,
            )
            for item in structure.items
        )

    def _to_market_assumptions(
        self, m: MarketLeasingProfile, rent_freq: str = "annual", next_space_type: str | None = None,
        recovery_structure: RecoveryStructure | None = None,
    ) -> MarketAssumptions:
        return MarketAssumptions(
            recovery_type=recovery_structure.default_recovery_type if recovery_structure else None,
            recovery_overrides=self._structure_overrides(recovery_structure) if recovery_structure else (),
            expense_stop_per_sf=recovery_structure.expense_stop_per_sf if recovery_structure else None,
            space_type=m.space_type,
            market_rent_per_unit=m.market_rent_per_unit,
            rent_growth_rate=m.rent_growth_rate_pct,
            rent_payment_frequency=rent_freq,
            rent_basis=m.rent_basis or "per_area",
            new_lease_term_months=m.new_lease_term_months,
            new_ti_per_sf=m.new_tenant_ti_per_sf,
            new_lc_pct=m.new_tenant_lc_pct,
            new_lc_per_sf=m.new_tenant_lc_per_sf or Decimal(0),
            new_free_rent_months=m.new_tenant_free_rent_months,
            downtime_months=m.downtime_months,
            renewal_probability=m.renewal_probability,
            renewal_term_months=m.renewal_lease_term_months,
            renewal_ti_per_sf=m.renewal_ti_per_sf,
            renewal_lc_pct=m.renewal_lc_pct,
            renewal_lc_per_sf=m.renewal_lc_per_sf or Decimal(0),
            leasing_cost_growth_rate=m.leasing_cost_growth_rate or Decimal(0),
            rollover_method=m.rollover_method or "probability_tree",
            renewal_rent_rule=m.renewal_rent_rule or "market",
            lease_escalation_pct=m.lease_escalation_pct,
            lc_includes_escalations=m.lc_includes_escalations is not False,
            new_lc_pct_by_lease_year=tuple(m.new_tenant_lc_pct_by_lease_year or ()),
            renewal_lc_pct_by_lease_year=tuple(m.renewal_lc_pct_by_lease_year or ()),
            lease_rent_steps=tuple((int(mo), pct) for mo, pct in (m.lease_rent_steps or ())),
            exclude_from_general_vacancy=bool(m.exclude_from_general_vacancy),
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
            rent_growth_schedule=tuple(m.rent_growth_schedule or ()),
            next_space_type=next_space_type,
            lease_escalation_per_unit=m.lease_escalation_per_unit,
            general_vacancy_schedule=tuple(m.general_vacancy_schedule or ()),
            credit_loss_schedule=tuple(m.credit_loss_schedule or ()),
            renewal_probability_schedule=tuple(m.renewal_probability_schedule or ()),
            downtime_schedule=tuple(int(d) for d in (m.downtime_schedule or ())),
            new_free_rent_schedule=tuple(m.new_free_rent_schedule or ()),
            renewal_free_rent_schedule=tuple(m.renewal_free_rent_schedule or ()),
            leasing_cost_growth_schedule=tuple(m.leasing_cost_growth_schedule or ()),
        )

    def _to_expense_input(self, e: PropertyExpense, total_area: Decimal) -> ExpenseInput:
        base_amount = e.base_year_amount
        amount_schedule = tuple(e.amount_schedule or ())
        if e.amount_basis == "per_area":
            base_amount = e.base_year_amount * total_area
            amount_schedule = tuple(a * total_area for a in amount_schedule)
        return ExpenseInput(
            expense_id=e.id,
            category=e.category,
            base_amount=base_amount,
            growth_rate=e.growth_rate_pct,
            is_recoverable=e.is_recoverable,
            is_gross_up_eligible=e.is_gross_up_eligible,
            gross_up_vacancy_pct=e.gross_up_vacancy_pct,
            is_pct_of_egi=e.is_pct_of_egi,
            pct_of_egi=e.pct_of_egi,
            growth_schedule=tuple(e.growth_schedule or ()),
            variable_pct=e.variable_pct or Decimal(0),
            amount_schedule=amount_schedule,
        )

    def _to_other_income_input(self, oi) -> OtherIncomeInput:
        return OtherIncomeInput(
            income_id=oi.id,
            category=oi.category,
            base_amount=oi.base_year_amount,
            growth_rate=oi.growth_rate_pct,
            growth_schedule=tuple(oi.growth_schedule or ()),
            amount_schedule=tuple(oi.amount_schedule or ()),
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
            capital_reserves_growth_rate=v.capital_reserves_growth_rate or Decimal(0),
            total_property_area=p.total_area,
            use_mid_year_convention=v.use_mid_year_convention,
            terminal_timing=v.terminal_timing or "end_of_period",
            loan_amount=v.loan_amount,
            interest_rate=v.interest_rate,
            amortization_months=v.amortization_months,
            loan_term_months=v.loan_term_months,
            io_period_months=v.io_period_months or 0,
            purchase_price=v.purchase_price,
            acquisition_costs_pct=v.acquisition_costs_pct or Decimal(0),
            loan_fees_pct=v.loan_fees_pct or Decimal(0),
            additional_loans=tuple(
                LoanParams(
                    loan_amount=Decimal(str(a["loan_amount"])),
                    interest_rate=Decimal(str(a["interest_rate"])),
                    amortization_months=a.get("amortization_months"),
                    loan_term_months=a.get("loan_term_months"),
                    io_period_months=a.get("io_period_months") or 0,
                    loan_fees_pct=Decimal(str(a.get("loan_fees_pct") or 0)),
                )
                for a in v.additional_loans or ()
            ),
            direct_cap_rate=v.direct_cap_rate,
            exit_deduct_forward_capital=bool(v.exit_deduct_forward_capital),
            reduce_general_vacancy_by_downtime=bool(v.reduce_general_vacancy_by_downtime),
            vacancy_calculation_frequency=v.vacancy_calculation_frequency or "annual",
            vacancy_on_gross_revenue=bool(v.vacancy_on_gross_revenue),
            credit_loss_on_tenant_revenue=bool(v.credit_loss_on_tenant_revenue),
            calendar_year_recoveries=bool(v.calendar_year_recoveries),
            exit_noi_full_occupancy=bool(v.exit_noi_full_occupancy),
            exit_stabilized_vacancy_pct=v.exit_stabilized_vacancy_pct or Decimal(0),
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
        hold_years = self._hold_years(valuation, property_)

        purchase_price = total_slips_dec * Decimal("60000")
        if valuation.loan_amount is not None and valuation.loan_amount > Decimal(0):
            purchase_price = max(purchase_price, valuation.loan_amount * Decimal("1.35"))
        if valuation.purchase_price:
            purchase_price = valuation.purchase_price

        debt = None
        if valuation.loan_amount is not None and valuation.loan_amount > Decimal(0):
            debt = MarinaDebtInput(
                loan_amount=valuation.loan_amount,
                interest_rate=(
                    valuation.interest_rate
                    if valuation.interest_rate is not None
                    else Decimal("0.0675")
                ),
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
                waitlist_start_count=waitlist_start,
                waitlist_conversion_pct=Decimal("0.55"),
                waitlist_new_demand_per_year=waitlist_new,
                annual_rate_growth_pct=Decimal("0.03"),
                seasonal_rate_growth_pct=Decimal("0.035"),
                transient_rate_growth_pct=Decimal("0.03"),
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
        data = json.loads(self._operating_model_json(valuation, property_, "marina"))

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
            seasonal_active_months=tuple(
                int(m) for m in demand_data.get("seasonal_active_months", [4, 5, 6, 7, 8, 9, 10])
            ),
            annual_occupancy_growth_pct=Decimal(str(demand_data.get("annual_occupancy_growth_pct", "0.00"))),
            seasonal_occupancy_growth_pct=Decimal(str(demand_data.get("seasonal_occupancy_growth_pct", "0.00"))),
            waitlist_start_count=Decimal(str(demand_data.get("waitlist_start_count", "20"))),
            waitlist_conversion_pct=Decimal(str(demand_data.get("waitlist_conversion_pct", "0.55"))),
            waitlist_new_demand_per_year=Decimal(str(demand_data.get("waitlist_new_demand_per_year", "8"))),
            annual_rate_growth_pct=Decimal(str(demand_data.get("annual_rate_growth_pct", "0.03"))),
            seasonal_rate_growth_pct=Decimal(str(demand_data.get("seasonal_rate_growth_pct", "0.035"))),
            transient_rate_growth_pct=Decimal(str(demand_data.get("transient_rate_growth_pct", "0.03"))),
            ancillary_growth_pct=Decimal(str(demand_data.get("ancillary_growth_pct", "0.03"))),
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
                first_year=int(c["first_year"]),
                every_n_years=int(c["every_n_years"]),
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
                first_year=int(c["first_year"]),
                every_n_years=int(c["every_n_years"]),
                growth_pct=Decimal(str(c.get("growth_pct", "0.02"))),
                deferred_maintenance_catchup_year=(
                    int(c["deferred_maintenance_catchup_year"])
                    if c.get("deferred_maintenance_catchup_year") is not None
                    else None
                ),
                deferred_maintenance_amount=Decimal(str(c.get("deferred_maintenance_amount", 0))),
            )
            for c in data.get("capex_lifecycle", [])
        )
        val_data = data.get("valuation", {})
        hold_years = self._hold_years(valuation, property_, val_data.get("hold_years"))
        total_slips = sum(s.count for s in slips)
        purchase_price = valuation.purchase_price or Decimal(
            str(val_data.get("initial_purchase_price", total_slips * 60000))
        )

        debt = None
        if valuation.loan_amount is not None and valuation.loan_amount > Decimal(0):
            debt = MarinaDebtInput(
                loan_amount=valuation.loan_amount,
                interest_rate=(
                    valuation.interest_rate
                    if valuation.interest_rate is not None
                    else Decimal("0.0675")
                ),
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
                    if val_data.get("levered_discount_rate") is not None
                    else None
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
            slip_detail = [
                SlipClassRevenueSummary(
                    slip_class_name=sc.slip_class_name,
                    kind=sc.kind,
                    count=sc.count,
                    annual_contract_revenue=sc.annual_contract_revenue,
                    seasonal_contract_revenue=sc.seasonal_contract_revenue,
                    transient_revenue=sc.transient_revenue,
                    utility_revenue=sc.utility_revenue,
                    repair_service_revenue=sc.repair_service_revenue,
                    retail_fnb_revenue=sc.retail_fnb_revenue,
                    storage_revenue=sc.storage_revenue,
                    launch_fee_revenue=sc.launch_fee_revenue,
                    total_revenue=sc.total_revenue,
                    occupied_days=sc.occupied_days,
                    avg_occupancy_pct=sc.avg_occupancy_pct,
                )
                for sc in row.slip_class_detail
            ]
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
                    balloon_payment=-row.balloon_payment,
                    levered_cash_flow=row.levered_cash_flow,
                    slip_class_detail=slip_detail,
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
            "balloon_payment": str(getattr(cf, "balloon_payment", Decimal(0))),
            "levered_cash_flow": str(cf.levered_cash_flow),
            "slip_class_detail": [
                {
                    "slip_class_name": sc.slip_class_name,
                    "kind": sc.kind,
                    "count": sc.count,
                    "annual_contract_revenue": str(sc.annual_contract_revenue),
                    "seasonal_contract_revenue": str(sc.seasonal_contract_revenue),
                    "transient_revenue": str(sc.transient_revenue),
                    "utility_revenue": str(sc.utility_revenue),
                    "repair_service_revenue": str(sc.repair_service_revenue),
                    "retail_fnb_revenue": str(sc.retail_fnb_revenue),
                    "storage_revenue": str(sc.storage_revenue),
                    "launch_fee_revenue": str(sc.launch_fee_revenue),
                    "total_revenue": str(sc.total_revenue),
                    "occupied_days": str(sc.occupied_days),
                    "avg_occupancy_pct": str(sc.avg_occupancy_pct),
                }
                for sc in getattr(cf, "slip_class_detail", [])
            ],
        }

    @staticmethod
    def _with_storage_detail(rows: list[dict], result) -> list[dict]:
        """Attach each year's self storage operating detail to its cash flow row (JSON-safe)."""
        detail = {d["year"]: d for d in (getattr(result, "storage_detail", None) or [])}
        for row in rows:
            if row["year"] in detail:
                row["storage_detail"] = json.loads(json.dumps(detail[row["year"]], default=str))
        return rows

    def _to_run_response(
        self,
        valuation: Valuation,
        property_: Property,
        suites: list[Suite],
        leases: list[Lease],
        result,
        analysis_start: date,
    ) -> ValuationRunResponse:
        storage_detail = {
            row["year"]: row["storage_detail"]
            for row in self._with_storage_detail([{"year": cf.year} for cf in result.annual_cash_flows], result)
            if "storage_detail" in row
        }
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
                storage_detail=storage_detail.get(cf.year),
            )
            for cf in result.annual_cash_flows
        ]

        tenant_cfs = self._build_tenant_cash_flows(result, leases)
        self._attach_current_rent(tenant_cfs, leases, valuation)
        walt = self._compute_walt(suites, leases, analysis_start)
        key_metrics = self._build_key_metrics(valuation, result, annual_cfs, walt)
        expiration_schedule = self._build_expiration_schedule(
            suites, leases, self._effective_period_months(valuation, property_), analysis_start
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
            terminal_capital_deduction_amount=result.terminal_capital_deduction_amount,
            direct_cap_value=result.direct_cap_value,
            returns=self._returns_summary(result.returns),
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
            terminal_capital_deduction_amount=valuation.result_terminal_capital_deduction_amount,
            direct_cap_value=valuation.result_direct_cap_value,
            returns=(
                InvestmentReturnsSummary.model_validate_json(valuation.result_returns_json)
                if valuation.result_returns_json
                else None
            ),
            year1_gpi=Decimal(y1.gross_potential_income) if y1 else Decimal(0),
            year1_egi=Decimal(y1.effective_gross_income) if y1 else Decimal(0),
            year1_noi=Decimal(y1.net_operating_income) if y1 else Decimal(0),
            year1_cfbd=Decimal(y1.cash_flow_before_debt) if y1 else Decimal(0),
        )

    def _returns_summary(self, returns) -> InvestmentReturnsSummary | None:
        if returns is None:
            return None
        return InvestmentReturnsSummary(**asdict(returns))

    async def _frozen_snapshot(self, valuation, *columns: str):
        """The snapshot a valuation in review or approved is frozen to, loading only `columns` of
        its large blobs; None for a draft."""
        if valuation is None or valuation.review_status == "draft" or not valuation.snapshot_id:
            return None
        from sqlalchemy.orm import defer

        from src.models.valuation import ValuationSnapshot

        blobs = {"inputs_json", "results_json", "recovery_audit_json"} - set(columns)
        return (await self.db.execute(
            select(ValuationSnapshot).where(ValuationSnapshot.id == valuation.snapshot_id)
            .options(*(defer(getattr(ValuationSnapshot, b)) for b in blobs))
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()

    async def _frozen_service(self, valuation_id: str):
        """For a frozen valuation, an async context giving a ValuationService over its snapshot
        rebuilt in a private in-memory database; None for a draft."""
        snapshot = await self._frozen_snapshot(await self._load_valuation(valuation_id), "inputs_json")
        if snapshot is None:
            return None
        from contextlib import asynccontextmanager

        from src.services.valuation_snapshot import restored

        @asynccontextmanager
        async def frozen():
            async with restored(json.loads(snapshot.inputs_json)) as session:
                yield ValuationService(session)

        return frozen()

    async def monthly_cash_flows(self, valuation_id: str) -> list[AnnualCashFlowSummary] | None:
        """Re-run the model and return its cash flows by month (not persisted)."""
        if (frozen := await self._frozen_service(valuation_id)) is not None:
            async with frozen as service:
                return await service.monthly_cash_flows(valuation_id)
        valuation = await self._load_valuation(valuation_id)
        if valuation is None:
            return None
        property_ = await self._load_property(valuation.property_id)
        if property_ is None:
            return None
        if property_.property_type in ("marina", "seniors_housing"):
            raise ValueError("Monthly cash flows are not available for this property type")
        result = (await self.build_engine_inputs(valuation, property_)).run(include_monthly=True)
        return [AnnualCashFlowSummary(**self._serialize_annual_cf(cf)) for cf in result.monthly_cash_flows]

    async def ncreif_forecast(self, valuation_id: str) -> NcreifForecast | None:
        """Forecast quarterly unleveraged NCREIF-style time-weighted property returns."""
        if (frozen := await self._frozen_service(valuation_id)) is not None:
            async with frozen as service:
                return await service.ncreif_forecast(valuation_id)
        valuation = await self._load_valuation(valuation_id)
        if valuation is None:
            return None
        property_ = await self._load_property(valuation.property_id)
        if property_ is None:
            return None
        if property_.property_type in ("marina", "seniors_housing"):
            raise ValueError("NCREIF forecast is not yet available for this property type")
        result = (await self.build_engine_inputs(valuation, property_)).run(include_monthly=True)
        beginning_value = valuation.purchase_price or valuation.result_npv or result.npv
        payload = forecast_ncreif_returns(
            result.monthly_cash_flows,
            beginning_market_value=beginning_value,
            exit_cap_rate=valuation.exit_cap_rate,
            ownership_pct=(
                property_.ownership_pct
                if property_.ownership_pct is not None
                else Decimal(1)
            ),
            terminal_market_value=result.terminal_gross_value or None,
        )
        return NcreifForecast.model_validate(payload)

    async def _repricing_inputs(self, valuation_id: str):
        """Valuation, property, engine params and one fresh engine run, for repricing at other rates."""
        # Skip the large per-tenant / recovery-audit JSON: repricing re-runs the model instead
        valuation = (await self.db.execute(
            select(Valuation)
            .where(Valuation.id == valuation_id)
            .options(
                defer(Valuation.result_recovery_audit_json),
                defer(Valuation.result_tenant_cash_flows_json),
            )
        )).scalar_one_or_none()
        if valuation is None:
            return None
        if valuation.status != ValuationStatus.COMPLETED.value or not valuation.result_cash_flows_json:
            raise ValueError("Valuation has not been run yet")
        property_ = await self.db.get(Property, valuation.property_id)
        if valuation.result_terminal_noi_basis is None or property_.property_type in ("marina", "seniors_housing"):
            raise ValueError(
                "Sensitivity and what-if repricing are not available for this valuation type "
                "(marina, seniors housing, or a run without a terminal NOI basis)"
            )
        ran, changed = valuation.last_run_at, valuation.inputs_updated_at
        if ran is not None and changed is not None and _naive_dt(ran) < _naive_dt(changed):
            raise ValueError(
                "Inputs changed since this valuation last ran; re-run it to use sensitivity and what-if"
            )
        # One engine run per completed run: slider moves reprice the cached cash flows
        key = (valuation.id, valuation.last_run_at, valuation.updated_at, changed)
        cached = _REPRICE_RUNS.get(key)
        if cached is None:
            inputs = await self.build_engine_inputs(valuation, property_)
            cached = (inputs.params, inputs.run())
            _REPRICE_RUNS[key] = cached
            while len(_REPRICE_RUNS) > 4:
                _REPRICE_RUNS.pop(next(iter(_REPRICE_RUNS)))
        # Results saved by an older engine (or after an input change the timestamps missed) no
        # longer match the model: repricing them would report a change nobody made
        saved = valuation.result_npv
        if saved is not None and abs(Decimal(cached[1].npv) - Decimal(saved)) > Decimal("0.01"):
            raise ValueError(
                "The saved results no longer match the model (they predate a change); "
                "re-run the valuation to use sensitivity and what-if"
            )
        return valuation, property_, cached[0], cached[1]

    @staticmethod
    def _reprice(
        params: ValuationParams,
        result,
        discount_rates: list[Decimal],
        exit_caps: list[Decimal],
    ) -> SensitivityGrid:
        """Value of one engine run at each discount rate x exit cap.

        Cash flows and the terminal NOI basis do not depend on either rate, so each cell
        applies the engine's own terminal value, discounting and return math to the run's
        cash flows with only the discount rate / exit cap changed. Values and reversions are
        rounded to cents like the stored result.
        """
        cent = Decimal("0.01")
        monthly = params.discounting_convention == "monthly"
        # Unlevered IRR only: the loan does not affect it
        unlevered = replace(params, loan_amount=None, additional_loans=(), terminal_noi_override=result.terminal_noi_basis)
        terminals: list[Decimal] = []
        irrs: list[Decimal | None] = []
        for cap in exit_caps:
            cap_params = replace(unlevered, exit_cap_rate=cap)
            tv = calculate_terminal_value_breakdown(
                result.annual_cash_flows, cap_params,
                forward_year_capital=result.terminal_capital_deduction_amount,
            ).net_value
            terminals.append(tv)
            returns = compute_investment_returns(
                result.annual_cash_flows, tv, Decimal(0), cap_params, [], None,
                result.monthly_cash_flows if monthly else None,
            )
            irrs.append(returns.unlevered_irr if returns else None)

        values: list[list[Decimal]] = []
        for rate in discount_rates:
            row = []
            for tv in terminals:
                if monthly:
                    _, _, npv = discount_monthly_cash_flows(result.monthly_cash_flows, tv, rate)
                else:
                    _, _, npv = discount_cash_flows(
                        result.annual_cash_flows, tv, rate,
                        params.use_mid_year_convention, params.terminal_timing,
                    )
                row.append(npv.quantize(cent))
            values.append(row)
        return SensitivityGrid(
            discount_rates=discount_rates,
            exit_cap_rates=exit_caps,
            values=values,
            irr_by_exit_cap=irrs,
            terminal_values=[tv.quantize(cent) for tv in terminals],
        )

    async def sensitivity(
        self,
        valuation_id: str,
        discount_step: Decimal = Decimal("0.0025"),
        exit_cap_step: Decimal = Decimal("0.0025"),
        steps: int = 2,
    ) -> SensitivityMatrix | None:
        """Discount rate x exit cap PV matrix from one run of the completed valuation."""
        if (frozen := await self._frozen_service(valuation_id)) is not None:
            async with frozen as service:
                return await service.sensitivity(valuation_id, discount_step, exit_cap_step, steps)
        inputs = await self._repricing_inputs(valuation_id)
        if inputs is None:
            return None
        valuation, _, params, result = inputs
        offsets = [Decimal(i) for i in range(-steps, steps + 1)]
        discount_rates = [valuation.discount_rate + o * discount_step for o in offsets]
        exit_caps = [valuation.exit_cap_rate + o * exit_cap_step for o in offsets]
        discount_rates = [r for r in discount_rates if r > 0]
        exit_caps = [c for c in exit_caps if c > 0]
        grid = self._reprice(params, result, discount_rates, exit_caps)
        return SensitivityMatrix(**asdict(grid))

    async def what_if(
        self,
        valuation_id: str,
        discount_rate: Decimal | None = None,
        exit_cap_rate: Decimal | None = None,
    ) -> WhatIfResult | None:
        """Value at one discount rate / exit cap from one run of the completed valuation (not saved)."""
        if (frozen := await self._frozen_service(valuation_id)) is not None:
            async with frozen as service:
                return await service.what_if(valuation_id, discount_rate, exit_cap_rate)
        inputs = await self._repricing_inputs(valuation_id)
        if inputs is None:
            return None
        valuation, property_, params, result = inputs
        rate = valuation.discount_rate if discount_rate is None else discount_rate
        cap = valuation.exit_cap_rate if exit_cap_rate is None else exit_cap_rate
        grid = self._reprice(params, result, [rate], [cap])
        cent = Decimal("0.01")
        value = grid.values[0][0]
        saved = valuation.result_npv or Decimal(0)
        area = property_.total_area or Decimal(0)
        return WhatIfResult(
            discount_rate=rate,
            exit_cap_rate=cap,
            value=value,
            value_per_area=(value / area).quantize(cent) if area > 0 else None,
            area_unit=property_.area_unit,
            terminal_value=grid.terminal_values[0],
            irr=grid.irr_by_exit_cap[0],
            saved_discount_rate=valuation.discount_rate,
            saved_exit_cap_rate=valuation.exit_cap_rate,
            saved_value=saved,
            change_vs_saved=value - saved,
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

    def _attach_current_rent(
        self, tenant_cfs: list[TenantCashFlowDetail], leases: list[Lease], valuation: Valuation,
        as_of: date | None = None,
    ) -> None:
        """Set each suite's contract rent today from the lease in force on that date (none if vacant)."""
        as_of = as_of or date.today()
        active = {
            lease.suite_id: lease for lease in leases
            if lease.lease_start_date <= as_of <= lease.lease_end_date
        }
        cpi = valuation.cpi_rate if valuation.cpi_rate is not None else Decimal("0.025")
        for tcf in tenant_cfs:
            lease = active.get(tcf.suite_id)
            if lease is None:
                continue
            lease_input = self._to_lease_input(lease)
            rate = _current_rent(lease_input, as_of, cpi)
            annual = rate * lease_input.rent_area * (12 if lease_input.rent_payment_frequency == "monthly" else 1)
            tcf.current_rent_rate = rate
            tcf.current_rent_annual = annual
            tcf.current_rent_frequency = lease_input.rent_payment_frequency
            tcf.current_rent_basis = lease_input.rent_basis

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
                    recovery_pool=row.recovery_pool,
                    share_denominator_area=row.share_denominator_area,
                    pool_deduction=row.pool_deduction,
                    modified_gross_pool_per_sf=row.modified_gross_pool_per_sf,
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
                units = rent_area(suite.area, lease.rent_basis)
                if lease.rent_payment_frequency == "monthly":
                    annual_rent = lease.base_rent_per_unit * units * Decimal(12)
                else:
                    annual_rent = lease.base_rent_per_unit * units
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
        period_months: int,
        analysis_start: date,
    ) -> list[LeaseExpirationEntry]:
        from collections import defaultdict
        analysis_end = add_months(analysis_start, period_months) - timedelta(days=1)

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
                if l.base_rent_per_unit and l.rent_basis != "total":  # $/SF average only
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

    @staticmethod
    def _effective_period_months(valuation: Valuation, property_: Property) -> int:
        return valuation.analysis_period_months_override or property_.analysis_period_months

    def _hold_years(self, valuation: Valuation, property_: Property, model_hold_years=None) -> int:
        """Marina / seniors hold: the valuation's own period, else the operating model's, else the property's."""
        if valuation.analysis_period_months_override:
            return max(1, (valuation.analysis_period_months_override + 11) // 12)
        if model_hold_years is not None:
            return int(model_hold_years)
        return max(1, (property_.analysis_period_months + 11) // 12)

    @staticmethod
    def _operating_model_json(valuation: Valuation, property_: Property, kind: str) -> str | None:
        """The valuation's operating model."""
        return getattr(valuation, f"{kind}_assumptions_json", None)
