"""
Decoders for PUBLISHED Enterprise XL4ADW single-cell time series and period values.

Formats (XL4ADW User Guide, AE 14.0, "Time Series Data"):
  _ATL   "2010/01|1000;2010/02|0;"      year/month | amount pairs
  _APM   "1000;0;0;2000;0P;"            monthly amounts, trailing P = perpetual
  _APY   same as _APM, yearly
  _AEM   "1000;0;0;2000;"               monthly event amounts, zero after the last
  _AEY   same as _AEM, yearly
  _APCL  "1|200;4|300;6|400P;"          period | amount, value holds until next entry
  _APUL  same as _APCL, not consolidated
  _PD    "5Y0M0W0D"                     period length
Percentages are always fractions (1.0 = 100%).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

SERIES_SUFFIXES = ("_ATL", "_APM", "_APY", "_AEM", "_AEY", "_APCL", "_APUL")


def to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    s = str(value).strip().replace(",", "").replace("$", "")
    if not s:
        return None
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d / Decimal(100) if pct else d


def _entries(cell) -> list[str]:
    if cell is None:
        return []
    return [e.strip() for e in str(cell).split(";") if e.strip()]


@dataclass
class Series:
    """A decoded series: amount per period (month or year), optional perpetual tail."""
    values: list[Decimal]
    perpetual: bool = False

    def at(self, index: int) -> Decimal:
        """Value for a 0-based period index."""
        if index < len(self.values):
            return self.values[index]
        if self.perpetual and self.values:
            return self.values[-1]
        return Decimal(0)

    def first(self) -> Decimal | None:
        return self.values[0] if self.values else None

    def sum_first(self, n: int) -> Decimal:
        return sum((self.at(i) for i in range(n)), Decimal(0))


def parse_amount_list(cell, allow_perpetual: bool = True) -> Series:
    """_APM / _APY / _AEM / _AEY. A bare number is a one-entry perpetual series."""
    if cell is None:
        return Series([])
    if isinstance(cell, (int, float, Decimal)):
        return Series([Decimal(str(cell))], perpetual=allow_perpetual)
    values: list[Decimal] = []
    perpetual = False
    for e in _entries(cell):
        if e.upper().endswith("P"):
            perpetual = allow_perpetual
            e = e[:-1]
        d = to_decimal(e)
        values.append(d if d is not None else Decimal(0))
    if len(values) == 1 and not perpetual and ";" not in str(cell):
        perpetual = allow_perpetual
    return Series(values, perpetual)


def parse_period_list(cell, consolidate: bool = True) -> Series:
    """_APCL / _APUL: '1|200;4|300;6|400P;' -> monthly series (1-based periods)."""
    if cell is None:
        return Series([])
    if isinstance(cell, (int, float, Decimal)):
        return Series([Decimal(str(cell))], perpetual=True)
    points: list[tuple[int, Decimal]] = []
    perpetual = False
    for e in _entries(cell):
        if "|" not in e:
            d = to_decimal(e.rstrip("Pp"))
            if d is not None:
                points.append((len(points) + 1, d))
            continue
        period_s, amount_s = e.split("|", 1)
        if amount_s.upper().endswith("P"):
            perpetual = True
            amount_s = amount_s[:-1]
        try:
            period = int(period_s.strip())
        except ValueError:
            continue
        points.append((period, to_decimal(amount_s) or Decimal(0)))
    if not points:
        return Series([])
    points.sort()
    values: list[Decimal] = []
    for i, (period, amount) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else period + 1
        while len(values) < period - 1:
            values.append(values[-1] if values else Decimal(0))
        values.extend([amount] * max(1, end - period))
    return Series(values, perpetual)


def parse_dated_list(cell) -> list[tuple[date, Decimal]]:
    """_ATL: '2010/01|1000;2010/02|0;' -> [(date, amount), ...]."""
    out = []
    for e in _entries(cell):
        if "|" not in e:
            continue
        d_s, a_s = e.split("|", 1)
        m = re.match(r"(\d{4})\s*[/-]\s*(\d{1,2})", d_s.strip())
        if not m:
            continue
        out.append((date(int(m.group(1)), int(m.group(2)), 1), to_decimal(a_s) or Decimal(0)))
    return out


def parse_series(cell, suffix: str | None) -> Series:
    suffix = (suffix or "").upper()
    if suffix in ("_APCL", "_APUL"):
        return parse_period_list(cell, consolidate=suffix == "_APCL")
    if suffix in ("_AEM", "_AEY"):
        return parse_amount_list(cell, allow_perpetual=False)
    if suffix == "_ATL":
        return Series([a for _, a in parse_dated_list(cell)])
    return parse_amount_list(cell)


_PERIOD_RE = re.compile(r"^\s*(?:(\d+)\s*Y)?\s*(?:(\d+)\s*M)?\s*(?:(\d+)\s*W)?\s*(?:(\d+)\s*D)?\s*$", re.I)


def parse_period_months(value) -> int | None:
    """'5Y0M0W0D' -> 60. Plain numbers are taken as months; '5 years' / '60 months' accepted."""
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    s = str(value).strip()
    m = _PERIOD_RE.match(s)
    if m and any(m.groups()):
        y, mo, w, d = (int(g) if g else 0 for g in m.groups())
        return y * 12 + mo + round((w * 7 + d) / 30.4375)
    words = re.match(r"^\s*([\d.]+)\s*(y|yr|yrs|year|years|m|mo|mos|month|months)\s*$", s, re.I)
    if words:
        n = Decimal(words.group(1))
        return int(n * 12) if words.group(2).lower().startswith("y") else int(n)
    d = to_decimal(s)
    return int(d) if d is not None else None
