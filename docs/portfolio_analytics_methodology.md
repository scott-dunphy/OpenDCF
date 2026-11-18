# Portfolio analytics methodology

OpenDCF portfolio runs preserve both 100% property results and effective-ownership-share results.
Ownership is an attribute of the portfolio investment, not the underlying property, and may include
effective dates, acquisition cost, commitment, and currency.

## Forecasts and returns

- Monthly NOI, capital costs, debt service, and cash flow are aligned by calendar month and aggregated
  at effective ownership share.
- Portfolio XIRR is calculated from the combined dated cash-flow stream, including initial ownership-share
  value and terminal property values. A weighted average of property IRRs remains available only as a
  diagnostic and is not presented as the portfolio return.
- Forecast time-weighted return is chain-linked quarterly using ownership-share market values, NOI, and
  capital improvements under the NCREIF property-return convention.
- Required liquidity is the amount needed to fund the lowest cumulative forecast cash position.

## Scenario and risk analytics

Scenarios can carry probabilities. OpenDCF reports normalized probability-weighted ownership-share value
and Year 1 NOI for the scenarios with probabilities. Property-level change in ownership-share value is
stored as scenario attribution.

Concentration includes largest-property weight and value-weighted HHI. Reference alerts are raised when a
single property exceeds 25%, a property type exceeds 60%, or a market exceeds 65% of ownership-share value.
These are screening references, not universal investment-policy limits.

## Disposition allocation sensitivity

A disposition plan removes each sold property's operating cash flows after its selected sale date and replaces
its modeled terminal value with ownership-share net sale proceeds. A supplied price is treated as the 100% gross
property price; otherwise the nearest forecast quarter-end market value is used. The analysis recalculates portfolio
XIRR, liquidity requirement, HHI, largest-asset exposure, and remaining allocation by property type and market.

The interactive map uses stored latitude and longitude. Marker size represents effective ownership and proposed
sales are highlighted. Unmapped properties remain listed and are never silently excluded from analytics.

## Current boundaries

Currency is recorded but values are not yet translated between currencies. JV promotes, fund fees,
investor-level waterfalls, benchmark-relative Brinson attribution, transaction scheduling, and portfolio
optimization require separate fund/investor cash-flow layers and are not inferred from property DCFs.
