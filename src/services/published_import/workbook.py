"""
Read worksheets from an PUBLISHED Enterprise XL4ADW (Excel Add-in) workbook, or from
a plain workbook with one header row.

XL4ADW input sheets carry a header block in column A (HOSTINFO, PORTFOLIO,
SCENARIO, TIMESTAMP, USER, VERSION, VIEW, EXAMPLE, ACTION) followed by a COL
row that holds the field names; data starts on the next row. Row-level ACTION
values SKIP and DELETE are not imported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO

from openpyxl import load_workbook

from src.services.published_import.timeseries import SERIES_SUFFIXES

_HEADER_KEYS = {"HOSTINFO", "PORTFOLIO", "SCENARIO", "TIMESTAMP", "USER", "VERSION", "VIEW", "EXAMPLE", "ACTION"}
_COL_KEYS = {"COL", "COL HEADER", "COLHEADER"}
_SKIP_ACTIONS = {"SKIP", "DELETE"}
# Type suffixes defined by XL4ADW; stripped before alias matching
_TYPE_SUFFIXES = SERIES_SUFFIXES + ("_EXTERNALID", "_EXTID", "_ID", "_YND", "_YN", "_SVD", "_SV", "_PD", "_LST")


def normalize(name: str) -> str:
    """Lowercase, strip non-alphanumerics: 'Lease Begin ($)' -> 'leasebegin'."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def split_suffix(header: str) -> tuple[str, str | None]:
    """'MR_Amount_APM' -> ('mramount', '_APM'); 'LeaseProfile_ExternalID' -> ('leaseprofile', '_EXTERNALID')."""
    upper = header.upper()
    for suf in sorted(_TYPE_SUFFIXES, key=len, reverse=True):
        if upper.endswith(suf) and len(upper) > len(suf):
            return normalize(header[: -len(suf)]), suf
    return normalize(header), None


@dataclass
class Column:
    header: str
    index: int
    base: str              # normalized name without type suffix
    suffix: str | None     # e.g. "_APM"


@dataclass
class Sheet:
    name: str
    view: str | None
    columns: list[Column]
    rows: list[dict[str, object]]   # header -> raw cell value
    is_xl4adw: bool
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return normalize(self.view or self.name)


def _cell_text(v) -> str:
    return str(v).strip() if v is not None else ""


def _read_sheet(ws) -> Sheet | None:
    grid = [list(r) for r in ws.iter_rows(values_only=True)]
    if not grid:
        return None

    meta: dict[str, str] = {}
    col_row = None
    action_row = None
    for i, row in enumerate(grid[:20]):
        first = _cell_text(row[0] if row else None).upper()
        if first in _COL_KEYS:
            col_row = i
            break
        if first in _HEADER_KEYS:
            meta[first] = _cell_text(row[1] if len(row) > 1 else None)
            if first == "ACTION":
                action_row = i

    if col_row is not None:
        header_cells = grid[col_row]
        start_col = 1
        data_rows = grid[col_row + 1:]
        is_xl4adw = True
    else:
        # Plain sheet: header = first row among the first 10 with the most text cells
        best_i, best_n = None, 0
        for i, row in enumerate(grid[:10]):
            n = sum(1 for c in row if isinstance(c, str) and c.strip())
            if n > best_n:
                best_i, best_n = i, n
        if best_i is None or best_n < 2:
            return None
        header_cells = grid[best_i]
        start_col = 0
        data_rows = grid[best_i + 1:]
        is_xl4adw = False

    columns: list[Column] = []
    for idx in range(start_col, len(header_cells)):
        h = _cell_text(header_cells[idx])
        if not h:
            continue
        base, suffix = split_suffix(h)
        columns.append(Column(header=h, index=idx, base=base, suffix=suffix))
    if not columns:
        return None

    column_skip = set()
    if action_row is not None:
        for c in columns:
            cell = grid[action_row][c.index] if c.index < len(grid[action_row]) else None
            if _cell_text(cell).upper() == "SKIP":
                column_skip.add(c.header)
    columns = [c for c in columns if c.header not in column_skip]

    rows: list[dict[str, object]] = []
    for raw in data_rows:
        if raw is None or all(v is None or _cell_text(v) == "" for v in raw):
            continue
        if is_xl4adw and _cell_text(raw[0] if raw else None).upper() in _SKIP_ACTIONS:
            continue
        rows.append({c.header: (raw[c.index] if c.index < len(raw) else None) for c in columns})

    return Sheet(
        name=ws.title,
        view=meta.get("VIEW") or None,
        columns=columns,
        rows=rows,
        is_xl4adw=is_xl4adw,
        meta=meta,
    )


def read_workbook(data: bytes) -> list[Sheet]:
    wb = load_workbook(BytesIO(data), data_only=True, read_only=True)
    sheets = []
    for ws in wb.worksheets:
        s = _read_sheet(ws)
        if s is not None:
            sheets.append(s)
    wb.close()
    return sheets
