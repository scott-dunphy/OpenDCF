"""Build src/data/cbsas.csv and src/data/zip_cbsa.csv from Census reference files.

Usage: python -I build_cbsa_data.py <list1_2023.xlsx> <tab20_zcta520_county20_natl.txt> <out_dir>
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

delineation, relationship, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])

county_cbsa: dict[str, str] = {}
cbsas: dict[str, tuple[str, str]] = {}
wb = openpyxl.load_workbook(delineation, read_only=True)
for r in wb.active.iter_rows(min_row=4, values_only=True):
    if not r[0] or not r[9] or not str(r[0]).isdigit():
        continue
    code, title, kind = str(r[0]), r[3], "metro" if r[4].startswith("Metro") else "micro"
    cbsas[code] = (title, kind)
    county_cbsa[f"{r[9]}{r[10]}"] = code

# The ZCTA file uses Connecticut's pre-2022 counties; the 2023 delineation uses planning
# regions. Map each old county to the CBSA holding most of it.
for fips, code in {"09001": "14860", "09003": "25540", "09005": "45860", "09007": "25540",
                   "09009": "35300", "09011": "35980", "09013": "25540", "09015": "39480"}.items():
    county_cbsa.setdefault(fips, code)

land = defaultdict(lambda: defaultdict(int))
total = defaultdict(int)
with open(relationship, encoding="utf-8-sig") as f:
    for row in csv.DictReader(f, delimiter="|"):
        z = row["GEOID_ZCTA5_20"]
        if not z:
            continue
        part = int(row["AREALAND_PART"] or 0)
        total[z] += part
        cbsa = county_cbsa.get(row["GEOID_COUNTY_20"])
        if cbsa:
            land[z][cbsa] += part

out.mkdir(parents=True, exist_ok=True)
with open(out / "cbsas.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["cbsa_code", "title", "kind"])
    for code in sorted(cbsas):
        w.writerow([code, *cbsas[code]])
rows = 0
with open(out / "zip_cbsa.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["zip", "cbsa_code", "land_share"])
    for z in sorted(land):
        for code, part in sorted(land[z].items(), key=lambda kv: -kv[1]):
            share = part / total[z] if total[z] else 1
            if share >= 0.01:
                w.writerow([z, code, f"{share:.3f}"])
                rows += 1
print(len(cbsas), "CBSAs;", len(land), "ZIPs in a CBSA of", len(total), "; rows", rows)
