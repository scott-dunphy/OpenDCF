# Bulk import from PUBLISHED Enterprise (Excel Add-in / XL4ADW)

Source: *XL4ADW User Guide, PUBLISHED Enterprise 14.0* (Altus Group, 2021-11-15).

## What the importer reads

**XL4ADW input sheets.** Column A holds a header block: HOSTINFO, PORTFOLIO, SCENARIO, TIMESTAMP, USER,
VERSION, VIEW, EXAMPLE, ACTION. Field names sit on the `COL` row, and data starts on the row below it.

- Rows whose ACTION cell (column A) is `SKIP` or `DELETE` are ignored.
- Columns marked `SKIP` on the ACTION row are ignored.

**Plain sheets.** Any sheet with a single header row. The importer picks the row with the most text cells
among the first 10 rows.

## How sheets are recognized

The importer checks the `VIEW` cell first, then the sheet name:

| Sheet | Becomes |
| --- | --- |
| PropertyAssets | Property (name, type, address, market, analysis begin and length, area, purchase price, portfolio) |
| PropertyClassifications | Market, from a classification named Market/MSA/Metro |
| AreaMeasures | Property area, when PropertyAssets has none |
| Leases | Suites, tenants and leases |
| RentSchedules | Rent steps |
| MarketLeases | Market leasing profiles |
| OperatingExpenses | Expenses (`Amount1_APM` is monthly; annual = first 12 months) |
| OtherRevenues / MiscellaneousRents / ParkingRevenues | Other income |
| CapitalExpenses | Capital projects (from `_ATL` dated series or monthly/yearly series) |
| Vacancies / CreditLosses / InflationRates | General vacancy, credit loss, growth rates |
| Loans | First loan only |
| Valuation / Sales / DCF / AcquisitionCostsDCF | Discount rate, exit cap, selling costs |
| MultiFamily / StorageRevenues | Unit mix (suites = unit types, one market profile each) |
| AssumptionProfiles (Ares) | Portfolio assumption profiles |

Sheets without a recognized name are classified from their headers: tenant + lease start means a rent roll;
market rent + downtime means an MLA sheet.

## Columns

Columns are matched through alias lists. Each header is tried with and without its XL4ADW type suffix:
`_APM _APY _AEM _AEY _APCL _APUL _ATL _ID _PD _ExternalID _ExtID`.

Single-cell time series are decoded as the guide documents them:

- `1000;0;2000P` is an amount list, where `P` marks a perpetual tail
- `1|200;4|300P` is a period list
- `2010/01|1000;` is a dated list
- `5Y0M0W0D` is a period length

Yearly series (`_APY`, `_AEY`) with more than one entry are kept year by year:
- rent growth, general vacancy, credit loss, renewal probability, downtime and free rent on market leasing profiles;
- property-level Vacancies, CreditLosses and InflationRates sheets;
- expense and other income growth.

A single value, or a monthly series, uses its first value.

Expense and other income amount series still use only their first 12 months as the Year 1 amount, which then grows at
the growth rate. Later amounts in the series are not imported, because it is not yet confirmed whether the published
software inflates detailed amounts.

The preview lists every column it could not map. To map one by hand, pass
`column_mapping={sheet: {header: field}}` in the preview options.

## Not yet imported

These are flagged in the preview warnings, or held only as a lease comment:

- Option lease terms: the option rent and option term (the upon-expiration choice itself is imported)
- Recovery pools and expense groups (each lease gets one recovery type, mapped from the structure name)
- Loan seniority and loan start dates: every loan after the first is imported as an additional loan funded at close
- CPI index series
- Leasing commissions by lease year: only a single % is read
- Renewal rent "use market or prior" choice: renewals import at market
- Results sheets: KpiResults, PropertyAssetResults, TenantResults

## Defaults to check

- **Discount rate and exit cap:** 8.0% and 6.5% when the workbook has neither. The valuation description
  says so.
- **Unrecognized recovery:** base-year stop for office, NNN for everything else.
- **Multifamily in-place rents:** one lease per unit type, expiring 6 months after analysis start.

## API

- `GET /api/v1/imports/template.xlsx`: a blank workbook in XL4ADW layout.
- `POST /api/v1/imports/preview?filename=...&options={json}`: send the workbook as the raw request body.
  Returns the sheet mapping, a preview of each property, and warnings.
- `POST /api/v1/imports/{id}/commit`: optional `portfolio_id` or `portfolio_name`; `replace_existing`
  replaces properties with the same `external_id`; `create_valuations`.

The full XL4ADW column list is not published. Once a real export is in hand, extend the aliases in
`src/services/published_import/mapper.py`.
