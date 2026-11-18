# Published Appraisal Benchmark Audit

## Scope and acceptance rule

This benchmark uses public appraisal reports that disclose the rent roll, market-leasing assumptions,
operating expenses, annual cash flow, reversion assumptions, and present-value schedule. The computational
target is the report's selected DCF matrix cell, not the appraiser's separately reconciled market-value
opinion. Those numbers can legitimately differ.

"Exact" means the engine's unrounded present value is within one cent of the published DCF present value,
without an undisclosed valuation plug. A case can remain useful for line-item regression testing while
failing this stricter value criterion.

## Primary sources

- [Montague and Royal Ridge filing](https://www.sec.gov/Archives/edgar/data/1031316/000117152004000315/ex99-11.txt)
- [Upland Town & Country Center](https://www.sec.gov/Archives/edgar/data/105729/000119312511099914/dex99c10.htm)
- [301 Colorado](https://www.sec.gov/Archives/edgar/data/105729/000119312511099914/dex99c11.htm)
- [Magnolia City Place](https://www.sec.gov/Archives/edgar/data/891919/000119312515349412/d22203dex16c7.htm)
- [Cole Credit Property Trust portfolio report](https://www.sec.gov/Archives/edgar/data/1289272/000114420414022223/v374525_ex99ciii.htm)
- Kent GSA Office: SEC accessions 0001096906-11-002287 and 0001096906-13-000169, exhibit (e).

Methodology was checked against the [RICS DCF practice information](https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/discounted-cash-flow-valuation),
including explicit forecast periods, contract and market cash flows, terminal value, and discount-rate
consistency. The benchmark preserves the reports' end-of-period timing, forward-year NOI reversion, and
property-specific leasing assumptions rather than imposing one generic convention.

## Current ten-assignment gate

These ten fixtures pass the exact-value assertion. Source reports display some inputs at fewer decimal
places than their cash-flow schedules imply. In those cases, the fixture carries additional inferred
precision only inside the displayed input's rounding interval and documents the inference next to the
input. No residual value adjustment is used.

| Assignment | Property type | Published DCF value | Exact difference |
|---|---|---:|---:|
| Montague | R&D / industrial | $19,363,627 | < $0.01 |
| Royal Ridge | Office | $23,320,272 | < $0.01 |
| Walgreens — Lawrence | Single-tenant net lease retail | $3,349,230 | < $0.01 |
| Rite Aid — Memphis | Single-tenant net lease retail | $2,387,819 | < $0.01 |
| Rite Aid — Warren | Single-tenant net lease retail | $3,668,397 | < $0.01 |
| Walgreens — Cahokia | Single-tenant net lease retail | $2,000,093 | < $0.01 |
| Rite Aid — Bangor | Single-tenant net lease retail | $3,962,564 | < $0.01 |
| Rite Aid — Murfreesboro | Single-tenant net lease retail | $2,643,422 | < $0.01 |
| Rite Aid — Philadelphia | Single-tenant net lease retail | $3,558,571 | < $0.01 |
| Best Buy — Tupelo | Single-tenant net lease retail | $2,761,539 | < $0.01 |

## Model behavior exercised

The cases collectively exercise calendar-year recoveries within non-calendar fiscal projections, pooled
base-year stops, fixed-dollar and percentage rent steps, blended renewal/new-tenant leasing, downtime,
abatements, tenant improvements, commissions, expense caps and administrative fees, occupancy gross-up,
vacancy reduction by modeled downtime, percentage-of-revenue management fees, forward-year reversion NOI,
selling costs, and full-occupancy terminal adjustments.

## Additional printed-input validation cases

These cases use the reports' printed discount and exit-cap rates without inferred rate precision.
Because the public schedules round annual cash flows to whole dollars, acceptance is an absolute
$50 valuation tolerance rather than a sub-cent claim.

| Assignment | Published DCF value | OpenDCF difference |
|---|---:|---:|
| Walgreens — Houston | $2,791,453 | -$4.71 |
| Walgreens — Cleveland | $2,546,692 | +$10.48 |
| Tractor Supply — Woodstock | $3,002,296 | +$4.56 |
| Gander Mountain — Houston | $14,508,001 | -$4.46 |
| Conn’s — Austin | $3,982,654 | +$32.27 |

## Reproducibility

Run the appraisal-specific integration suite:

```shell
.venv/bin/python -m pytest -q tests/integration/test_published_appraisal_*.py
```

Run the complete regression suite:

```shell
.venv/bin/python -m pytest -q
```

