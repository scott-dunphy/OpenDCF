import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from anthropic import Anthropic
from pydantic import ValidationError
from sqlalchemy import inspect

from src.config import settings

COPILOT_TOOL = {
    "name": "respond_to_valuation_request",
    "description": "Answer a question about the supplied model or propose precise model edits.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action_type", "message", "changes"],
        "properties": {
            "action_type": {"type": "string", "enum": ["answer", "propose_changes"]},
            "message": {"type": "string"},
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["entity_type", "entity_id", "field", "new_value", "reason"],
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "enum": [
                                "valuation",
                                "property",
                                "suite",
                                "tenant",
                                "lease",
                                "market_leasing_profile",
                            ],
                        },
                        "entity_id": {"type": "string"},
                        "field": {"type": "string"},
                        "new_value": {},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    },
}

ALLOWED_FIELDS = {
    "valuation": {
        "discount_rate",
        "exit_cap_rate",
        "exit_costs_pct",
        "capital_reserves_per_unit",
        "cpi_rate",
        "purchase_price",
        "direct_cap_rate",
        "analysis_start_date_override",
        "analysis_period_months_override",
    },
    "property": {"total_area", "amenities"},
    "suite": {
        "area",
        "space_type",
        "is_available",
        "absorption_start_date",
        "lease_up_months",
        "market_space_type",
    },
    "tenant": {"name", "credit_rating", "industry"},
    "lease": {
        "lease_start_date",
        "lease_end_date",
        "base_rent_per_unit",
        "escalation_pct_annual",
        "recovery_type",
        "renewal_probability",
        "renewal_rent_spread_pct",
        "upon_expiration",
    },
    "market_leasing_profile": {
        "market_rent_per_unit",
        "rent_growth_rate_pct",
        "new_lease_term_months",
        "downtime_months",
        "renewal_probability",
        "renewal_lease_term_months",
        "general_vacancy_pct",
        "credit_loss_pct",
    },
}

_FRACTION_FIELDS = {
    "discount_rate", "exit_cap_rate", "exit_costs_pct", "cpi_rate",
    "escalation_pct_annual", "renewal_probability", "renewal_rent_spread_pct",
    "rent_growth_rate_pct", "general_vacancy_pct", "credit_loss_pct",
}
_NONNEGATIVE_FIELDS = {
    "capital_reserves_per_unit", "purchase_price", "direct_cap_rate", "total_area", "area",
    "lease_up_months", "base_rent_per_unit", "market_rent_per_unit", "new_lease_term_months",
    "downtime_months", "renewal_lease_term_months",
}


def ask_copilot(message: str, context: dict[str, Any]) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    instruction = (
        "You are the OpenDCF valuation copilot. Use only the supplied model state. For questions, "
        "answer with the value and identify its semantic source. For edits, propose the smallest "
        "exact change. Percent fields are stored as decimals (65% = 0.65). Never invent entity "
        "IDs or fields. "
        "If a name is ambiguous, answer that clarification is required and propose no changes.\n\n"
        f"MODEL STATE:\n{json.dumps(context, default=str)}\n\nUSER:\n{message}"
    )
    response = Anthropic(api_key=settings.anthropic_api_key).messages.create(
        model=settings.anthropic_document_model,
        max_tokens=4096,
        tools=[COPILOT_TOOL],
        tool_choice={"type": "tool", "name": COPILOT_TOOL["name"]},
        messages=[{"role": "user", "content": instruction}],
    )
    for item in response.content:
        if getattr(item, "type", None) == "tool_use":
            return dict(item.input)
    raise RuntimeError("Anthropic returned no structured copilot response")


def validate_changes(changes: list[dict], entities: dict[tuple[str, str], Any]) -> list[dict]:
    validated = []
    for change in changes:
        kind, entity_id, field = change["entity_type"], change["entity_id"], change["field"]
        if field not in ALLOWED_FIELDS.get(kind, set()):
            raise ValueError(f"Copilot may not change {kind}.{field}")
        entity = entities.get((kind, entity_id))
        if entity is None:
            raise ValueError(f"Entity is not in this valuation: {kind} {entity_id}")
        old = getattr(entity, field)
        column = inspect(type(entity)).columns[field]
        value = change["new_value"]
        python_type = getattr(column.type, "python_type", None)
        if value is not None and python_type is Decimal:
            try:
                value = Decimal(str(value))
            except InvalidOperation:
                raise ValueError(f"{kind}.{field}: '{value}' is not a number") from None
        elif value is not None and python_type is bool:
            if isinstance(value, bool):
                pass
            elif isinstance(value, str) and value.strip().lower() in {"true", "false"}:
                value = value.strip().lower() == "true"
            else:
                raise ValueError(f"{kind}.{field} must be true or false")
        elif value is not None and python_type is date:
            value = date.fromisoformat(value) if isinstance(value, str) else value
            if not isinstance(value, date):
                raise ValueError(f"{kind}.{field} must be an ISO date")
        elif value is not None and python_type in {int, float, str}:
            value = python_type(value)
        if value is None and not column.nullable:
            raise ValueError(f"{kind}.{field} may not be null")
        if field in _FRACTION_FIELDS and value is not None and not Decimal("-1") <= Decimal(str(value)) <= Decimal(1):
            raise ValueError(f"{kind}.{field} must be between -1 and 1")
        if field in _NONNEGATIVE_FIELDS and value is not None and Decimal(str(value)) < 0:
            raise ValueError(f"{kind}.{field} may not be negative")
        validated.append({**change, "new_value": value, "old_value": old})
    projected = {
        key: {column.name: getattr(entity, column.name) for column in inspect(type(entity)).columns}
        for key, entity in entities.items()
    }
    for change in validated:
        projected[(change["entity_type"], change["entity_id"])][change["field"]] = change["new_value"]
    for (kind, _), values in projected.items():
        if kind == "lease" and values.get("lease_start_date") and values.get("lease_end_date"):
            if values["lease_end_date"] < values["lease_start_date"]:
                raise ValueError("lease.lease_end_date must be on or after lease_start_date")
    leases_by_suite: dict[str, list[dict]] = {}
    for (kind, _), values in projected.items():
        if kind == "lease":
            leases_by_suite.setdefault(values["suite_id"], []).append(values)
    for leases in leases_by_suite.values():
        ordered = sorted(leases, key=lambda item: item["lease_start_date"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["lease_start_date"] <= previous["lease_end_date"]:
                raise ValueError("Copilot change would create overlapping leases in a suite")
    return validated


def assert_proposal_is_current(changes: list[dict], entities: dict[tuple[str, str], Any]) -> None:
    """Reject a confirmation if an analyst changed a proposed field in the meantime."""
    for change in changes:
        key = (change["entity_type"], change["entity_id"])
        entity = entities.get(key)
        if entity is None:
            raise ValueError(f"Entity is no longer in this valuation: {key[0]} {key[1]}")
        current = getattr(entity, change["field"])
        expected = change.get("old_value")
        if str(current) != str(expected) and not (current is None and expected is None):
            raise ValueError(
                f"{key[0]}.{change['field']} changed after this proposal; review and propose again"
            )


# Market profile single values a year-by-year schedule overrides; setting one clears its schedule
_PROFILE_SCHEDULES = {
    "rent_growth_rate_pct": "rent_growth_schedule",
    "general_vacancy_pct": "general_vacancy_schedule",
    "credit_loss_pct": "credit_loss_schedule",
    "renewal_probability": "renewal_probability_schedule",
    "downtime_months": "downtime_schedule",
}


def apply_changes(validated: list[dict], entities: dict[tuple[str, str], Any]) -> None:
    for change in validated:
        entity = entities[(change["entity_type"], change["entity_id"])]
        setattr(entity, change["field"], change["new_value"])
        if change["entity_type"] == "market_leasing_profile" and change["field"] in _PROFILE_SCHEDULES:
            setattr(entity, _PROFILE_SCHEDULES[change["field"]], [])
    # Every allow-listed field affects economics. Match manual-edit behavior by invalidating
    # previously calculated outputs so the UI cannot display stale results as completed.
    valuation = next(
        (entity for (kind, _), entity in entities.items() if kind == "valuation"), None
    )
    if valuation is not None and validated:
        valuation.status = "draft"
        valuation.error_message = None
        for column in inspect(type(valuation)).columns:
            if column.name.startswith("result_"):
                setattr(valuation, column.name, None)


SCENARIO_TOOL = {
    "name": "describe_what_if",
    "description": "Translate a what-if question into temporary model changes. The engine computes the result.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["scenario", "changes"],
        "properties": {
            "scenario": {
                "type": "string",
                "description": "One sentence restating the assumption tested, or a clarifying question if unclear.",
            },
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["entity_type", "entity_id", "field", "operation", "value"],
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "enum": [
                                *COPILOT_TOOL["input_schema"]["properties"]["changes"]["items"]["properties"]["entity_type"]["enum"],
                                "storage_model",
                                "storage_unit_type",
                            ],
                        },
                        "entity_id": {"type": "string"},
                        "field": {"type": "string"},
                        "operation": {"type": "string", "enum": ["set", "multiply", "add"]},
                        "value": {},
                    },
                },
            },
        },
    },
}


# A self storage property valued from its unit mix: what-if changes go to its operating model
STORAGE_MODEL_FIELDS = {
    "street_rate_growth_pct", "credit_loss_pct", "churn.monthly_move_out_pct", "ecri.increase_pct",
    "concessions.first_month_discount_pct",
}
STORAGE_UNIT_FIELDS = {"street_rate", "in_place_rate", "stabilized_occupancy"}
STORAGE_UNUSED_ENTITIES = {"suite", "lease", "market_leasing_profile"}


def ask_scenario(message: str, history: list[str], context: dict[str, Any]) -> dict[str, Any]:
    """Ask the model which fields a what-if question changes; it never computes the outcome."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    fields = {k: sorted(v) for k, v in ALLOWED_FIELDS.items()}
    storage_note = ""
    if "storage_model" in context:
        for kind in STORAGE_UNUSED_ENTITIES:
            fields.pop(kind)
        fields["storage_model"] = sorted(STORAGE_MODEL_FIELDS)
        fields["storage_unit_type"] = sorted(STORAGE_UNIT_FIELDS)
        storage_note = (
            "This is a self storage facility valued from its unit mix; suites, leases and market "
            "profiles are not used. storage_model's entity_id is the valuation id; "
            "storage_unit_type's entity_id is the unit type name. Rates are $/unit/month; a change "
            "to every unit type needs one entry per unit type.\n"
        )
    instruction = (
        "You translate what-if questions about an OpenDCF valuation into temporary model changes. "
        "The DCF engine computes the impact; never state values yourself. Use only the supplied "
        "entities, IDs and these fields:\n"
        f"{json.dumps(fields)}\n"
        + storage_note
        +         "Use operation 'multiply' for relative changes (rent up 10% = multiply 1.10), 'add' for "
        "shifts (discount rate up 50 bps = add 0.005) and 'set' for new levels. Percent fields are "
        "decimals (65% = 0.65). A change that applies to the whole property needs one entry per "
        "matching entity (every market_leasing_profile, every lease). A lease's renewal_probability "
        "overrides its market profile, so a property-wide renewal change also changes every lease "
        "that has its own renewal_probability. If the question is ambiguous or no field can express "
        "it, return no changes and ask a short clarifying question in scenario.\n\n"
        + (f"EARLIER QUESTIONS (context only, each ran on the saved model):\n{json.dumps(history)}\n\n" if history else "")
        + f"MODEL STATE:\n{json.dumps(context, default=str)}\n\nQUESTION:\n{message}"
    )
    response = Anthropic(api_key=settings.anthropic_api_key).messages.create(
        model=settings.anthropic_document_model,
        max_tokens=4096,
        tools=[SCENARIO_TOOL],
        tool_choice={"type": "tool", "name": SCENARIO_TOOL["name"]},
        messages=[{"role": "user", "content": instruction}],
    )
    for item in response.content:
        if getattr(item, "type", None) == "tool_use":
            return dict(item.input)
    raise RuntimeError("Anthropic returned no structured what-if response")


def _operate(label: str, current, operation: str, value):
    """New value for a set/multiply/add operation on a current value."""
    if operation not in {"multiply", "add"}:
        return value
    if current is None:
        raise ValueError(f"{label} has no value to adjust; ask for a specific level")
    if isinstance(current, (bool, date, str)):
        raise ValueError(f"{label} can only be set to a new value, not adjusted")
    try:
        current, step = Decimal(str(current)), Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label}: '{value}' is not a number") from None
    return current * step if operation == "multiply" else current + step


def resolve_scenario_changes(
    operations: list[dict], entities: dict[tuple[str, str], Any], storage_model: bool = False
) -> list[dict]:
    """Turn set/multiply/add operations into validated absolute changes from current values.

    On a property valued from a storage unit mix, suite, lease and market changes are rejected:
    the engine would not read them.
    """
    changes = []
    for op in operations:
        kind, entity_id, field = op["entity_type"], op["entity_id"], op["field"]
        if storage_model and kind in STORAGE_UNUSED_ENTITIES:
            raise ValueError(
                f"This self storage property is valued from its unit mix, so a {kind.replace('_', ' ')} "
                "change would have no effect. Ask about street rates, occupancy, churn, ECRI, "
                "concessions or credit loss instead."
            )
        entity = entities.get((kind, entity_id))
        if entity is None:
            raise ValueError(f"Entity is not in this valuation: {kind} {entity_id}")
        if field not in ALLOWED_FIELDS.get(kind, set()):
            raise ValueError(f"What-if may not change {kind}.{field}")
        value = _operate(f"{kind}.{field}", getattr(entity, field), op["operation"], op["value"])
        changes.append({"entity_type": kind, "entity_id": entity_id, "field": field,
                        "new_value": value, "reason": "what-if"})
    return validate_changes(changes, entities)


def resolve_storage_changes(operations: list[dict], model, valuation_id: str):
    """Apply set/multiply/add operations to a copy of a self storage operating model.

    Returns (changes with old and new values, the validated changed model); the stored model is
    not touched.
    """
    data = model.model_dump()
    units = {u["name"]: u for u in data["unit_types"]}
    changes = []
    for op in operations:
        kind, entity_id, field = op["entity_type"], op["entity_id"], op["field"]
        if kind == "storage_model":
            if entity_id != valuation_id:
                raise ValueError(f"Entity is not in this valuation: {kind} {entity_id}")
            if field not in STORAGE_MODEL_FIELDS:
                raise ValueError(f"What-if may not change {kind}.{field}")
            if field.startswith("ecri.") and not data["ecri"]["enabled"]:
                raise ValueError("ECRI is switched off in this unit mix, so changing it would have no effect")
            *path, leaf = field.split(".")
            target = data
            for part in path:
                target = target[part]
        else:
            target = units.get(entity_id)
            if target is None:
                raise ValueError(f"Unit type is not in this model: {entity_id}")
            if field not in STORAGE_UNIT_FIELDS:
                raise ValueError(f"What-if may not change {kind}.{field}")
            leaf = field
        old = target[leaf]
        current = old
        if leaf == "stabilized_occupancy" and current is None and target["count"]:
            current = Decimal(str(target["occupied_units"])) / target["count"]  # the engine's default
        try:
            target[leaf] = Decimal(str(_operate(f"{kind}.{field}", current, op["operation"], op["value"])))
        except InvalidOperation:
            raise ValueError(f"{kind}.{field}: '{op['value']}' is not a number") from None
        changes.append({"entity_type": kind, "entity_id": entity_id, "field": field,
                        "old_value": old, "new_value": target[leaf], "reason": "what-if"})
    try:
        scenario = type(model).model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"The storage model change is not valid: {exc.errors()[0]['msg']}") from None
    return changes, scenario
