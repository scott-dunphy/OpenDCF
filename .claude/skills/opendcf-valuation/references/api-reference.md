# OpenDCF Valuation Engine - Complete API Reference

Base URL: `http://localhost:8001`

- API prefix: `/api/v1`
- Content type: `application/json` for POST/PUT
- Date format: `YYYY-MM-DD`
- Decimal format: send as strings for precision (for example `"0.05"`, `"1250000"`).

## Table of Contents
1. [System Endpoints](#system-endpoints)
2. [Properties](#properties)
3. [Suites](#suites)
4. [Tenants](#tenants)
5. [Leases](#leases)
6. [Lease Sub-Resources](#lease-sub-resources)
7. [Operating Expenses](#operating-expenses)
8. [Other Income (Custom Revenue)](#other-income-custom-revenue)
9. [Market Leasing Profiles](#market-leasing-profiles)
10. [Capital Projects](#capital-projects)
11. [Recovery Structures](#recovery-structures)
12. [Valuations](#valuations)
13. [Valuation Reports](#valuation-reports)

---

## System Endpoints

### GET /health
Health check for the service.

### GET /
Serves frontend `index.html` when the frontend directory is mounted (non-API UI route).

### GET /api/v1/enums
Returns enum values for UI dropdowns:
- `property_types`
- `area_units`
- `escalation_types`
- `recovery_types`
- `expense_categories`
- `lease_types`
- `valuation_statuses`

---

## Properties

### POST /api/v1/properties
Create property.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| name | string | yes | | max 255 |
| property_type | enum | yes | | `office`, `retail`, `industrial`, `mixed_use`, `multifamily`, `self_storage` |
| total_area | Decimal | yes | | SF for commercial, unit count for residential |
| area_unit | enum | yes | | `sf` or `unit` |
| analysis_start_date | date | yes | | |
| analysis_period_months | int | no | 120 | 12-360 |
| fiscal_year_end_month | int | no | 12 | 1-12 |
| address_line1 | string | no | | |
| address_line2 | string | no | | |
| city | string | no | | |
| state | string | no | | |
| zip_code | string | no | | |
| year_built | int | no | | 1800-2100 |
| comment | string | no | null | Optional source/provenance notes |

### GET /api/v1/properties
List properties (`skip`, `limit` query params supported).

### GET /api/v1/properties/{property_id}
Get property by ID (includes suites).

### PUT /api/v1/properties/{property_id}
Update property (all fields optional, including `comment`).

### DELETE /api/v1/properties/{property_id}
Delete property (cascades to related records).

---

## Suites

### POST /api/v1/properties/{property_id}/suites
Create suite/unit.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| suite_name | string | yes | | max 100 |
| area | Decimal | yes | | SF or unit count |
| space_type | string | yes | | Must align with market profile `space_type` |
| floor | int | no | null | |
| is_available | bool | no | true | |
| market_leasing_profile_id | string | no | null | Explicit profile assignment |
| comment | string | no | null | Optional source/provenance notes |

### GET /api/v1/properties/{property_id}/suites
List suites for a property.

### GET /api/v1/properties/{property_id}/suites/{suite_id}
Get suite by ID.

### PUT /api/v1/properties/{property_id}/suites/{suite_id}
Update suite (all fields optional, including `comment`).

### DELETE /api/v1/properties/{property_id}/suites/{suite_id}
Delete suite (leases cascade).

---

## Tenants

### POST /api/v1/tenants
Create tenant.

| Field | Type | Required | Default |
|---|---|---|---|
| name | string | yes | |
| credit_rating | string | no | null |
| industry | string | no | null |
| contact_name | string | no | null |
| contact_email | string | no | null |
| notes | string | no | null |
| comment | string | no | null |

### GET /api/v1/tenants
List tenants (`skip`, `limit` query params supported).

### GET /api/v1/tenants/{tenant_id}
Get tenant by ID.

### PUT /api/v1/tenants/{tenant_id}
Update tenant (all fields optional, including `comment`).

### DELETE /api/v1/tenants/{tenant_id}
Delete tenant.

---

## Leases

### POST /api/v1/suites/{suite_id}/leases
Create lease.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| lease_start_date | date | yes | | |
| lease_end_date | date | yes | | Must be after start |
| base_rent_per_unit | Decimal | yes | | `$/SF/year` commercial, `$/unit/month` residential |
| tenant_id | string | no | null | |
| lease_type | enum | no | `in_place` | `in_place`, `market`, `month_to_month` |
| rent_payment_frequency | string | no | `annual` | `annual` or `monthly` |
| escalation_type | enum | no | `flat` | `flat`, `pct_annual`, `cpi`, `fixed_step` |
| escalation_pct_annual | Decimal | no | null | required when `pct_annual` |
| cpi_floor | Decimal | no | null | |
| cpi_cap | Decimal | no | null | |
| recovery_type | enum | no | `nnn` | `nnn`, `full_service_gross`, `modified_gross`, `base_year_stop`, `none` |
| pro_rata_share_pct | Decimal | no | auto | 0-1; auto if omitted |
| base_year | int | no | null | |
| base_year_stop_amount | Decimal | no | null | |
| expense_stop_per_sf | Decimal | no | null | |
| pct_rent_breakpoint | Decimal | no | null | |
| pct_rent_rate | Decimal | no | null | |
| projected_annual_sales_per_sf | Decimal | no | null | |
| renewal_probability | Decimal | no | null | Lease-level override |
| renewal_rent_spread_pct | Decimal | no | null | Lease-level override |
| recovery_structure_id | string | no | null | |
| comment | string | no | null | Optional source/provenance notes |

### GET /api/v1/suites/{suite_id}/leases
List leases for a suite.

### GET /api/v1/leases/{lease_id}
Get lease by ID (includes rent steps, free rent periods, and expense recovery overrides).

### PUT /api/v1/leases/{lease_id}
Update lease (all fields optional, including `comment`).

### DELETE /api/v1/leases/{lease_id}
Delete lease.

Validation notes:
- Overlapping lease date ranges in the same suite return `409 Conflict`.
- If changing dates on update, the same overlap check is enforced.

---

## Lease Sub-Resources

### POST /api/v1/leases/{lease_id}/rent-steps
Add a rent step.

| Field | Type | Required |
|---|---|---|
| effective_date | date | yes |
| rent_per_unit | Decimal | yes |
| comment | string | no |

### DELETE /api/v1/leases/{lease_id}/rent-steps/{step_id}
Delete rent step.

### POST /api/v1/leases/{lease_id}/free-rent-periods
Add free-rent period.

| Field | Type | Required | Default |
|---|---|---|---|
| start_date | date | yes | |
| end_date | date | yes | |
| applies_to_base_rent | bool | no | true |
| applies_to_recoveries | bool | no | false |
| comment | string | no | null |

### DELETE /api/v1/leases/{lease_id}/free-rent-periods/{frp_id}
Delete free-rent period.

### POST /api/v1/leases/{lease_id}/expense-recoveries
Add lease expense recovery override.

| Field | Type | Required |
|---|---|---|
| expense_category | string | yes |
| recovery_type | enum | yes |
| base_year_stop_amount | Decimal | no |
| cap_per_sf_annual | Decimal | no |
| floor_per_sf_annual | Decimal | no |
| admin_fee_pct | Decimal | no |
| comment | string | no |

### DELETE /api/v1/leases/{lease_id}/expense-recoveries/{override_id}
Delete expense recovery override.

---

## Operating Expenses

### POST /api/v1/properties/{property_id}/expenses
Create expense line item.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| category | string | yes | | Standard: `real_estate_taxes`, `insurance`, `cam`, `utilities`, `management_fee`, `repairs_maintenance`, `general_admin`, `other`; custom allowed |
| description | string | no | null | |
| comment | string | no | null | Optional source/provenance notes |
| base_year_amount | Decimal | yes | | Annual amount |
| growth_rate_pct | Decimal | no | 0.03 | 0-1 |
| is_recoverable | bool | no | true | |
| is_gross_up_eligible | bool | no | false | |
| gross_up_vacancy_pct | Decimal | no | null | |
| is_pct_of_egi | bool | no | false | |
| pct_of_egi | Decimal | no | null | |

### GET /api/v1/properties/{property_id}/expenses
List expenses.

### GET /api/v1/properties/{property_id}/expenses/{expense_id}
Get expense by ID.

### PUT /api/v1/properties/{property_id}/expenses/{expense_id}
Update expense (all fields optional, including `comment`).

### DELETE /api/v1/properties/{property_id}/expenses/{expense_id}
Delete expense.

---

## Other Income (Custom Revenue)

### POST /api/v1/properties/{property_id}/other-income
Create other-income line item.

| Field | Type | Required | Default |
|---|---|---|---|
| category | string | yes | |
| description | string | no | null |
| comment | string | no | null |
| base_year_amount | Decimal | yes | |
| growth_rate_pct | Decimal | no | 0.03 |

### GET /api/v1/properties/{property_id}/other-income
List other-income line items.

### PUT /api/v1/properties/{property_id}/other-income/{item_id}
Update other-income line item (all fields optional, including `comment`).

### DELETE /api/v1/properties/{property_id}/other-income/{item_id}
Delete other-income line item.

---

## Market Leasing Profiles

### POST /api/v1/properties/{property_id}/market-profiles
Create market leasing profile.

| Field | Type | Required | Default |
|---|---|---|---|
| space_type | string | yes | |
| description | string | no | null |
| comment | string | no | null |
| market_rent_per_unit | Decimal | yes | |
| rent_growth_rate_pct | Decimal | no | 0.03 |
| new_lease_term_months | int | no | 60 |
| new_tenant_ti_per_sf | Decimal | no | 0 |
| new_tenant_lc_pct | Decimal | no | 0.06 |
| new_tenant_free_rent_months | int | no | 0 |
| downtime_months | int | no | 3 |
| renewal_probability | Decimal | no | 0.65 |
| renewal_lease_term_months | int | no | 60 |
| renewal_ti_per_sf | Decimal | no | 0 |
| renewal_lc_pct | Decimal | no | 0.03 |
| renewal_free_rent_months | int | no | 0 |
| renewal_rent_adjustment_pct | Decimal | no | 0 |
| general_vacancy_pct | Decimal | no | 0.05 |
| credit_loss_pct | Decimal | no | 0.01 |

### GET /api/v1/properties/{property_id}/market-profiles
List market profiles.

### GET /api/v1/properties/{property_id}/market-profiles/{profile_id}
Get market profile by ID.

### PUT /api/v1/properties/{property_id}/market-profiles/{profile_id}
Update market profile (all fields optional, including `comment`).

### DELETE /api/v1/properties/{property_id}/market-profiles/{profile_id}
Delete market profile.

---

## Capital Projects

### POST /api/v1/properties/{property_id}/capital-projects
Create capital project.

| Field | Type | Required |
|---|---|---|
| description | string | yes |
| comment | string | no |
| total_amount | Decimal | yes |
| start_date | date | yes |
| duration_months | int | yes |

### GET /api/v1/properties/{property_id}/capital-projects
List capital projects.

### PUT /api/v1/properties/{property_id}/capital-projects/{project_id}
Update capital project (all fields optional, including `comment`).

### DELETE /api/v1/properties/{property_id}/capital-projects/{project_id}
Delete capital project.

---

## Recovery Structures

### POST /api/v1/properties/{property_id}/recovery-structures
Create recovery structure.

| Field | Type | Required | Default |
|---|---|---|---|
| name | string | yes | |
| description | string | no | null |
| comment | string | no | null |
| default_recovery_type | enum | no | `nnn` |
| items | array | no | `[]` |

`items[]` object fields:
- `expense_category` (string, required)
- `recovery_type` (enum, required)
- `base_year_stop_amount` (Decimal, optional)
- `cap_per_sf_annual` (Decimal, optional)
- `floor_per_sf_annual` (Decimal, optional)
- `admin_fee_pct` (Decimal, optional)
- `comment` (string, optional)

### GET /api/v1/properties/{property_id}/recovery-structures
List recovery structures.

### GET /api/v1/properties/{property_id}/recovery-structures/{rs_id}
Get recovery structure by ID.

### PUT /api/v1/properties/{property_id}/recovery-structures/{rs_id}
Update recovery structure header (`name`, `description`, `comment`, `default_recovery_type`).

### DELETE /api/v1/properties/{property_id}/recovery-structures/{rs_id}
Delete recovery structure.

### POST /api/v1/properties/{property_id}/recovery-structures/{rs_id}/items
Add one item to a recovery structure.

### DELETE /api/v1/properties/{property_id}/recovery-structures/{rs_id}/items/{item_id}
Delete one recovery structure item.

---

## Valuations

### POST /api/v1/properties/{property_id}/valuations
Create valuation.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| name | string | yes | | |
| description | string | no | null | |
| comment | string | no | null | Optional source/provenance notes |
| discount_rate | Decimal | yes | | 0 < x < 1 |
| exit_cap_rate | Decimal | yes | | 0 < x < 1 |
| exit_cap_applied_to_year | int | no | -1 | `-1` means Hold+1 (Year N+1) NOI |
| exit_costs_pct | Decimal | no | 0.02 | |
| capital_reserves_per_unit | Decimal | no | 0.25 | |
| use_mid_year_convention | bool | no | false | |
| loan_amount | Decimal | no | null | |
| interest_rate | Decimal | no | null | |
| amortization_months | int | no | null | |
| loan_term_months | int | no | null | |
| io_period_months | int | no | 0 | |

### GET /api/v1/properties/{property_id}/valuations
List valuations for a property.

### GET /api/v1/valuations/{valuation_id}
Get valuation by ID.

### PUT /api/v1/valuations/{valuation_id}
Update valuation (all fields optional, including `comment`).

### DELETE /api/v1/valuations/{valuation_id}
Delete valuation.

### POST /api/v1/valuations/{valuation_id}/run
Run valuation engine and persist results.

---

## Valuation Reports

### GET /api/v1/valuations/{valuation_id}/reports/full
Get full cached valuation output.

### GET /api/v1/valuations/{valuation_id}/reports/key-metrics
Get key metrics summary.

### GET /api/v1/valuations/{valuation_id}/reports/cash-flow-summary
Get annual cash flow summary.

### GET /api/v1/valuations/{valuation_id}/reports/rent-roll
Get valuation rent roll report.

### GET /api/v1/valuations/{valuation_id}/reports/lease-expirations
Get lease expiration schedule.

### GET /api/v1/valuations/{valuation_id}/reports/tenant-detail
Get tenant-level annual cash flow detail.
