"""Census core based statistical areas (CBSAs) and an offline ZIP -> CBSA lookup.

Data in src/data (built by scripts/build_cbsa_data.py from Census reference files):
- cbsas.csv: July 2023 CBSA delineation (code, title, metro/micro)
- zip_cbsa.csv: 2020 ZCTA-to-county relationship joined to that delineation; one row per ZIP and
  CBSA with the share of the ZIP's land area in it. ZIPs outside every CBSA are absent.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DELINEATION_VINTAGE = "July 2023"

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}


@dataclass(frozen=True)
class Cbsa:
    code: str
    title: str
    kind: str  # "metro" | "micro"

    @property
    def states(self) -> list[str]:
        return self.title.rsplit(", ", 1)[-1].split("-")

    @property
    def cities(self) -> list[str]:
        return self.title.rsplit(", ", 1)[0].split("-")


@lru_cache(maxsize=1)
def all_cbsas() -> dict[str, Cbsa]:
    with open(DATA / "cbsas.csv", newline="") as f:
        return {r["cbsa_code"]: Cbsa(r["cbsa_code"], r["title"], r["kind"]) for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def _zip_rows() -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    with open(DATA / "zip_cbsa.csv", newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["zip"], []).append((r["cbsa_code"], float(r["land_share"])))
    return out


def get(code: str | None) -> Cbsa | None:
    return all_cbsas().get(code) if code else None


def title(code: str | None) -> str | None:
    c = get(code)
    return c.title if c else None


def zip_candidates(zip_code: str | None) -> list[tuple[Cbsa, float]]:
    """CBSAs covering a ZIP, largest land share first; empty when rural or unknown."""
    m = re.match(r"\s*(\d{5})", zip_code or "")
    if not m:
        return []
    return [(all_cbsas()[c], share) for c, share in _zip_rows().get(m.group(1), []) if c in all_cbsas()]


def from_zip(zip_code: str | None) -> str | None:
    found = zip_candidates(zip_code)
    return found[0][0].code if found else None


def for_property(zip_code: str | None, market: str | None, city: str | None, state: str | None) -> str | None:
    """CBSA from the ZIP, else an unambiguous market name, else the city when the state is known."""
    return (from_zip(zip_code) or match_market(market, state)
            or (match_market(city, state) if state_code(state) else None))


def state_code(state: str | None) -> str | None:
    """Two-letter state from 'TX', 'tx' or 'Texas'."""
    if not state or not state.strip():
        return None
    s = state.strip()
    if len(s) == 2 and s.upper() in STATES.values():
        return s.upper()
    return STATES.get(s.lower())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def search(query: str, limit: int = 20) -> list[Cbsa]:
    """CBSAs whose title or code matches every word of the query; metros first."""
    words = [_norm(w) for w in query.split() if _norm(w)]
    hits = [c for c in all_cbsas().values() if all(w in _norm(c.title) or w == c.code for w in words)]
    hits.sort(key=lambda c: (c.kind != "metro", c.title))
    return hits[:limit]


def match_market(text: str | None, state: str | None = None) -> str | None:
    """Best-effort CBSA for a free-text market name ('Dallas-Fort Worth', 'Kansas City').
    Returns a code only when exactly one metro matches (by title, else by first principal city)."""
    if not text or not text.strip():
        return None
    if re.fullmatch(r"\d{5}", text.strip()) and get(text.strip()):
        return text.strip()
    t = _norm(text.split(",")[0])
    st = state_code(state)
    pool = [c for c in all_cbsas().values() if st is None or st in c.states]
    tests = (
        lambda c: _norm(c.title.rsplit(", ", 1)[0]) == t,
        lambda c: _norm(c.title).startswith(t),
        lambda c: _norm(c.cities[0]) == t,
    )
    for kind in ("metro", "micro"):  # a metro match beats a same-named micropolitan area
        for test in tests:
            found = [c for c in pool if c.kind == kind and test(c)]
            if len(found) == 1:
                return found[0].code
            if found:
                return None
    return None
