import json
import base64
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.config import settings

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.expense import PropertyExpense
from src.models.capital import PropertyCapitalProject
from src.models.lease import FreeRentPeriod, Lease, LeaseExpenseRecovery, RentStep, Tenant
from src.models.market import MarketLeasingProfile
from src.models.other_income import PropertyOtherIncome
from src.models.property import Property, Suite
from src.models.recovery_pool import RecoveryPool
from src.models.recovery_structure import RecoveryStructure, RecoveryStructureItem
from src.models.valuation import Valuation
from src.services.valuation_clone import HOLD_FROM_MODEL_TYPES
from src.models.base import DecimalList
from src.schemas.common import PropertyType


STRUCTURED_PLAN_TOOL = {
    "name": "build_opendcf_valuation_inputs",
    "description": "Convert approved appraisal facts into linked OpenDCF valuation input rows.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "property_updates", "valuation_updates", "suites", "tenants", "leases",
            "market_leasing_profiles", "expenses", "other_income", "capital_projects",
            "rent_steps", "free_rent_periods", "lease_expense_recoveries",
        ],
        "properties": {
            "property_updates": {"type": "object", "additionalProperties": True},
            "valuation_updates": {"type": "object", "additionalProperties": True},
            **{
                name: {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                }
                for name in (
                    "suites", "tenants", "leases", "market_leasing_profiles", "expenses",
                    "other_income", "capital_projects", "rent_steps", "free_rent_periods",
                    "lease_expense_recoveries", "recovery_structures", "recovery_structure_items",
                )
            },
        },
    },
}

LEASE_TABLE_TOOL = {
    "name": "record_complete_rent_roll",
    "description": "Record every legible tenant and lease row from the supplied appraisal pages.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["suites", "tenants", "leases"],
        "properties": {
            name: {"type": "array", "items": {"type": "object", "additionalProperties": True}}
            for name in ("suites", "tenants", "leases")
        },
    },
}


def enrich_plan_leases_from_pdf(plan: dict, facts: list[Any], content: bytes) -> dict:
    """Run a focused table pass over cited rent-roll pages to avoid a partial tenant schedule."""
    from anthropic import Anthropic

    from src.services.document_intelligence import call_tool
    from pypdf import PdfReader, PdfWriter

    pages = [
        fact.page_number for fact in facts
        if fact.page_number and fact.status == "accepted"
        and fact.field_path.startswith(("leases[]", "rent_roll.", "rollover."))
    ]
    if not pages:
        return plan
    reader = PdfReader(io.BytesIO(content))
    start = max(1, min(pages) - 3)
    end = min(len(reader.pages), max(pages) + 3)
    writer = PdfWriter()
    for page_number in range(start, end + 1):
        writer.add_page(reader.pages[page_number - 1])
    stream = io.BytesIO()
    writer.write(stream)
    block = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(stream.getvalue()).decode(),
        },
    }
    prompt = f"""These are appraisal pages {start}-{end}, selected because they contain rent-roll and
lease evidence. Extract EVERY individually legible tenant/suite row, not merely examples or major tenants.
Do not invent obscured values. Return linked OpenDCF rows using these exact conventions:
- suites: source_id, suite_name, area (>0; 0 only for space with no area such as an antenna or sign),
  space_type ('office' or 'retail_bank'), is_available
- tenants: source_id, name
- leases: source_id, source_suite_id, source_tenant_id, lease_start_date, lease_end_date,
  base_rent_per_unit in annual $/SF, rent_payment_frequency='annual', recovery_type using one of
  'nnn', 'full_service_gross', 'modified_gross', 'base_year_stop', or 'none'. For a 0 SF suite set
  rent_basis='total' and base_rent_per_unit to the annual $ amount.
Only include a lease when tenant, suite area, start date, end date, and annual rent are supported.
Call record_complete_rent_roll once."""
    rows = call_tool(Anthropic(api_key=settings.anthropic_api_key), LEASE_TABLE_TOOL,
                     [block, {"type": "text", "text": prompt}])
    if rows.get("leases"):
        plan["suites"] = rows.get("suites", [])
        plan["tenants"] = rows.get("tenants", [])
        plan["leases"] = rows.get("leases", [])
    return normalize_structured_plan(plan)


def structure_plan_with_anthropic(
    plan: dict, facts: list[Any], document_types: dict[str, str] | None = None
) -> dict:
    """Translate reviewed evidence from every source document into linked OpenDCF rows."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    from anthropic import Anthropic

    from src.services.document_intelligence import call_tool

    evidence = [
        {
            "field_path": fact.field_path,
            "value": json.loads(fact.value_json),
            "confidence": fact.confidence,
            "page_number": fact.page_number,
            "source_document_type": (document_types or {}).get(fact.document_id, "unknown"),
        }
        for fact in facts
        if fact.status == "accepted"
    ]
    prompt = """Convert these approved commercial real estate facts into a complete OpenDCF model.
The facts come from several source documents; each lists its source_document_type.
Use only supported facts; do not invent tenant names, areas, dates, rents, or expenses. Group repeated
leases[]. facts into the smallest defensible set of leases. Every tenant, suite, lease, and rent step must
have stable source IDs and linked references. The same lease or expense often appears in more than one
document: model it once.

When sources disagree, prefer:
- tenant schedule (suites, tenants, leases, rent steps, free rent, recoveries): signed leases and
  amendments (the latest amendment wins), then the rent roll, then the appraisal or offering memorandum
- expenses and other income: the operating statement (most recent full year or trailing twelve months),
  then the budget, then the appraisal or offering memorandum
- discount rate, exit cap rate, holding period and market leasing: the appraisal, then the offering
  memorandum

Required row conventions:
- suites: source_id, suite_name, area (>0; 0 only for space with no area such as an antenna or sign),
  space_type, is_available
- tenants: source_id, name
- leases: source_id, source_suite_id, source_tenant_id, lease_start_date, lease_end_date,
  base_rent_per_unit (annual $/SF), rent_payment_frequency='annual', recovery_type (one of 'nnn',
  'full_service_gross', 'modified_gross', 'base_year_stop', 'none'). For a 0 SF suite set
  rent_basis='total' and base_rent_per_unit to the annual $ amount. Include these when the evidence
  supports them (all percentages as fractions, e.g. 0.03):
  escalation_type ('flat', 'pct_annual', 'fixed_step' when rent_steps list the increases, 'cpi'),
  escalation_pct_annual, cpi_floor, cpi_cap, pro_rata_share_pct (tenant's share of the building),
  base_year (integer year), base_year_stop_amount (total annual $ of the base-year stop),
  expense_stop_per_sf (for modified_gross), upon_expiration ('market', 'renew', 'vacate', 'option',
  'reabsorb'), option_rent_per_unit (annual $/SF, omit when the option is at market),
  option_term_months, committed_ti_amount and committed_lc_amount (total $ still owed),
  pct_rent_breakpoint, pct_rent_rate, source_recovery_structure_id
- lease_expense_recoveries: one row per lease and expense whose recovery differs from the lease's
  recovery_type or has a cap, floor, fee or its own stop: source_lease_id, expense_category (must equal
  an expenses[].category), recovery_type, base_year_stop_amount, cap_per_sf_annual, cap_growth_pct,
  floor_per_sf_annual, admin_fee_pct, cap_group (the same label on every controllable expense that
  shares one cap), expense_stop_per_sf (a modified_gross expense's own $/SF stop; leave
  floor_per_sf_annual for floors), comment (quote the clause briefly). Base-year stops are pooled: every expense
  recovered over a base year shares one stop (the lease's base_year_stop_amount, or the base year's
  total), and a lease_expense_recoveries row takes its expense out of that pool. So for a base_year_stop
  lease, add a row only for an expense the lease treats separately (its own stop, or a different method).
- recovery_structures and recovery_structure_items: only when several leases share identical recovery
  terms. Structure: source_id, name, default_recovery_type, expense_stop_per_sf (the $/SF stop when the
  default is modified_gross). Item: source_recovery_structure_id, expense_category, recovery_type, the
  same optional fields as lease_expense_recoveries, and expense_stop_per_sf (a modified_gross
  category's own $/SF stop; leave floor_per_sf_annual for floors). Leases then
  set source_recovery_structure_id instead of repeating lease_expense_recoveries rows.
- free_rent_periods: source_lease_id, start_date, end_date, applies_to_base_rent,
  applies_to_recoveries
- market_leasing_profiles: source_id, space_type matching suites, market_rent_per_unit,
  rent_growth_rate_pct; use conservative defaults only for rollover mechanics when absent
- expenses: category as a snake_case label (real_estate_taxes, insurance, cam, utilities,
  management_fee, repairs_maintenance, general_admin, or another), base_year_amount, amount_basis
  ('total' or 'per_area'), growth_rate_pct, is_recoverable; do not duplicate the same expense conclusion
- other_income: category, base_year_amount, growth_rate_pct
- rent_steps: source_lease_id, effective_date, rent_per_unit
- capital_projects: one-time building improvements only: description, total_amount ($), start_date,
  duration_months (spend spreads evenly over it). Recurring capital reserves are not a project: put
  them in valuation_updates.capital_reserves_per_unit ($/SF or $/unit a year).
- property_updates and valuation_updates should contain direct OpenDCF field names.
An amendment overrides the original lease for the terms it changes, from its effective date.
Return empty arrays for categories unsupported by the evidence. Facts JSON follows:\n""" + json.dumps(evidence, default=str)
    structured = call_tool(Anthropic(api_key=settings.anthropic_api_key), STRUCTURED_PLAN_TOOL, prompt)
    plan["property"].update(structured.pop("property_updates", {}) or {})
    plan["valuation"].update(structured.pop("valuation_updates", {}) or {})
    for name, rows in structured.items():
        if isinstance(rows, list):
            plan[name] = rows
    refresh_fact_overlays(plan)
    return normalize_structured_plan(plan)


def _fraction(value: Any) -> Any:
    percent_text = isinstance(value, str) and value.strip().endswith("%")
    try:
        number = Decimal(str(value).strip().replace("%", "").replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        return value
    return str(number / 100) if percent_text or abs(number) > 1 else str(number)


RECOVERY_CODES = {
    "NNN": "nnn", "TRIPLE_NET": "nnn", "NET": "nnn", "FSG": "full_service_gross",
    "FULL_SERVICE_GROSS": "full_service_gross", "GROSS": "full_service_gross",
    "MODIFIED_GROSS": "modified_gross", "BASE_YEAR": "base_year_stop",
    "BASE_YEAR_STOP": "base_year_stop", "NONE": "none", "ABSOLUTE_NET": "none",
}
RECOVERY_TYPES = {"nnn", "full_service_gross", "modified_gross", "base_year_stop", "none"}
ESCALATION_CODES = {
    "NONE": "flat", "FLAT": "flat", "FIXED": "fixed_step", "FIXED_STEP": "fixed_step",
    "STEP": "fixed_step", "STEPS": "fixed_step", "PERCENT": "pct_annual", "PCT": "pct_annual",
    "PCT_ANNUAL": "pct_annual", "ANNUAL": "pct_annual", "PERCENTAGE": "pct_annual",
    "PERCENT_ANNUAL": "pct_annual", "CPI": "cpi",
}
ESCALATION_TYPES = {"flat", "pct_annual", "fixed_step", "cpi"}
# Rates that are never 100% or more, so a bare 1 means 1%. pro_rata_share_pct is left out: 1 is 100%.
SMALL_RATES = {
    "escalation_pct_annual": "annual escalation", "cpi_floor": "CPI floor", "cpi_cap": "CPI cap",
    "pct_rent_rate": "percentage rent rate", "cap_growth_pct": "recovery cap growth",
    "admin_fee_pct": "admin fee",
}
UPON_EXPIRATION = {"market", "renew", "vacate", "option", "reabsorb"}
LEASE_FRACTIONS = ("escalation_pct_annual", "cpi_floor", "cpi_cap", "pro_rata_share_pct", "pct_rent_rate")
RECOVERY_FRACTIONS = ("cap_growth_pct", "admin_fee_pct")


def _code(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_").replace("/", "_")


def _category(value: Any) -> str:
    return "_".join(str(value or "").strip().lower().replace("&", " ").replace("/", " ").split())


def _normalize_lease_terms(plan: dict) -> None:
    """Coerce lease and recovery rows to engine enums and fractions; note anything that won't apply."""
    notes = plan.setdefault("review_notes", [])
    tenant_names = {row.get("source_id"): row.get("name") for row in plan.get("tenants", [])}
    lease_tenant = {
        row.get("source_id"): tenant_names.get(row.get("source_tenant_id"), row.get("source_id"))
        for row in plan.get("leases", [])
    }
    def rate(row: dict, key: str, who: str) -> None:
        value = _fraction(row[key])
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return
        if key in SMALL_RATES and number >= 1:
            number /= 100
            notes.append(f"{who}: {SMALL_RATES[key]} of {value} read as {(number * 100).normalize():f}%. Check it.")
        row[key] = str(number)

    stepped = {row.get("source_lease_id") for row in plan.get("rent_steps", [])}
    for row in plan.get("leases", []):
        who = lease_tenant.get(row.get("source_id")) or "A lease"
        if row.get("escalation_type"):
            raw = row["escalation_type"]
            code = _code(raw)
            code = ESCALATION_CODES.get(code, "cpi" if code.startswith("CPI") else code.lower())
            if code not in ESCALATION_TYPES:
                code = ("pct_annual" if row.get("escalation_pct_annual")
                        else "fixed_step" if row.get("source_id") in stepped else "flat")
                notes.append(f"{who}: escalation '{raw}' is not recognised and was set to {code}. Check it.")
            row["escalation_type"] = code
        elif row.get("escalation_pct_annual"):
            row["escalation_type"] = "pct_annual"
        if row.get("upon_expiration") and str(row["upon_expiration"]).lower() not in UPON_EXPIRATION:
            row.pop("upon_expiration")
        elif row.get("upon_expiration"):
            row["upon_expiration"] = str(row["upon_expiration"]).lower()
        for key in LEASE_FRACTIONS:
            if row.get(key) not in (None, ""):
                rate(row, key, who)
        if row.get("base_year") not in (None, ""):
            try:
                row["base_year"] = int(str(row["base_year"]).strip()[:4])
            except ValueError:
                row.pop("base_year")
    categories = set()
    for row in plan.get("expenses", []):
        row["category"] = _category(row.get("category"))
        categories.add(row["category"])
    structure_ids = {row.get("source_id") for row in plan.get("recovery_structures", [])}
    for row in plan.get("recovery_structures", []):
        code = RECOVERY_CODES.get(_code(row.get("default_recovery_type")), _code(row.get("default_recovery_type")).lower())
        row["default_recovery_type"] = code if code in RECOVERY_TYPES else "nnn"
    kept_items = []
    for row in plan.get("recovery_structure_items", []):
        if row.get("source_recovery_structure_id") not in structure_ids:
            notes.append(f"Dropped a shared recovery term for {row.get('expense_category')}: its recovery setup is missing.")
            continue
        kept_items.append(row)
    plan["recovery_structure_items"] = kept_items
    for collection in ("lease_expense_recoveries", "recovery_structure_items"):
        for row in plan.get(collection, []):
            row["expense_category"] = _category(row.get("expense_category"))
            code = RECOVERY_CODES.get(_code(row.get("recovery_type")), _code(row.get("recovery_type")).lower())
            row["recovery_type"] = code if code in RECOVERY_TYPES else "nnn"
            who = lease_tenant.get(row.get("source_lease_id")) or "A shared recovery setup"
            for key in RECOVERY_FRACTIONS:
                if row.get(key) not in (None, ""):
                    rate(row, key, who)
            if categories and row["expense_category"] not in categories:
                notes.append(
                    f"{who}: recovery terms for '{row['expense_category']}' match no expense in the "
                    "model, so they won't apply. Rename the category in Edit details."
                )


def _property_type_code(value: Any) -> str | None:
    """A known property type code for a code or description ("Class A office tower"), else None."""
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    codes = [t.value for t in PropertyType]
    return text if text in codes else next(
        (c for c in codes if c.replace("_", " ") in text.replace("_", " ")), None)


def normalize_structured_plan(plan: dict) -> dict:
    """Normalize model-produced rows to OpenDCF's enums, links, and fractional rates."""
    recovery_codes = RECOVERY_CODES
    plan["review_notes"] = []
    def space_code(value: Any) -> str:
        text = str(value or "office").strip().lower().replace("/", "_").replace(" ", "_")
        return {"retail_bank_branch": "retail_bank", "retail_bank": "retail_bank"}.get(text, text)

    prop = plan.get("property") or {}
    if prop.get("property_type") is not None:
        match = _property_type_code(prop["property_type"])
        if match:
            prop["property_type"] = match
        else:
            plan["review_notes"].append(
                f"Property type '{prop['property_type']}' is not recognised; the current type was kept."
            )
            prop.pop("property_type")
    profiles = plan.get("market_leasing_profiles", [])
    for row in profiles:
        row["space_type"] = space_code(row.get("space_type"))
    for row in profiles:
        row["rent_growth_rate_pct"] = _fraction(row.get("rent_growth_rate_pct", 0.03))
        row.pop("recovery_type", None)
    for row in plan.get("suites", []):
        row["space_type"] = space_code(row.get("space_type"))
        row.setdefault("is_available", True)
    for row in plan.get("leases", []):
        recovery = _code(row.get("recovery_type") or "nnn")
        recovery = recovery_codes.get(recovery, recovery.lower())
        if recovery not in RECOVERY_TYPES:
            plan["review_notes"].append(
                f"Lease {row.get('source_id')}: recovery type '{row.get('recovery_type')}' is not "
                "recognised and was set to NNN. Check it in the lease terms."
            )
            recovery = "nnn"
        row["recovery_type"] = recovery
        row.setdefault("rent_payment_frequency", "annual")
        if row.get("rent_basis") not in ("per_area", "total"):
            row["rent_basis"] = "per_area"
        if not row.get("lease_start_date") and not row.get("lease_end_date"):
            start = date.fromisoformat(str(plan["property"]["analysis_start_date"]))
            row["lease_start_date"] = start.isoformat()
            row["lease_end_date"] = date(
                start.year + (1 if start.month == 12 else 0),
                1 if start.month == 12 else start.month + 1,
                1,
            ).isoformat()
            row["lease_type"] = "month_to_month"
            row["comment"] = (
                (str(row.get("comment", "")).strip() + " ").lstrip()
                + "Modeled as month-to-month: appraisal rent roll supplied current rent without fixed dates."
            )
    normalized_expenses = []
    for row in plan.get("expenses", []):
        row["growth_rate_pct"] = _fraction(row.get("growth_rate_pct", 0.03))
        row.setdefault("amount_basis", "total")
        row.setdefault("is_recoverable", True)
        category_code = str(row.get("category", "")).strip().lower().replace(" ", "_")
        if category_code == "management_fee":
            pct = row.get("pct_of_egi", row.get("base_year_amount", 0.03))
            row.update(
                base_year_amount=0,
                amount_basis="total",
                is_pct_of_egi=True,
                pct_of_egi=_fraction(pct),
                is_recoverable=False,
            )
        elif category_code == "capital_reserves":
            plan["valuation"]["capital_reserves_per_unit"] = row.get("base_year_amount", 0)
            continue
        normalized_expenses.append(row)
    plan["expenses"] = normalized_expenses
    for row in plan.get("other_income", []):
        row["growth_rate_pct"] = _fraction(row.get("growth_rate_pct", 0.03))
    plan["lease_expense_recoveries"] = [
        row for row in plan.get("lease_expense_recoveries", [])
        if row.get("source_lease_id") and row.get("expense_category") and row.get("recovery_type")
    ]
    _normalize_capital_projects(plan)
    _normalize_lease_terms(plan)
    # An initial rent step duplicates the lease's base rent and is not an escalation.
    lease_by_id = {row.get("source_id"): row for row in plan.get("leases", [])}
    plan["rent_steps"] = [
        row for row in plan.get("rent_steps", [])
        if not (
            (lease := lease_by_id.get(row.get("source_lease_id")))
            and row.get("effective_date") == lease.get("lease_start_date")
            and Decimal(str(row.get("rent_per_unit", 0))) == Decimal(str(lease.get("base_rent_per_unit", 0)))
        )
    ]
    return plan


def _normalize_capital_projects(plan: dict) -> None:
    """Keep only one-time projects the model can store; recurring reserves and incomplete rows
    become review notes instead of failing when the plan is applied."""
    kept = []
    for row in plan.get("capital_projects", []):
        row.setdefault("description", row.pop("name", None))
        row.setdefault("total_amount", row.pop("amount", None))
        label = row.get("description") or "Capital item"
        recurring = row.get("is_recurring") or row.get("frequency") in ("annual", "monthly", "quarterly")
        if recurring or "reserve" in str(label).lower():
            plan["review_notes"].append(
                f"{label} ({row.get('total_amount')} {row.get('frequency') or 'recurring'}) is a recurring reserve, "
                "not a capital project; not added. Set Capital Reserves on the valuation if it applies."
            )
            continue
        row["duration_months"] = row.get("duration_months") or 1
        try:
            amount_ok = Decimal(str(row.get("total_amount"))) > 0
        except InvalidOperation:
            amount_ok = False
        if not amount_ok or not row.get("start_date"):
            plan["review_notes"].append(f"{label}: no amount or start date in the evidence; not added.")
            continue
        kept.append(row)
    plan["capital_projects"] = kept


def _value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def snapshot(obj: Any, exclude: set[str] | None = None) -> dict:
    excluded = {"id", "created_at", "updated_at"} | (exclude or set())
    return {
        column.name: _value(getattr(obj, column.name))
        for column in obj.__table__.columns
        if column.name not in excluded
    }


async def build_plan(db: AsyncSession, valuation: Valuation, facts: list[Any]) -> tuple[dict, list]:
    prop = await db.get(Property, valuation.property_id)
    suites = list((await db.execute(select(Suite).where(Suite.valuation_id == valuation.id))).scalars())
    suite_ids = [item.id for item in suites]
    tenants = list(
        (await db.execute(select(Tenant).where(Tenant.valuation_id == valuation.id))).scalars()
    )
    profiles = list(
        (
            await db.execute(
                select(MarketLeasingProfile).where(MarketLeasingProfile.valuation_id == valuation.id)
            )
        ).scalars()
    )
    expenses = list(
        (
            await db.execute(select(PropertyExpense).where(PropertyExpense.valuation_id == valuation.id))
        ).scalars()
    )
    leases = (
        list((await db.execute(select(Lease).where(Lease.suite_id.in_(suite_ids)))).scalars())
        if suite_ids
        else []
    )
    lease_ids = [item.id for item in leases]
    rent_steps = list((await db.execute(select(RentStep).where(RentStep.lease_id.in_(lease_ids)))).scalars()) if lease_ids else []
    free_rent = list((await db.execute(select(FreeRentPeriod).where(FreeRentPeriod.lease_id.in_(lease_ids)))).scalars()) if lease_ids else []
    recovery_overrides = list((await db.execute(select(LeaseExpenseRecovery).where(LeaseExpenseRecovery.lease_id.in_(lease_ids)))).scalars()) if lease_ids else []
    other_income = list((await db.execute(select(PropertyOtherIncome).where(PropertyOtherIncome.valuation_id == valuation.id))).scalars())
    capital_projects = list((await db.execute(select(PropertyCapitalProject).where(PropertyCapitalProject.valuation_id == valuation.id))).scalars())
    recovery_structures = list((await db.execute(select(RecoveryStructure).where(RecoveryStructure.valuation_id == valuation.id))).scalars())
    recovery_ids = [item.id for item in recovery_structures]
    recovery_items = list((await db.execute(select(RecoveryStructureItem).where(RecoveryStructureItem.recovery_structure_id.in_(recovery_ids)))).scalars()) if recovery_ids else []
    recovery_pools = list((await db.execute(select(RecoveryPool).where(RecoveryPool.valuation_id == valuation.id))).scalars())

    plan = {
        "property": snapshot(prop)
        | {"name": f"{prop.name} — Imported Appraisal", "external_id": None},
        "suites": [snapshot(item, {"property_id", "valuation_id"}) | {"source_id": item.id} for item in suites],
        "tenants": [snapshot(item, {"property_id", "valuation_id"}) | {"source_id": item.id} for item in tenants],
        "market_leasing_profiles": [
            snapshot(item, {"property_id", "valuation_id", "next_profile_id", "recovery_structure_id"})
            | {"source_id": item.id, "source_next_profile_id": item.next_profile_id,
               "source_recovery_structure_id": item.recovery_structure_id}
            for item in profiles
        ],
        "expenses": [snapshot(item, {"property_id", "valuation_id"}) for item in expenses],
        "other_income": [snapshot(item, {"property_id", "valuation_id"}) for item in other_income],
        "capital_projects": [snapshot(item, {"property_id", "valuation_id"}) for item in capital_projects],
        "recovery_pools": [snapshot(item, {"property_id", "valuation_id"}) for item in recovery_pools],
        "recovery_structures": [
            snapshot(item, {"property_id", "valuation_id"}) | {"source_id": item.id}
            for item in recovery_structures
        ],
        "recovery_structure_items": [
            snapshot(item, {"recovery_structure_id"})
            | {"source_recovery_structure_id": item.recovery_structure_id}
            for item in recovery_items
        ],
        "leases": [
            snapshot(item, {"suite_id", "tenant_id", "recovery_structure_id"})
            | {
                "source_id": item.id,
                "source_suite_id": item.suite_id,
                "source_tenant_id": item.tenant_id,
                "source_recovery_structure_id": item.recovery_structure_id,
            }
            for item in leases
        ],
        "rent_steps": [
            snapshot(item, {"lease_id"}) | {"source_lease_id": item.lease_id}
            for item in rent_steps
        ],
        "free_rent_periods": [
            snapshot(item, {"lease_id"}) | {"source_lease_id": item.lease_id}
            for item in free_rent
        ],
        "lease_expense_recoveries": [
            snapshot(item, {"lease_id"}) | {"source_lease_id": item.lease_id}
            for item in recovery_overrides
        ],
        "valuation": snapshot(
            valuation,
            {
                "property_id",
                "status",
                "error_message",
                "review_status",  # a rebuilt valuation starts as a draft, never frozen
                "snapshot_id",
                "prior_valuation_id",
                *{
                    column.name
                    for column in Valuation.__table__.columns
                    if column.name.startswith("result_")
                },
            },
        )
        | {"name": f"{valuation.name} — Imported Appraisal"},
        "appraisal_facts": [],
    }
    unresolved = []
    for fact in facts:
        entry = {
            "field_path": fact.field_path,
            "value": json.loads(fact.value_json),
            "confidence": fact.confidence,
            "page_number": fact.page_number,
            "source_quote": fact.source_quote,
            "review_status": fact.status,
            "resolved": fact.status == "accepted",
        }
        plan["appraisal_facts"].append(entry)
        if not apply_simple_fact(plan, entry):
            unresolved.append(entry)
    return plan, unresolved


def apply_simple_fact(plan: dict, fact: dict) -> bool:
    """Overlay unambiguous property/valuation appraisal facts; arrays stay reviewable."""
    path = fact["field_path"].strip().lower()
    if fact.get("review_status") not in {None, "accepted"}:
        return False
    aliases = {
        "appraisal.property_name": ("property", "name", lambda value: str(value)),
        "property.address": ("property", "address_line1", lambda value: str(value)),
        "property.total_rentable_area_sf": ("property", "total_area", lambda value: value),
        "property.net_rentable_area_sf": ("property", "total_area", lambda value: value),
        "property.rentable_area_sf": ("property", "total_area", lambda value: value),
        "property.year_built": ("property", "year_built", lambda value: value),
        "dcf_assumptions.cash_flow_commencement_date": (
            "property", "analysis_start_date", lambda value: value
        ),
        "dcf_assumptions.holding_period_years": (
            "property", "analysis_period_months", lambda value: int(value) * 12
        ),
        "valuation.holding_period_years": (
            "property", "analysis_period_months", lambda value: int(value) * 12
        ),
        "dcf_assumptions.discount_rate": ("valuation", "discount_rate", lambda value: value),
        "dcf_assumptions.terminal_cap_rate": ("valuation", "exit_cap_rate", lambda value: value),
        "dcf_assumptions.reversion_cost_of_sale_pct": (
            "valuation", "exit_costs_pct", lambda value: value
        ),
    }
    if path in aliases:
        root, key, transform = aliases[path]
        plan[root][key] = transform(fact["value"])
        fact["mapped_to"] = f"{root}.{key}"
        return True
    parts = path.split(".")
    if len(parts) != 2 or parts[0] not in {"property", "valuation"}:
        return False
    target = plan[parts[0]]
    if parts[1] not in target:
        return False
    value = fact["value"]
    if path == "property.property_type":
        # Facts are reapplied after normalizing; keep the plan's code unless the fact names a known one
        value = _property_type_code(value)
        if value is None:
            return False
    target[parts[1]] = value
    fact["mapped_to"] = path
    return True


def refresh_fact_overlays(plan: dict) -> dict:
    """Reapply reviewed facts so saved plans benefit from newer mapping rules."""
    for fact in plan.get("appraisal_facts", []):
        apply_simple_fact(plan, fact)
    plan.setdefault("property", {})["external_id"] = None
    valuation = plan.setdefault("valuation", {})
    if valuation.get("name", "").startswith("AI Appraisal Import"):
        valuation["name"] = f"{plan['property'].get('name', 'Imported Property')} Valuation"
    return plan


def update_existing_roots(prop: Property, valuation: Valuation, plan: dict) -> None:
    """Synchronize an already-created valuation after an idempotent retry. A property the
    valuation was added to (rather than created with it) keeps its own identity."""
    if not plan.get("target_property_id"):
        for key, value in _coerce(Property, plan.get("property", {}), {"id"}).items():
            setattr(prop, key, value)
        prop.external_id = None
    excluded = {
        "id",
        "property_id",
        "status",
        "error_message",
        "review_status",
        "snapshot_id",
        "prior_valuation_id",
        *{
            column.name
            for column in Valuation.__table__.columns
            if column.name.startswith("result_")
        },
    }
    for key, value in _coerce(Valuation, plan.get("valuation", {}), excluded).items():
        setattr(valuation, key, value)


def _coerce(model: type, values: dict, excluded: set[str] | None = None) -> dict:
    excluded = (excluded or set()) | {
        "id", "created_at", "updated_at", "source_id", "source_suite_id", "source_tenant_id"
    }
    columns = {column.name: column for column in model.__table__.columns}
    output = {}
    for key, value in values.items():
        if key in excluded or key not in columns or value is None:
            continue
        try:
            pytype = columns[key].type.python_type
        except (AttributeError, NotImplementedError):
            pytype = None
        if pytype is date and isinstance(value, str):
            value = date.fromisoformat(value)
        elif pytype is datetime and isinstance(value, str):
            value = datetime.fromisoformat(value)
        elif pytype is Decimal:
            value = Decimal(str(value))
        elif isinstance(columns[key].type, DecimalList):
            # A list of rates by year; anything else (e.g. a {"2028": ...} mapping) is dropped so
            # the flat rate applies, rather than storing labels that cannot be read back
            try:
                value = [Decimal(str(v)) for v in value] if isinstance(value, list) else None
            except InvalidOperation:
                value = None
            if not value or any(abs(v) >= 1 for v in value):  # rates are fractions; years are not
                continue
        output[key] = value
    return output


async def materialize_plan(
    db: AsyncSession, plan: dict, property_: Property | None = None
) -> tuple[Property, Valuation]:
    """Create the plan's valuation and its whole model, under `property_` when given (a new
    valuation of an existing property), else under a new property built from the plan."""
    refresh_fact_overlays(plan)
    if property_ is not None:
        prop = property_
    else:
        prop = Property(**_coerce(Property, plan["property"], {"id"}))
        db.add(prop)
        await db.flush()
    # Every input row belongs to the valuation, so it exists first
    valuation = Valuation(
        property_id=prop.id,
        **_coerce(Valuation, plan["valuation"], {"id", "property_id", "status", "error_message", "prior_valuation_id"}),
    )
    valuation.status = "draft"
    # A rebuilt valuation is a new draft: it is not the source's frozen review copy
    valuation.review_status = "draft"
    valuation.snapshot_id = None
    # Dates and operating model as the plan's property had them, when the plan's valuation predates
    # valuation-owned inputs
    planned = plan.get("property", {})
    if valuation.analysis_start_date_override is None and planned.get("analysis_start_date"):
        valuation.analysis_start_date_override = _coerce(Property, planned, {"id"}).get("analysis_start_date")
    if valuation.analysis_period_months_override is None and prop.property_type not in HOLD_FROM_MODEL_TYPES:
        valuation.analysis_period_months_override = planned.get("analysis_period_months") or prop.analysis_period_months
    for column in ("marina_assumptions_json", "seniors_housing_assumptions_json", "self_storage_assumptions_json"):
        if getattr(valuation, column) is None and planned.get(column):
            setattr(valuation, column, planned[column])
    db.add(valuation)
    await db.flush()
    owner = {"property_id": prop.id, "valuation_id": valuation.id}

    tenant_map: dict[str, str] = {}
    for row in plan.get("tenants", []):
        item = Tenant(**owner, **_coerce(Tenant, row, {"id", "property_id", "valuation_id"}))
        db.add(item)
        await db.flush()
        tenant_map[row.get("source_id", "")] = item.id

    profile_map: dict[str, str] = {}
    for row in plan.get("market_leasing_profiles", []):
        item = MarketLeasingProfile(
            **owner,
            **_coerce(MarketLeasingProfile, row,
                      {"id", "property_id", "valuation_id", "next_profile_id", "recovery_structure_id"}),
        )
        db.add(item)
        await db.flush()
        profile_map[row.get("source_id", "")] = item.id
    for row in plan.get("market_leasing_profiles", []):
        source_next = row.get("source_next_profile_id")
        if source_next:
            current = await db.get(MarketLeasingProfile, profile_map[row.get("source_id", "")])
            current.next_profile_id = profile_map.get(source_next)

    suite_map: dict[str, str] = {}
    for row in plan.get("suites", []):
        values = _coerce(Suite, row, {"id", "property_id", "valuation_id"})
        old_profile = row.get("market_leasing_profile_id")  # plans staged before b7e2c4d9a1f3
        if old_profile and not values.get("market_space_type"):
            values["market_space_type"] = next(
                (p.get("space_type") for p in plan.get("market_leasing_profiles", [])
                 if p.get("source_id") == old_profile), None)
        item = Suite(**owner, **values)
        db.add(item)
        await db.flush()
        suite_map[row.get("source_id", "")] = item.id

    for row in plan.get("expenses", []):
        db.add(
            PropertyExpense(
                **owner, **_coerce(PropertyExpense, row, {"id", "property_id", "valuation_id"})
            )
        )
    for row in plan.get("other_income", []):
        db.add(PropertyOtherIncome(**owner, **_coerce(PropertyOtherIncome, row, {"id", "property_id", "valuation_id"})))
    # Plans saved before capital rows were normalized can hold reserves or incomplete rows
    staged = {"capital_projects": [dict(r) for r in plan.get("capital_projects", [])], "review_notes": []}
    _normalize_capital_projects(staged)
    for row in staged["capital_projects"]:
        db.add(PropertyCapitalProject(**owner, **_coerce(PropertyCapitalProject, row, {"id", "property_id", "valuation_id"})))

    # Pools leave suites out of their denominator by id: point them at the new suites
    for row in plan.get("recovery_pools", []):
        db.add(RecoveryPool(
            **owner,
            **_coerce(RecoveryPool, row, {"id", "property_id", "valuation_id", "excluded_suite_ids"}),
            excluded_suite_ids=[suite_map[s] for s in row.get("excluded_suite_ids") or [] if s in suite_map],
        ))

    recovery_map: dict[str, str] = {}
    for row in plan.get("recovery_structures", []):
        item = RecoveryStructure(**owner, **_coerce(RecoveryStructure, row, {"id", "property_id", "valuation_id"}))
        db.add(item)
        await db.flush()
        recovery_map[row.get("source_id", "")] = item.id
    for row in plan.get("recovery_structure_items", []):
        structure_id = recovery_map.get(row.get("source_recovery_structure_id", ""))
        if not structure_id:
            raise ValueError("Every recovery structure item must reference a staged structure")
        db.add(RecoveryStructureItem(recovery_structure_id=structure_id, **_coerce(RecoveryStructureItem, row, {"id", "recovery_structure_id"})))
    for row in plan.get("market_leasing_profiles", []):
        source_structure = row.get("source_recovery_structure_id")
        if source_structure:
            current = await db.get(MarketLeasingProfile, profile_map[row.get("source_id", "")])
            current.recovery_structure_id = recovery_map.get(source_structure)

    lease_map: dict[str, str] = {}
    for row in plan.get("leases", []):
        suite_id = suite_map.get(row.get("source_suite_id", ""))
        if not suite_id:
            raise ValueError("Every staged lease must reference a staged suite")
        values = _coerce(Lease, row, {"id", "suite_id", "tenant_id", "recovery_structure_id"})
        values["tenant_id"] = tenant_map.get(row.get("source_tenant_id", ""))
        values["recovery_structure_id"] = recovery_map.get(row.get("source_recovery_structure_id", ""))
        item = Lease(suite_id=suite_id, **values)
        db.add(item)
        await db.flush()
        lease_map[row.get("source_id", "")] = item.id
    for collection, model in (
        ("rent_steps", RentStep),
        ("free_rent_periods", FreeRentPeriod),
        ("lease_expense_recoveries", LeaseExpenseRecovery),
    ):
        for row in plan.get(collection, []):
            lease_id = lease_map.get(row.get("source_lease_id", ""))
            if not lease_id:
                raise ValueError(f"Every staged {collection} row must reference a staged lease")
            db.add(model(lease_id=lease_id, **_coerce(model, row, {"id", "lease_id"})))
    await db.flush()
    return prop, valuation
