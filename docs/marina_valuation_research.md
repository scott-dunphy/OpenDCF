# Marina Valuation Research Notes (As of March 8, 2026)

This note records external references used to structure `src/engine/marina_valuation.py`.

## 1) Revenue Segmentation and Seasonality

- Sun Communities / ELS marina disclosures describe key marina revenue streams and operating patterns:
  - Annual, seasonal, and transient dockage
  - Marina service, fuel sales, and ancillary marina offerings
  - Weather variability affecting transient demand

References:
- https://www.suninc.com/media/c5jpiiux/els-q3-2021-press-release-final.pdf
- https://www.sec.gov/Archives/edgar/data/912593/000091259323000068/sui-20230630x10q.htm

Model mapping:
- Annual/seasonal/transient contract revenue lines
- Fuel dock modeled on gross margin (not gross sales)
- Monthly seasonality and monthly weather shock vectors

## 2) Slip and Service Structures

Observed marina pricing conventions (wet slips, moorings, utility differences by electrical service) inform inventory granularity.

References:
- https://chestertownmarina.com/rates/
- https://harborwalkmarina.com/rates/

Model mapping:
- Slip class inventory by type/length class/utility service tier
- Utility charges as separate revenue per contract month/day

## 3) Legal/Tenure and Permitting Risk

U.S. and state frameworks confirm that marina value can depend on permits, submerged-land tenure, and concession rights.

References:
- https://www.law.cornell.edu/uscode/text/33/403
- https://www.floridadep.gov/water/submerged-lands-environmental-resources-coordination/content/sovereignty-submerged-lands

Model mapping:
- Fee simple vs leasehold layer
- Annual submerged-land / permit / concession cost lines
- Lease-expiry and reversion haircut to terminal value

## 4) Environmental Compliance and Resilience

Pump-out and coastal resilience guidance supports explicit compliance and storm contingency treatment.

References:
- https://www.epa.gov/cva/clean-vessel-act-cva-program
- https://www.fisheries.noaa.gov/national/habitat-conservation/marina-and-boatyard-guide-hurricane-preparedness-and-response

Model mapping:
- Environmental cost lines
- Storm contingency cyclical costs
- Pump-out and other lifecycle capex scheduling

## 5) Financing/Covenants

Public REIT disclosures show debt covenant sensitivity and financing constraints as material to valuation outcomes.

Reference:
- https://www.sec.gov/Archives/edgar/data/912593/000091259323000068/sui-20230630x10q.htm

Model mapping:
- Debt schedule and levered cash flows
- DSCR, LTV, and debt-yield covenant views
- Debt sizing function constrained by covenant thresholds
