import json
import re
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from decimal import Decimal
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from sqlalchemy.orm import defer, selectinload

from src.api.validation import reject_null_columns
from src.models.valuation import ValuationSnapshot
from src.services.market_profiles import latest_valuation_id
from src.services.valuation_clone import HOLD_FROM_MODEL_TYPES, copy_inputs, copy_valuation, library_management_fee
from src.services.valuation_snapshot import (
    capture,
    engine_version,
    frozen_property,
    frozen_rows,
    restored,
    schema_revision,
)
from src.db.session import get_session
from src.engine.marina_valuation import (
    AdditionalRevenueLineInput as MarinaAdditionalRevenueLineInput,
)
from src.engine.marina_valuation import (
    CapexLifecycleInput as EngineCapexLifecycleInput,
)
from src.engine.marina_valuation import (
    CyclicalCostInput as EngineCyclicalCostInput,
)
from src.engine.marina_valuation import (
    DebtInput as EngineDebtInput,
)
from src.engine.marina_valuation import (
    DemandModelInput as EngineDemandModelInput,
)
from src.engine.marina_valuation import (
    FuelDockInput as EngineFuelDockInput,
)
from src.engine.marina_valuation import (
    LegalTenureInput as EngineLegalTenureInput,
)
from src.engine.marina_valuation import (
    MarinaModelInput as EngineMarinaModelInput,
)
from src.engine.marina_valuation import (
    MarinaScenarioInput as EngineMarinaScenarioInput,
)
from src.engine.marina_valuation import (
    OperatingCostLineInput as EngineOperatingCostLineInput,
)
from src.engine.marina_valuation import (
    SlipClassInput as EngineSlipClassInput,
)
from src.engine.marina_valuation import (
    ValuationInput as EngineValuationInput,
)
from src.engine.marina_valuation import (
    run_marina_scenarios,
    run_marina_sensitivity,
    run_marina_valuation,
    size_debt_for_covenants,
)
from src.models.property import Property
from src.models.valuation import Valuation
from src.services.readiness import assess as assess_readiness
from src.schemas.cashflow import (
    AnnualCashFlowSummary,
    KeyMetricsSummary,
    LeaseExpirationEntry,
    NcreifForecast,
    RentRollEntry,
    SensitivityMatrix,
    TenantCashFlowDetail,
    TenantRecoveryAuditEntry,
    ValuationRunResponse,
    WhatIfResult,
)
from src.schemas.marina_valuation import (
    MarinaDebtSizingResultRead,
    MarinaScenarioResultRead,
    MarinaSensitivityPointRead,
    MarinaValuationResultRead,
    MarinaValuationRunRequest,
    MarinaValuationRunResponse,
)
from src.engine.seniors_housing import (
    AncillaryRevenueInput as SHEngineAncillaryInput,
    CapexInput as SHEngineCapexInput,
    CareLevelTier as SHEngineCareLevelTier,
    DebtInput as SHEngineDebtInput,
    ExpenseLineInput as SHEngineExpenseInput,
    OccupancyRampInput as SHEngineRampInput,
    SeniorsHousingModelInput as SHEngineModelInput,
    SeniorsHousingScenarioInput as SHEngineScenarioInput,
    SNFPayerMixInput as SHEngineSNFPayerInput,
    UnitTypeInput as SHEngineUnitTypeInput,
    ValuationAssumptions as SHEngineValuationInput,
    run_seniors_housing_scenarios,
    run_seniors_housing_sensitivity,
    run_seniors_housing_valuation,
)
from src.schemas.seniors_housing import (
    SHScenarioResultRead,
    SHSensitivityPointRead,
    SHValuationResultRead,
    SHValuationRunRequest,
    SHValuationRunResponse,
)
from src.schemas.common import ValuationStatus
from src.schemas.valuation import (
    ReviewAction,
    SnapshotVerification,
    ValuationCreate,
    ValuationRead,
    ValuationSnapshotRead,
    ValuationUpdate,
)
from src.services.valuation_service import ValuationService

router = APIRouter(prefix="/api/v1", tags=["valuations"])


def _safe_filename(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return safe or "report"


def _build_rent_roll_workbook(
    *,
    property_name: str,
    valuation_name: str,
    analysis_start_date: str | None,
    rent_roll: list[RentRollEntry],
    area_unit: str,
) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise HTTPException(
            status_code=500,
            detail="Excel export dependency missing (openpyxl).",
        ) from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Rent Roll"

    ws["A1"] = "OpenDCF Rent Roll"
    ws["A1"].font = Font(size=16, bold=True)
    ws["A2"] = f"Property: {property_name}"
    ws["A3"] = f"Valuation: {valuation_name}"
    ws["F2"] = f"Analysis Start: {analysis_start_date or '—'}"
    ws["F3"] = f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"

    base_rent_label = "$/Unit/mo" if area_unit == "unit" else "$/SF/yr"
    headers = [
        "Suite",
        "Space Type",
        "Area",
        "Tenant",
        "Lease Start",
        "Lease End",
        "Lease Type",
        f"Base Rent ({base_rent_label})",
        "Annual Rent",
        "Recovery Type",
        "Escalation",
    ]

    header_row = 5
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(fill_type="solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    start_row = header_row + 1
    for i, row in enumerate(rent_roll):
        r = start_row + i
        lease_start = row.lease_start.isoformat() if row.lease_start else None
        lease_end = row.lease_end.isoformat() if row.lease_end else None
        values = [
            row.suite_name,
            row.space_type,
            float(row.area),
            row.tenant_name or "",
            lease_start,
            lease_end,
            row.lease_type,
            float(row.base_rent_per_unit) if row.base_rent_per_unit is not None else None,
            float(row.annual_rent) if row.annual_rent is not None else None,
            row.recovery_type or "",
            row.escalation_type or "",
        ]
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = border
            if c in (3, 8, 9):
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    last_row = max(header_row + 1, start_row + len(rent_roll) - 1)

    # Number formats
    for r in range(start_row, last_row + 1):
        ws.cell(r, 3).number_format = "#,##0.00"
        ws.cell(r, 8).number_format = "$#,##0.00"
        ws.cell(r, 9).number_format = "$#,##0"
        ws.cell(r, 5).number_format = "yyyy-mm-dd"
        ws.cell(r, 6).number_format = "yyyy-mm-dd"

    # Column sizing
    widths = {
        1: 16, 2: 14, 3: 12, 4: 24, 5: 12, 6: 12, 7: 12, 8: 16, 9: 14, 10: 14, 11: 14,
    }
    for col_idx, width in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A6"
    ws.auto_filter.ref = f"A{header_row}:K{last_row}"
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = f"1:{header_row}"
    ws.sheet_view.showGridLines = False

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()


def _to_engine_marina_model(body: MarinaValuationRunRequest) -> EngineMarinaModelInput:
    debt = None
    if body.debt is not None:
        debt = EngineDebtInput(
            loan_amount=body.debt.loan_amount,
            interest_rate=body.debt.interest_rate,
            amortization_months=body.debt.amortization_months,
            term_months=body.debt.term_months,
            io_period_months=body.debt.io_period_months,
            minimum_dscr=body.debt.minimum_dscr,
            maximum_ltv=body.debt.maximum_ltv,
            minimum_debt_yield=body.debt.minimum_debt_yield,
        )

    return EngineMarinaModelInput(
        as_of_date=body.as_of_date,
        slip_classes=tuple(
            EngineSlipClassInput(
                name=s.name,
                kind=s.kind,
                length_class=s.length_class,
                utility_service_level=s.utility_service_level,
                count=s.count,
                annual_contract_share=s.annual_contract_share,
                seasonal_contract_share=s.seasonal_contract_share,
                transient_share=s.transient_share,
                annual_contract_rate=s.annual_contract_rate,
                seasonal_contract_rate=s.seasonal_contract_rate,
                transient_daily_rate=s.transient_daily_rate,
                utility_fee_monthly=s.utility_fee_monthly,
                utility_fee_transient_daily=s.utility_fee_transient_daily,
                repair_service_revenue_per_occupied_day=s.repair_service_revenue_per_occupied_day,
                retail_fnb_revenue_per_occupied_day=s.retail_fnb_revenue_per_occupied_day,
                storage_fee_per_month=s.storage_fee_per_month,
                launch_fee_per_transient_arrival=s.launch_fee_per_transient_arrival,
                avg_transient_stay_days=s.avg_transient_stay_days,
                base_annual_occupancy=s.base_annual_occupancy,
                base_seasonal_occupancy=s.base_seasonal_occupancy,
                base_transient_capture=s.base_transient_capture,
            )
            for s in body.slip_classes
        ),
        additional_revenue_lines=tuple(
            MarinaAdditionalRevenueLineInput(
                name=line.name,
                annual_fixed=line.annual_fixed,
                per_occupied_day=line.per_occupied_day,
                growth_pct=line.growth_pct,
            )
            for line in body.additional_revenue_lines
        ),
        demand=EngineDemandModelInput(
            monthly_seasonality=tuple(body.demand.monthly_seasonality),
            monthly_weather_shock_pct=tuple(body.demand.monthly_weather_shock_pct),
            seasonal_active_months=tuple(body.demand.seasonal_active_months),
            annual_occupancy_growth_pct=body.demand.annual_occupancy_growth_pct,
            seasonal_occupancy_growth_pct=body.demand.seasonal_occupancy_growth_pct,
            waitlist_start_count=body.demand.waitlist_start_count,
            waitlist_conversion_pct=body.demand.waitlist_conversion_pct,
            waitlist_new_demand_per_year=body.demand.waitlist_new_demand_per_year,
            annual_rate_growth_pct=body.demand.annual_rate_growth_pct,
            seasonal_rate_growth_pct=body.demand.seasonal_rate_growth_pct,
            transient_rate_growth_pct=body.demand.transient_rate_growth_pct,
            ancillary_growth_pct=body.demand.ancillary_growth_pct,
            transient_weather_sensitivity=body.demand.transient_weather_sensitivity,
            vacancy_collection_loss_pct=body.demand.vacancy_collection_loss_pct,
            management_fee_pct=body.demand.management_fee_pct,
        ),
        operating_cost_lines=tuple(
            EngineOperatingCostLineInput(
                name=line.name,
                annual_fixed=line.annual_fixed,
                per_occupied_day=line.per_occupied_day,
                growth_pct=line.growth_pct,
            )
            for line in body.operating_cost_lines
        ),
        cyclical_costs=tuple(
            EngineCyclicalCostInput(
                name=cost.name,
                base_amount=cost.base_amount,
                first_year=cost.first_year,
                every_n_years=cost.every_n_years,
                growth_pct=cost.growth_pct,
                probability_pct=cost.probability_pct,
                treat_as_capex=cost.treat_as_capex,
            )
            for cost in body.cyclical_costs
        ),
        legal_tenure=EngineLegalTenureInput(
            tenure_type=body.legal_tenure.tenure_type,
            annual_ground_lease=body.legal_tenure.annual_ground_lease,
            ground_lease_growth_pct=body.legal_tenure.ground_lease_growth_pct,
            annual_submerged_land_lease=body.legal_tenure.annual_submerged_land_lease,
            submerged_land_lease_growth_pct=body.legal_tenure.submerged_land_lease_growth_pct,
            annual_permit_concession_fees=body.legal_tenure.annual_permit_concession_fees,
            permit_growth_pct=body.legal_tenure.permit_growth_pct,
            remaining_lease_years=body.legal_tenure.remaining_lease_years,
            lease_extension_probability=body.legal_tenure.lease_extension_probability,
            reversion_value_loss_pct=body.legal_tenure.reversion_value_loss_pct,
            expiry_warning_horizon_years=body.legal_tenure.expiry_warning_horizon_years,
        ),
        capex_lifecycle=tuple(
            EngineCapexLifecycleInput(
                name=capex.name,
                asset_type=capex.asset_type,
                base_amount=capex.base_amount,
                first_year=capex.first_year,
                every_n_years=capex.every_n_years,
                growth_pct=capex.growth_pct,
                deferred_maintenance_catchup_year=capex.deferred_maintenance_catchup_year,
                deferred_maintenance_amount=capex.deferred_maintenance_amount,
            )
            for capex in body.capex_lifecycle
        ),
        valuation=EngineValuationInput(
            hold_years=body.valuation.hold_years,
            discount_rate=body.valuation.discount_rate,
            exit_cap_rate=body.valuation.exit_cap_rate,
            exit_costs_pct=body.valuation.exit_costs_pct,
            use_mid_year_convention=body.valuation.use_mid_year_convention,
            terminal_noi_growth_pct=body.valuation.terminal_noi_growth_pct,
            dock_replacement_reserve_per_slip_year=body.valuation.dock_replacement_reserve_per_slip_year,
            reserve_growth_pct=body.valuation.reserve_growth_pct,
            initial_purchase_price=body.valuation.initial_purchase_price,
            levered_discount_rate=body.valuation.levered_discount_rate,
        ),
        fuel_dock=EngineFuelDockInput(
            enabled=body.fuel_dock.enabled,
            fuel_sales_per_occupied_day=body.fuel_dock.fuel_sales_per_occupied_day,
            fuel_margin_pct=body.fuel_dock.fuel_margin_pct,
            annual_growth_pct=body.fuel_dock.annual_growth_pct,
        ),
        debt=debt,
    )


def _to_engine_marina_scenarios(
    body: MarinaValuationRunRequest,
) -> tuple[EngineMarinaScenarioInput, ...]:
    return tuple(
        EngineMarinaScenarioInput(
            name=scenario.name,
            occupancy_multiplier=scenario.occupancy_multiplier,
            rate_multiplier=scenario.rate_multiplier,
            opex_multiplier=scenario.opex_multiplier,
            weather_shock_additive_pct=scenario.weather_shock_additive_pct,
            exit_cap_rate_shift_bps=scenario.exit_cap_rate_shift_bps,
        )
        for scenario in body.scenarios
    )


@router.post(
    "/properties/{property_id}/valuations",
    response_model=ValuationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_valuation(
    property_id: str,
    body: ValuationCreate,
    db: AsyncSession = Depends(get_session),
) -> ValuationRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    prop = result.scalar_one_or_none()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    valuation = Valuation(property_id=property_id, **body.model_dump())
    if "capital_reserves_per_unit" not in body.model_fields_set:
        # Not given: start from the assumptions library (house default by basis, or a profile)
        from src.services.portfolio_service import PortfolioService

        resolved = await PortfolioService(db).resolve_for_property(prop, None)
        if "capital_reserves_per_unit" in resolved.values:
            valuation.capital_reserves_per_unit = resolved.values["capital_reserves_per_unit"]
    # Each valuation has its own dates; the property's are the defaults
    valuation.analysis_start_date_override = valuation.analysis_start_date_override or prop.analysis_start_date
    if prop.property_type not in HOLD_FROM_MODEL_TYPES:  # their operating model's hold_years applies
        valuation.analysis_period_months_override = (
            valuation.analysis_period_months_override or prop.analysis_period_months
        )
    source_id = await latest_valuation_id(db, property_id)
    source = await db.get(Valuation, source_id) if source_id else None
    for column in ("marina_assumptions_json", "seniors_housing_assumptions_json", "self_storage_assumptions_json"):
        if getattr(valuation, column) is None:
            seed = getattr(source, column) if source is not None else getattr(prop, column)
            setattr(valuation, column, seed)
    db.add(valuation)
    await db.flush()
    if source is not None:
        # The new valuation starts from a copy of the latest one's whole model
        await copy_inputs(db, source, valuation)
    else:
        await library_management_fee(db, prop, valuation)
    await db.commit()
    await db.refresh(valuation)
    return valuation


@router.get("/properties/{property_id}/valuations", response_model=list[ValuationRead])
async def list_valuations(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[ValuationRead]:
    # The stored result blobs can be ~100MB per run and ValuationRead never returns them
    result = await db.execute(
        select(Valuation).where(Valuation.property_id == property_id).options(
            defer(Valuation.result_cash_flows_json),
            defer(Valuation.result_tenant_cash_flows_json),
            defer(Valuation.result_recovery_audit_json),
            defer(Valuation.result_returns_json),
        )
    )
    return list(result.scalars().all())


@router.get("/valuations/{valuation_id}", response_model=ValuationRead)
async def get_valuation(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> ValuationRead:
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return v


# Fields that only label a valuation; changing them keeps its results
_LABEL_FIELDS = {"name", "description", "comment"}
_RESULT_COLUMNS = [c.key for c in Valuation.__table__.columns if c.key.startswith("result_")]


@router.put("/valuations/{valuation_id}", response_model=ValuationRead)
async def update_valuation(
    valuation_id: str,
    body: ValuationUpdate,
    db: AsyncSession = Depends(get_session),
) -> ValuationRead:
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    changes = body.model_dump(exclude_unset=True)
    reject_null_columns(Valuation, changes)
    cash_flow_basis = changes.get("cash_flow_basis", v.cash_flow_basis)
    discount_rate_basis = changes.get("discount_rate_basis", v.discount_rate_basis)
    if cash_flow_basis != discount_rate_basis:
        raise HTTPException(
            status_code=422,
            detail="cash_flow_basis and discount_rate_basis must match",
        )
    inputs_changed = any(
        getattr(v, field) != value for field, value in changes.items() if field not in _LABEL_FIELDS
    )
    for field, value in changes.items():
        setattr(v, field, value)
    if inputs_changed:
        # Results came from the old inputs; the valuation must be run again
        v.status = ValuationStatus.DRAFT.value
        v.error_message = None
        for column in _RESULT_COLUMNS:
            setattr(v, column, None)
    await db.commit()
    await db.refresh(v)
    return v


@router.post(
    "/valuations/{valuation_id}/duplicate",
    response_model=ValuationRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_valuation(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> ValuationRead:
    """Copy a valuation and its whole model into a new draft (results are not copied)."""
    source = await db.get(Valuation, valuation_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    copy = await copy_valuation(db, source, f"{source.name} (copy)")
    await db.commit()
    await db.refresh(copy)
    return copy


class RollForwardRequest(BaseModel):
    period: Literal["month", "quarter", "year"] = "quarter"
    name: str | None = None


class RolledLease(BaseModel):
    lease_id: str
    suite_name: str
    tenant_name: str | None
    lease_start_date: date
    lease_end_date: date


class RollForwardResponse(BaseModel):
    valuation: ValuationRead
    expired_leases: list[RolledLease]  # ended between the two analysis starts
    started_leases: list[RolledLease]  # began between the two analysis starts


_ROLL_MONTHS = {"month": 1, "quarter": 3, "year": 12}


@router.post(
    "/valuations/{valuation_id}/roll-forward",
    response_model=RollForwardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def roll_forward_valuation(
    valuation_id: str,
    body: RollForwardRequest | None = None,
    db: AsyncSession = Depends(get_session),
) -> RollForwardResponse:
    """Copy a valuation with its analysis start moved forward, and list the leases that expired
    or started in between for the analyst to update."""
    from src.engine.date_utils import add_months
    from src.models.lease import Lease
    from src.models.property import Suite

    body = body or RollForwardRequest()
    source = await db.get(Valuation, valuation_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    prop = await db.get(Property, source.property_id)
    old_start = source.analysis_start_date_override or prop.analysis_start_date
    new_start = add_months(old_start, _ROLL_MONTHS[body.period])
    copy = await copy_valuation(
        db, source, body.name or f"{source.name} ({new_start:%b %Y})",
        analysis_start_date_override=new_start, prior_valuation_id=source.id,
    )
    await db.commit()
    await db.refresh(copy)
    rows = (await db.execute(
        select(Lease, Suite.suite_name).join(Suite, Lease.suite_id == Suite.id)
        .where(Suite.valuation_id == copy.id).options(selectinload(Lease.tenant))
    )).all()

    def entry(lease: Lease, suite_name: str) -> RolledLease:
        return RolledLease(lease_id=lease.id, suite_name=suite_name,
                           tenant_name=lease.tenant.name if lease.tenant else None,
                           lease_start_date=lease.lease_start_date, lease_end_date=lease.lease_end_date)

    return RollForwardResponse(
        valuation=copy,
        expired_leases=[entry(l, n) for l, n in rows if old_start <= l.lease_end_date < new_start],
        started_leases=[entry(l, n) for l, n in rows if old_start <= l.lease_start_date < new_start],
    )


@router.delete("/valuations/{valuation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_valuation(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    await db.delete(v)
    await db.commit()


@router.post("/valuations/{valuation_id}/run", response_model=ValuationRunResponse)
async def run_valuation(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> ValuationRunResponse:
    """
    Execute the DCF engine for this valuation.
    Loads all property data, runs the engine, persists results, returns full output.
    """
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    valuation = result.scalar_one_or_none()
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    if valuation.review_status != "draft":
        raise HTTPException(409, "This valuation is frozen for review; its results are the ones reviewed. "
                                 "Reopen it to run it again.")
    property_ = await db.get(Property, valuation.property_id)
    readiness = await assess_readiness(db, property_, valuation)
    if not readiness.ready:
        message = f"Not ready to run: {readiness.blocking_message()}"
        # Record the refusal only on a never-run valuation; one with results keeps them as-is
        if valuation.last_run_at is None:
            valuation.status = ValuationStatus.FAILED.value
            valuation.error_message = message
            await db.commit()
        raise HTTPException(status_code=400, detail=message)

    service = ValuationService(db)
    try:
        return await service.execute_valuation(valuation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc!s}")


# ─── Review lifecycle (docs/valuation-lifecycle-plan.md) ─────────────────────

async def _valuation_or_404(db: AsyncSession, valuation_id: str) -> Valuation:
    valuation = await db.get(Valuation, valuation_id)
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return valuation


async def _current_snapshot(db: AsyncSession, valuation: Valuation, *blobs: str) -> ValuationSnapshot:
    """The valuation's frozen snapshot, loading only the named large columns."""
    snapshot = await ValuationService(db)._frozen_snapshot(valuation, *blobs)
    if snapshot is None:
        raise HTTPException(status_code=409, detail="This valuation is not frozen")
    return snapshot


async def _rerun_snapshot(inputs: dict, valuation_id: str) -> Decimal | None:
    """Run a snapshot's inputs again in a private database; its NPV."""
    async with restored(inputs) as session:
        await ValuationService(session).execute_valuation(valuation_id)
        return (await session.get(Valuation, valuation_id)).result_npv


@router.post("/valuations/{valuation_id}/submit", response_model=ValuationRead)
async def submit_valuation(valuation_id: str, body: ReviewAction, db: AsyncSession = Depends(get_session)):
    """Run the valuation and freeze its inputs and results for review."""
    valuation = await _valuation_or_404(db, valuation_id)
    if valuation.review_status != "draft":
        raise HTTPException(409, f"Already {valuation.review_status.replace('_', ' ')}")
    property_ = await db.get(Property, valuation.property_id)
    readiness = await assess_readiness(db, property_, valuation)
    if not readiness.ready:
        raise HTTPException(400, f"Not ready to run: {readiness.blocking_message()}")
    service = ValuationService(db)
    try:
        await service.execute_valuation(valuation_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.refresh(valuation)
    if valuation.status != ValuationStatus.COMPLETED.value:
        raise HTTPException(422, f"The run did not complete: {valuation.error_message or valuation.status}")
    inputs = await capture(db, valuation)
    results = await service.get_results(valuation_id)
    # Refuse to freeze anything the snapshot could not reproduce
    try:
        rerun = await _rerun_snapshot(inputs, valuation_id)
    except Exception as exc:  # noqa: BLE001 - reported, nothing frozen
        raise HTTPException(500, f"Could not re-run the frozen inputs; not submitted: {exc!s}") from exc
    if rerun != valuation.result_npv:
        raise HTTPException(
            500, f"The frozen inputs value at {rerun}, not {valuation.result_npv}; not submitted. Please report this."
        )
    audit = results.recovery_audit
    snapshot = ValuationSnapshot(
        valuation_id=valuation_id, status="in_review", inputs_json=json.dumps(inputs),
        results_json=results.model_copy(update={"recovery_audit": []}).model_dump_json(),
        recovery_audit_json=json.dumps([a.model_dump(mode="json") for a in audit]) if audit else None,
        schema_revision=await schema_revision(db), result_npv=valuation.result_npv,
        value_date=(valuation.analysis_start_date_override or property_.analysis_start_date) - timedelta(days=1),
        engine_version=engine_version(), submitted_by=body.name, submitted_at=datetime.now(UTC),
        submit_note=body.note,
    )
    db.add(snapshot)
    await db.flush()
    # Claim the draft atomically: of two submits at once, only the first freezes
    claimed = await db.execute(
        update(Valuation)
        .where(Valuation.id == valuation_id, Valuation.review_status == "draft")
        .values(review_status="in_review", snapshot_id=snapshot.id)
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Already submitted")
    await db.commit()
    await db.refresh(valuation)
    return valuation


@router.post("/valuations/{valuation_id}/approve", response_model=ValuationRead)
async def approve_valuation(valuation_id: str, body: ReviewAction, db: AsyncSession = Depends(get_session)):
    valuation = await _valuation_or_404(db, valuation_id)
    if valuation.review_status != "in_review":
        raise HTTPException(409, "Only a valuation in review can be approved")
    snapshot = await _current_snapshot(db, valuation)
    snapshot.status = "approved"
    snapshot.approved_by, snapshot.approved_at, snapshot.approve_note = body.name, datetime.now(UTC), body.note
    valuation.review_status = "approved"
    await db.commit()
    await db.refresh(valuation)
    return valuation


@router.post("/valuations/{valuation_id}/reopen", response_model=ValuationRead)
async def reopen_valuation(valuation_id: str, body: ReviewAction, db: AsyncSession = Depends(get_session)):
    """Back to draft on the live model. The frozen snapshot is kept in the history."""
    valuation = await _valuation_or_404(db, valuation_id)
    if valuation.review_status == "draft":
        raise HTTPException(409, "Not frozen")
    if not (body.note or "").strip():
        raise HTTPException(422, "A reason is required to reopen")
    snapshot = await _current_snapshot(db, valuation)
    snapshot.status = "reopened"
    snapshot.reopened_by, snapshot.reopened_at, snapshot.reopen_reason = body.name, datetime.now(UTC), body.note
    valuation.review_status = "draft"
    valuation.snapshot_id = None
    await db.commit()
    await db.refresh(valuation)
    return valuation


@router.get("/valuations/{valuation_id}/snapshots", response_model=list[ValuationSnapshotRead])
async def list_snapshots(valuation_id: str, db: AsyncSession = Depends(get_session)):
    """Every time this valuation was frozen, newest first, with its review trail."""
    await _valuation_or_404(db, valuation_id)
    rows = await db.execute(
        select(ValuationSnapshot).where(ValuationSnapshot.valuation_id == valuation_id)
        .options(defer(ValuationSnapshot.inputs_json), defer(ValuationSnapshot.results_json))
        .order_by(ValuationSnapshot.submitted_at.desc())
    )
    return list(rows.scalars())


@router.post("/valuations/{valuation_id}/verify", response_model=SnapshotVerification)
async def verify_snapshot(valuation_id: str, db: AsyncSession = Depends(get_session)) -> SnapshotVerification:
    """Run the frozen inputs on today's engine and compare with the value that was reviewed."""
    valuation = await _valuation_or_404(db, valuation_id)
    snapshot = await _current_snapshot(db, valuation, "inputs_json")
    out = SnapshotVerification(
        snapshot_id=snapshot.id, engine_version_frozen=snapshot.engine_version,
        engine_version_now=engine_version(), stored_npv=snapshot.result_npv, rerun_npv=None, matches=False,
    )
    try:
        out.rerun_npv = await _rerun_snapshot(json.loads(snapshot.inputs_json), valuation_id)
    except Exception as exc:  # noqa: BLE001 - shown to the reviewer
        out.error = str(exc)
        return out
    out.matches = out.rerun_npv == snapshot.result_npv
    return out


@router.get("/valuations/{valuation_id}/frozen-inputs")
async def frozen_inputs(valuation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """The property, market profiles and expenses as frozen, for the review screens."""
    valuation = await _valuation_or_404(db, valuation_id)
    if valuation.review_status == "draft":
        raise HTTPException(409, "This valuation is not frozen")
    snapshot = json.loads((await _current_snapshot(db, valuation, "inputs_json")).inputs_json)

    def rows(table: str) -> list[dict]:
        return [{k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in frozen_rows(snapshot, table)]

    # The live property id: a property merged into another froze under an id that no longer exists
    return {"property": rows("properties")[0] | {"id": valuation.property_id},
            "market_profiles": rows("market_leasing_profiles"),
            "expenses": rows("property_expenses")}


async def _report_property(db: AsyncSession, valuation: Valuation):
    """The property a report describes: as frozen for a valuation in review or approved, else live."""
    if valuation.review_status != "draft" and valuation.snapshot_id:
        return frozen_property(json.loads((await _current_snapshot(db, valuation, "inputs_json")).inputs_json))
    return await db.get(Property, valuation.property_id)


@router.post("/marina-valuations/run", response_model=MarinaValuationRunResponse)
async def run_marina_valuation_endpoint(
    body: MarinaValuationRunRequest,
) -> MarinaValuationRunResponse:
    """Run an ad hoc marina valuation with optional scenarios/sensitivity/debt sizing."""
    try:
        model = _to_engine_marina_model(body)
        valuation_result = run_marina_valuation(model)

        scenario_results = []
        if body.scenarios:
            scenario_results = run_marina_scenarios(model, _to_engine_marina_scenarios(body))

        sensitivity_points = []
        if body.sensitivity is not None:
            sensitivity_points = run_marina_sensitivity(
                model,
                tuple(body.sensitivity.discount_rates),
                tuple(body.sensitivity.exit_cap_rates),
                tuple(body.sensitivity.occupancy_multipliers),
            )

        debt_sizing = None
        if body.include_debt_sizing:
            debt_sizing = size_debt_for_covenants(model)

        return MarinaValuationRunResponse(
            valuation=MarinaValuationResultRead.model_validate(asdict(valuation_result)),
            scenario_results=[
                MarinaScenarioResultRead.model_validate(asdict(item)) for item in scenario_results
            ],
            sensitivity_points=[
                MarinaSensitivityPointRead.model_validate(asdict(item))
                for item in sensitivity_points
            ],
            debt_sizing=(
                MarinaDebtSizingResultRead.model_validate(asdict(debt_sizing))
                if debt_sizing is not None
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc!s}")


# ---- Seniors Housing ----


def _to_engine_sh_model(body: SHValuationRunRequest) -> SHEngineModelInput:
    unit_types = tuple(
        SHEngineUnitTypeInput(
            name=ut.name,
            acuity=ut.acuity,
            unit_type=ut.unit_type,
            count=ut.count,
            avg_sf=ut.avg_sf,
            monthly_base_fee=ut.monthly_base_fee,
            second_person_fee_monthly=ut.second_person_fee_monthly,
            second_person_pct=ut.second_person_pct,
            community_fee=ut.community_fee,
            avg_length_of_stay_months=ut.avg_length_of_stay_months,
            stabilized_occupancy=ut.stabilized_occupancy,
            annual_turnover_rate=ut.annual_turnover_rate,
            care_level_tiers=tuple(
                SHEngineCareLevelTier(
                    name=t.name,
                    monthly_surcharge=t.monthly_surcharge,
                    pct_of_residents=t.pct_of_residents,
                )
                for t in ut.care_level_tiers
            ),
        )
        for ut in body.unit_types
    )
    snf_payer = tuple(
        SHEngineSNFPayerInput(
            payer=p.payer,
            pct_of_days=p.pct_of_days,
            daily_rate=p.daily_rate,
            annual_rate_growth=p.annual_rate_growth,
        )
        for p in body.snf_payer_mix
    )
    ancillary = tuple(
        SHEngineAncillaryInput(
            name=a.name,
            annual_fixed=a.annual_fixed,
            per_occupied_unit_month=a.per_occupied_unit_month,
            growth_pct=a.growth_pct,
            applies_to_acuity=tuple(a.applies_to_acuity),
        )
        for a in body.ancillary_revenue
    )
    expenses = tuple(
        SHEngineExpenseInput(
            name=e.name,
            category=e.category,
            annual_fixed=e.annual_fixed,
            per_occupied_unit_month=e.per_occupied_unit_month,
            pct_of_revenue=e.pct_of_revenue,
            growth_pct=e.growth_pct,
            is_variable=e.is_variable,
            applies_to_acuity=tuple(e.applies_to_acuity),
        )
        for e in body.expenses
    )
    capex = tuple(
        SHEngineCapexInput(
            name=c.name,
            annual_per_unit=c.annual_per_unit,
            annual_fixed=c.annual_fixed,
            growth_pct=c.growth_pct,
        )
        for c in body.capex
    )
    v = body.valuation
    valuation = SHEngineValuationInput(
        hold_years=v.hold_years,
        discount_rate=v.discount_rate,
        exit_cap_rate=v.exit_cap_rate,
        exit_costs_pct=v.exit_costs_pct,
        use_mid_year_convention=v.use_mid_year_convention,
        terminal_noi_growth_pct=v.terminal_noi_growth_pct,
        fee_growth_rate=v.fee_growth_rate,
        expense_growth_rate=v.expense_growth_rate,
        initial_purchase_price=v.initial_purchase_price,
        levered_discount_rate=v.levered_discount_rate,
    )
    ramp = None
    if body.occupancy_ramp is not None:
        ramp = SHEngineRampInput(
            start_occupancy=body.occupancy_ramp.start_occupancy,
            monthly_absorption_units=body.occupancy_ramp.monthly_absorption_units,
            stabilization_month=body.occupancy_ramp.stabilization_month,
        )
    debt = None
    if body.debt is not None:
        debt = SHEngineDebtInput(
            loan_amount=body.debt.loan_amount,
            interest_rate=body.debt.interest_rate,
            amortization_months=body.debt.amortization_months,
            term_months=body.debt.term_months,
            io_period_months=body.debt.io_period_months,
            minimum_dscr=body.debt.minimum_dscr,
            maximum_ltv=body.debt.maximum_ltv,
        )
    return SHEngineModelInput(
        as_of_date=body.as_of_date,
        community_name=body.community_name,
        unit_types=unit_types,
        snf_payer_mix=snf_payer,
        ancillary_revenue=ancillary,
        expenses=expenses,
        capex=capex,
        valuation=valuation,
        occupancy_ramp=ramp,
        debt=debt,
    )


@router.post("/seniors-housing-valuations/run", response_model=SHValuationRunResponse)
async def run_seniors_housing_valuation_endpoint(
    body: SHValuationRunRequest,
) -> SHValuationRunResponse:
    """Run an ad hoc seniors housing valuation with optional scenarios/sensitivity."""
    try:
        model = _to_engine_sh_model(body)
        result = run_seniors_housing_valuation(model)

        scenario_results = []
        if body.scenarios:
            scenarios = tuple(
                SHEngineScenarioInput(
                    name=s.name,
                    occupancy_multiplier=s.occupancy_multiplier,
                    rate_multiplier=s.rate_multiplier,
                    opex_multiplier=s.opex_multiplier,
                    exit_cap_rate_shift_bps=s.exit_cap_rate_shift_bps,
                )
                for s in body.scenarios
            )
            scenario_results = run_seniors_housing_scenarios(model, scenarios)

        sensitivity_points = []
        if body.sensitivity is not None:
            sensitivity_points = run_seniors_housing_sensitivity(
                model,
                tuple(body.sensitivity.discount_rates),
                tuple(body.sensitivity.exit_cap_rates),
                tuple(body.sensitivity.occupancy_multipliers),
            )

        return SHValuationRunResponse(
            valuation=SHValuationResultRead.model_validate(asdict(result)),
            scenario_results=[
                SHScenarioResultRead.model_validate(asdict(item)) for item in scenario_results
            ],
            sensitivity_points=[
                SHSensitivityPointRead.model_validate(asdict(item)) for item in sensitivity_points
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc!s}")


# ---- Reports ----

@router.get(
    "/valuations/{valuation_id}/reports/cash-flow-summary",
    response_model=list[AnnualCashFlowSummary],
)
async def report_cash_flow_summary(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[AnnualCashFlowSummary]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.annual_cash_flows


@router.get("/valuations/{valuation_id}/reports/rent-roll", response_model=list[RentRollEntry])
async def report_rent_roll(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[RentRollEntry]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.rent_roll


@router.get("/valuations/{valuation_id}/reports/rent-roll.xlsx")
async def report_rent_roll_excel(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    valuation_result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    valuation = valuation_result.scalar_one_or_none()
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")

    property_ = await _report_property(db, valuation)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")

    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")

    workbook_bytes = _build_rent_roll_workbook(
        property_name=property_.name,
        valuation_name=valuation.name,
        analysis_start_date=(
            valuation.analysis_start_date_override or property_.analysis_start_date
        ).isoformat(),
        rent_roll=response.rent_roll,
        area_unit=property_.area_unit,
    )
    filename = (
        f"rent_roll_{_safe_filename(property_.name)}_{_safe_filename(valuation.name)}.xlsx"
    )
    return StreamingResponse(
        BytesIO(workbook_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/valuations/{valuation_id}/reports/full-export.xlsx")
async def report_full_export_excel(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """
    Multi-tab Excel workbook:
    Key Metrics, Assumptions, Annual CFs, Tenant Detail, Debt, Rent Roll, Expirations.
    """
    valuation_result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    valuation = valuation_result.scalar_one_or_none()
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")

    property_ = await _report_property(db, valuation)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")

    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")

    analysis_start = (
        valuation.analysis_start_date_override or property_.analysis_start_date
    ).isoformat()

    # Build valuation params dict for assumptions/debt tabs
    vp = {
        "discount_rate": valuation.discount_rate,
        "basis_of_value": valuation.basis_of_value,
        "intended_use": valuation.intended_use,
        "risk_treatment": valuation.risk_treatment,
        "cash_flow_basis": valuation.cash_flow_basis,
        "discount_rate_basis": valuation.discount_rate_basis,
        "exit_cap_rate": valuation.exit_cap_rate,
        "exit_cap_applied_to_year": valuation.exit_cap_applied_to_year,
        "exit_costs_pct": valuation.exit_costs_pct,
        "transfer_tax_preset": valuation.transfer_tax_preset,
        "transfer_tax_custom_rate": valuation.transfer_tax_custom_rate,
        "apply_stabilized_gross_up": valuation.apply_stabilized_gross_up,
        "stabilized_occupancy_pct": valuation.stabilized_occupancy_pct,
        "capital_reserves_per_unit": valuation.capital_reserves_per_unit,
        "use_mid_year_convention": valuation.use_mid_year_convention,
        "terminal_timing": valuation.terminal_timing,
        "loan_amount": valuation.loan_amount,
        "interest_rate": valuation.interest_rate,
        "amortization_months": valuation.amortization_months,
        "loan_term_months": valuation.loan_term_months,
        "io_period_months": valuation.io_period_months,
        "additional_loans": valuation.additional_loans or [],
        "analysis_period_months": ValuationService._effective_period_months(valuation, property_),
    }

    from src.services.excel_export import build_full_export_workbook
    workbook_bytes = build_full_export_workbook(
        property_name=property_.name,
        property_type=property_.property_type,
        total_area=float(property_.total_area),
        area_unit=property_.area_unit,
        analysis_start_date=analysis_start,
        analysis_period_months=ValuationService._effective_period_months(valuation, property_),
        fiscal_year_end_month=property_.fiscal_year_end_month,
        valuation_name=valuation.name,
        valuation_params=vp,
        key_metrics=response.key_metrics,
        annual_cash_flows=response.annual_cash_flows,
        tenant_cash_flows=response.tenant_cash_flows,
        rent_roll=response.rent_roll,
        lease_expirations=response.lease_expiration_schedule,
    )
    filename = f"valuation_{_safe_filename(property_.name)}_{_safe_filename(valuation.name)}.xlsx"
    return StreamingResponse(
        BytesIO(workbook_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/valuations/{valuation_id}/reports/investment-memo.pdf")
async def report_investment_memo_pdf(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Branded PDF investment memo / underwriting package."""
    valuation_result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    valuation = valuation_result.scalar_one_or_none()
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")

    property_ = await _report_property(db, valuation)
    if property_ is None:
        raise HTTPException(status_code=404, detail="Property not found")

    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")

    analysis_start = (
        valuation.analysis_start_date_override or property_.analysis_start_date
    ).isoformat()

    vp = {
        "discount_rate": valuation.discount_rate,
        "basis_of_value": valuation.basis_of_value,
        "intended_use": valuation.intended_use,
        "risk_treatment": valuation.risk_treatment,
        "cash_flow_basis": valuation.cash_flow_basis,
        "discount_rate_basis": valuation.discount_rate_basis,
        "exit_cap_rate": valuation.exit_cap_rate,
        "exit_costs_pct": valuation.exit_costs_pct,
        "capital_reserves_per_unit": valuation.capital_reserves_per_unit,
        "use_mid_year_convention": valuation.use_mid_year_convention,
        "terminal_timing": valuation.terminal_timing,
        "loan_amount": valuation.loan_amount,
        "interest_rate": valuation.interest_rate,
        "additional_loans": valuation.additional_loans or [],
    }

    from src.services.pdf_report import build_investment_memo
    pdf_bytes = build_investment_memo(
        property_name=property_.name,
        property_type=property_.property_type,
        total_area=float(property_.total_area),
        area_unit=property_.area_unit,
        city=property_.city,
        state=property_.state,
        analysis_start_date=analysis_start,
        analysis_period_months=ValuationService._effective_period_months(valuation, property_),
        valuation_name=valuation.name,
        valuation_params=vp,
        key_metrics=response.key_metrics,
        annual_cash_flows=response.annual_cash_flows,
        tenant_cash_flows=response.tenant_cash_flows,
        rent_roll=response.rent_roll,
        lease_expirations=response.lease_expiration_schedule,
    )
    filename = (
        f"investment_memo_{_safe_filename(property_.name)}_{_safe_filename(valuation.name)}.pdf"
    )
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/valuations/{valuation_id}/reports/lease-expirations",
    response_model=list[LeaseExpirationEntry],
)
async def report_lease_expirations(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[LeaseExpirationEntry]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.lease_expiration_schedule


@router.get("/valuations/{valuation_id}/reports/sensitivity", response_model=SensitivityMatrix)
async def report_sensitivity(
    valuation_id: str,
    discount_step: Decimal = Query(default=Decimal("0.0025"), gt=0, lt=Decimal("0.05")),
    exit_cap_step: Decimal = Query(default=Decimal("0.0025"), gt=0, lt=Decimal("0.05")),
    steps: int = Query(default=2, ge=1, le=5),
    db: AsyncSession = Depends(get_session),
) -> SensitivityMatrix:
    """Discount rate x exit cap PV matrix (published DCF software-style) from the last completed run."""
    service = ValuationService(db)
    try:
        matrix = await service.sensitivity(valuation_id, discount_step, exit_cap_step, steps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if matrix is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return matrix


@router.get("/valuations/{valuation_id}/reports/what-if", response_model=WhatIfResult)
async def report_what_if(
    valuation_id: str,
    discount_rate: Decimal | None = Query(default=None, gt=0, lt=1),
    exit_cap_rate: Decimal | None = Query(default=None, gt=0, lt=1),
    db: AsyncSession = Depends(get_session),
) -> WhatIfResult:
    """Value of the last completed run at another discount rate / exit cap. Not saved."""
    service = ValuationService(db)
    try:
        result = await service.what_if(valuation_id, discount_rate, exit_cap_rate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return result


@router.get(
    "/valuations/{valuation_id}/reports/monthly-cash-flows", response_model=list[AnnualCashFlowSummary]
)
async def report_monthly_cash_flows(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[AnnualCashFlowSummary]:
    """Cash flows by month from the current model inputs; `year` is the analysis year."""
    service = ValuationService(db)
    try:
        rows = await service.monthly_cash_flows(valuation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if rows is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return rows


@router.get(
    "/valuations/{valuation_id}/reports/ncreif-forecast",
    response_model=NcreifForecast,
)
async def report_ncreif_forecast(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> NcreifForecast:
    """Projected NCREIF NPI-style quarterly income, capital and chain-linked returns."""
    try:
        result = await ValuationService(db).ncreif_forecast(valuation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return result


@router.get("/valuations/{valuation_id}/reports/key-metrics", response_model=KeyMetricsSummary)
async def report_key_metrics(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> KeyMetricsSummary:
    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    if response.key_metrics is None:
        raise HTTPException(status_code=400, detail="Valuation has not been run yet")
    return response.key_metrics


@router.get(
    "/valuations/{valuation_id}/reports/tenant-detail",
    response_model=list[TenantCashFlowDetail],
)
async def report_tenant_detail(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[TenantCashFlowDetail]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=False)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.tenant_cash_flows


@router.get(
    "/valuations/{valuation_id}/reports/recovery-audit",
    response_model=list[TenantRecoveryAuditEntry],
)
async def report_recovery_audit(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[TenantRecoveryAuditEntry]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.recovery_audit


@router.get("/valuations/{valuation_id}/reports/full", response_model=ValuationRunResponse)
async def report_full(
    valuation_id: str,
    include_recovery_audit: bool = Query(True),
    db: AsyncSession = Depends(get_session),
) -> ValuationRunResponse:
    service = ValuationService(db)
    response = await service.get_results(valuation_id, include_recovery_audit=include_recovery_audit)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response
