"""Excel template for the assumptions library (docs/market-assumptions-plan.md).

One row per profile: scope columns, provenance, then <field>_low / <field>_base / <field>_high
for every assumption field. The import reads the "Assumption Profiles" sheet; "Read Me", "Fields"
and "CBSAs" are reference sheets it skips.
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from src.engine.assumption_overrides import RESERVES_BY_BASIS, default_directions
from src.schemas.common import PropertyType
from src.schemas.portfolio import AssumptionProfileRead, AssumptionValues
from src.services import cbsa

SHEET = "Assumption Profiles"
REFERENCE_SHEETS = ("Read Me", "Fields", "CBSAs")
SCOPE = [
    ("name", "Unique name for the profile"),
    ("portfolio", "Blank = house-wide; or a portfolio name"),
    ("property_type", "Blank = any type"),
    ("cbsa_code", "5-digit census CBSA code (see CBSAs sheet); blank = any market"),
    ("market", "Optional free-text market instead of a CBSA; a name that identifies one CBSA is converted to it"),
    ("state", "Two-letter state, for properties outside any CBSA"),
    ("quality_score", "Blank = all qualities (values positioned by each property's 1-5 score); 1-5 = only that score"),
    ("as_of", "Date the numbers describe"),
    ("source", "Where they came from"),
    ("comment", ""),
]
UNITS = {
    "capital_reserves_per_unit": "$ per SF or per unit / yr, in the property's own basis",
    "capital_reserves_per_sf": "$ per SF / yr (properties measured in SF)",
    "capital_reserves_per_unit_count": "$ per unit / yr (properties measured in units)",
    "management_fee_pct": "decimal share of EGI (0.03 = 3%)",
    "new_ti_per_sf": "$ per SF", "renewal_ti_per_sf": "$ per SF",
}
MONTH_FIELDS = {"downtime_months", "new_lease_term_months", "renewal_lease_term_months",
                "new_free_rent_months", "renewal_free_rent_months"}


def _unit(field: str) -> str:
    if field in UNITS:
        return UNITS[field]
    if field in MONTH_FIELDS:
        return "months"
    return "decimal (0.055 = 5.5%)"


def _better(field: str, directions: dict[str, str]) -> str:
    d = directions.get("capital_reserves_per_unit" if field in RESERVES_BY_BASIS else field)
    return d if d in ("higher", "lower") else "n/a (base used)"


def _examples() -> list[dict]:
    return [
        {"name": "Industrial - Dallas", "property_type": "industrial", "cbsa_code": "19100",
         "as_of": "2026-09-30", "source": "Example only: replace",
         "exit_cap_rate": ("0.0525", "0.0575", "0.065"), "discount_rate": ("0.07", "0.075", "0.0825"),
         "market_rent_growth": ("0.02", "0.03", "0.04"), "general_vacancy_pct": ("0.03", "0.05", "0.08")},
        {"name": "Office - national", "property_type": "office", "as_of": "2026-09-30", "source": "Example only: replace",
         "exit_cap_rate": ("0.07", "0.08", "0.095"), "renewal_probability": ("0.55", "0.65", "0.75")},
    ]


def _row_from_profile(p: AssumptionProfileRead) -> dict:
    row = {"name": p.name, "property_type": p.property_type.value if p.property_type else None,
           "cbsa_code": p.cbsa_code, "market": p.market, "state": p.state, "quality_score": p.quality_score,
           "as_of": p.as_of, "source": p.source, "comment": p.comment}
    for key, base in p.values.model_dump(exclude_none=True).items():
        r = p.ranges.get(key)
        row[key] = (r.low if r else None, base, r.high if r else None)
    return row


def build_template(profiles: list[AssumptionProfileRead] | None = None, directions: dict[str, str] | None = None) -> bytes:
    directions = directions if directions is not None else default_directions()
    fields = list(AssumptionValues.model_fields)
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    headers = [k for k, _ in SCOPE] + [f"{f}_{part}" for f in fields for part in ("low", "base", "high")]
    ws.append(headers)
    bold, fill = Font(bold=True), PatternFill("solid", fgColor="E8EEF4")
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i)
        c.font, c.alignment = bold, Alignment(wrap_text=True, vertical="top")
        if h.endswith("_base"):
            c.fill = fill
        ws.column_dimensions[get_column_letter(i)].width = 22 if i <= len(SCOPE) else 14
    ws.freeze_panes = ws.cell(row=2, column=2)

    rows = [_row_from_profile(p) for p in profiles] if profiles else _examples()
    for r in rows:
        line = [r.get(k) for k, _ in SCOPE]
        for f in fields:
            low, base, high = r.get(f) or (None, None, None)
            line += [low, base, high]
        ws.append([float(v) if hasattr(v, "is_finite") else v for v in line])

    types = DataValidation(type="list", formula1='"' + ",".join(t.value for t in PropertyType) + '"', allow_blank=True)
    quality = DataValidation(type="whole", operator="between", formula1="1", formula2="5", allow_blank=True)
    ws.add_data_validation(types)
    ws.add_data_validation(quality)
    types.add(f"C2:C1000")
    quality.add(f"G2:G1000")

    readme = wb.create_sheet("Read Me")
    for line in [
        ["Assumptions library template"],
        [],
        ["One row per profile on the 'Assumption Profiles' sheet. Import the file on the Import page."],
        ["For each field, base is the typical value; low and high are roughly the 10th and 90th percentile"],
        ["across properties of the type in the market. Leave low and high blank for a single value."],
        ["Each property's 1-5 quality score (5 = best, 3 = base) picks its value inside the range:"],
        ["5 = the favourable end (e.g. low cap rate, high rent growth), 1 = the unfavourable end."],
        ["Which end is favourable for each field is set on the library page (see the Fields sheet)."],
        ["House defaults: a row with no type or market applies everywhere. Management fee and the two"],
        ["reserves columns (per SF, per unit) are copied into new properties and valuations."],
        ["Rates are decimals: 0.055 = 5.5%."],
        ["Most specific profile wins, field by field: CBSA + type + quality > CBSA + type > state + type > type > default."],
        ["Re-importing a row with the same scope (portfolio, type, CBSA, market, state, quality) updates that profile."],
        [],
        ["Example rows are placeholders: replace or delete them."],
        [f"CBSA codes: Census delineation, {cbsa.DELINEATION_VINTAGE}."],
        [],
        ["Column", "Meaning"],
        *[[k, d] for k, d in SCOPE],
    ]:
        readme.append(line)
    readme.column_dimensions["A"].width = 22
    readme.column_dimensions["B"].width = 90
    readme["A1"].font = Font(bold=True, size=14)

    ref = wb.create_sheet("Fields")
    ref.append(["field", "units", "better quality means", "columns"])
    for f in fields:
        ref.append([f, _unit(f), _better(f, directions), f"{f}_low / {f}_base / {f}_high"])
    for col, w in zip("ABCD", (30, 26, 22, 60)):
        ref.column_dimensions[col].width = w

    markets = wb.create_sheet("CBSAs")
    markets.append(["cbsa_code", "title", "kind"])
    for c in sorted(cbsa.all_cbsas().values(), key=lambda c: c.title):
        markets.append([c.code, c.title, c.kind])
    markets.column_dimensions["B"].width = 50

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
