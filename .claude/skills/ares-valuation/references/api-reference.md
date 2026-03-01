# OpenDCF Valuation Engine — Complete API Reference

Base URL: `http://localhost:8001/api/v1`

All POST/PUT requests require `Content-Type: application/json`. All decimal values sent as strings. Dates as `YYYY-MM-DD`.

## Table of Contents
1. [Properties](#properties)
2. [Suites](#suites)
3. [Tenants](#tenants)
4. [Leases](#leases)
5. [Rent Steps](#rent-steps)
6. [Free Rent Periods](#free-rent-periods)
7. [Lease Expense Recovery Overrides](#lease-expense-recovery-overrides)
8. [Operating Expenses](#operating-expenses)
9. [Market Leasing Profiles](#market-leasing-profiles)
10. [Capital Projects](#capital-projects)
11. [Recovery Structures](#recovery-structures)
12. [Valuations](#valuations)
13. [Reports](#reports)

---

## Properties

### POST /properties
Create a property.

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| name | string | yes | | max 255 chars |
| property_type | enum | yes | | office, retail, industrial, mixed_use, multifamily, self_storage |
| total_area | Decimal | yes | | SF for commercial, unit count for residential |
| area_unit | enum | yes | | sf or unit |
| analysis_start_date | date | yes | | YYYY-MM-DD |
| analysis_period_months | int | no | 120 | 12-360 |
| fiscal_year_end_month | int | no | 12 | 1-12 |
| address_line1 | string | no | | |
| city | string | no | | |
| state | string | no | | |
| zip_code | string | no | | |
| year_built | int | no | | 1800-2100 |

### GET /properties — List all
### GET /properties/{id} — Get one (includes suites)
### PUT /properties/{id} — Update (all fields optional)
### DELETE /properties/{id} — Delete (cascades)

---

## Suites

### POST /properties/{property_id}/suites

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| suite_name | string | yes | | max 100 |
| area | Decimal | yes | | SF or unit count |
| space_type | string | yes | | Must match market profile space_type |
| floor | int | no | | |
| market_leasing_profile_id | string | no | | Explicit MLA assignment |

### GET /properties/{pid}/suites — List
### PUT /properties/{pid}/suites/{sid} — Update
### DELETE /properties/{pid}/suites/{sid} — Delete (cascades leases)

---

## Tenants

### POST /tenants

| Field | Type | Required | Default |
|-------|------|----------|---------|
| name | string | yes | |
| credit_rating | string | no | |
| industry | string | no | |
| contact_name | string | no | |
| contact_email | string | no | |
| notes | string | no | |

### GET /tenants — List all
### PUT /tenants/{id} — Update
### DELETE /tenants/{id} — Delete

---

## Leases

### POST /suites/{suite_id}/leases

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| lease_start_date | date | yes | | |
| lease_end_date | date | yes | | Must be after start |
| base_rent_per_unit | Decimal | yes | | $/SF/yr (commercial) or $/unit/mo (residential) |
| tenant_id | string | no | | |
| lease_type | enum | no | in_place | in_place, market, month_to_month |
| rent_payment_frequency | string | no | annual | annual or monthly |
| escalation_type | enum | no | flat | flat, pct_annual, cpi, fixed_step |
| escalation_pct_annual | Decimal | no | | Required if pct_annual. Decimal: 0.03 = 3% |
| cpi_floor | Decimal | no | | For CPI leases |
| cpi_cap | Decimal | no | | For CPI leases |
| recovery_type | enum | no | nnn | nnn, full_service_gross, modified_gross, base_year_stop, none |
| pro_rata_share_pct | Decimal | no | auto | 0-1, auto = suite_area/total_area |
| base_year | int | no | | For base_year_stop |
| base_year_stop_amount | Decimal | no | | For base_year_stop |
| expense_stop_per_sf | Decimal | no | | For modified_gross |
| pct_rent_breakpoint | Decimal | no | | Annual sales threshold |
| pct_rent_rate | Decimal | no | | Overage rate (0.06 = 6%) |
| projected_annual_sales_per_sf | Decimal | no | | For pct rent calc |
| renewal_probability | Decimal | no | | Override market profile |
| renewal_rent_spread_pct | Decimal | no | | vs market at renewal |
| recovery_structure_id | string | no | | Assign recovery template |

### GET /suites/{sid}/leases — List for suite
### GET /leases/{id} — Get (includes rent_steps, free_rent_periods, expense_recovery_overrides)
### PUT /leases/{id} — Update
### DELETE /leases/{id} — Delete

---

## Rent Steps

For `fixed_step` escalation leases. Each step is an absolute rent amount at a date.

### POST /leases/{lease_id}/rent-steps

| Field | Type | Required |
|-------|------|----------|
| effective_date | date | yes |
| rent_per_unit | Decimal | yes |

### DELETE /leases/{lid}/rent-steps/{step_id}

---

## Free Rent Periods

### POST /leases/{lease_id}/free-rent-periods

| Field | Type | Required | Default |
|-------|------|----------|---------|
| start_date | date | yes | |
| end_date | date | yes | |
| applies_to_base_rent | bool | no | true |
| applies_to_recoveries | bool | no | false |

### DELETE /leases/{lid}/free-rent-periods/{frp_id}

---

## Lease Expense Recovery Overrides

Per-category recovery rules that override the lease-level recovery_type.

### POST /leases/{lease_id}/expense-recoveries

| Field | Type | Required |
|-------|------|----------|
| expense_category | enum | yes |
| recovery_type | enum | yes |
| base_year_stop_amount | Decimal | no |
| cap_per_sf_annual | Decimal | no |
| floor_per_sf_annual | Decimal | no |
| admin_fee_pct | Decimal | no |

### DELETE /leases/{lid}/expense-recoveries/{override_id}

---

## Operating Expenses

### POST /properties/{property_id}/expenses

| Field | Type | Required | Default |
|-------|------|----------|---------|
| category | enum | yes | | real_estate_taxes, insurance, cam, utilities, management_fee, repairs_maintenance, general_admin, other |
| base_year_amount | Decimal | yes | | Annual amount |
| growth_rate_pct | Decimal | no | 0.03 | 0-1 |
| description | string | no | | |
| is_recoverable | bool | no | true | |
| is_gross_up_eligible | bool | no | false | |
| gross_up_vacancy_pct | Decimal | no | | For gross-up |
| is_pct_of_egi | bool | no | false | Use for management fee |
| pct_of_egi | Decimal | no | | e.g. 0.04 = 4% |

### GET /properties/{pid}/expenses — List
### PUT /properties/{pid}/expenses/{eid} — Update
### DELETE /properties/{pid}/expenses/{eid} — Delete

---

## Market Leasing Profiles

One per property per space_type. Drives renewal and new-tenant assumptions.

### POST /properties/{property_id}/market-profiles

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| space_type | string | yes | | Must match suite space_type |
| market_rent_per_unit | Decimal | yes | | $/SF/yr or $/unit/mo |
| rent_growth_rate_pct | Decimal | no | 0.03 | |
| description | string | no | | |
| new_lease_term_months | int | no | 60 | |
| new_tenant_ti_per_sf | Decimal | no | 0 | $/SF (or $/unit turnover cost for MF) |
| new_tenant_lc_pct | Decimal | no | 0.06 | |
| new_tenant_free_rent_months | int | no | 0 | |
| downtime_months | int | no | 3 | |
| renewal_probability | Decimal | no | 0.65 | |
| renewal_lease_term_months | int | no | 60 | |
| renewal_ti_per_sf | Decimal | no | 0 | |
| renewal_lc_pct | Decimal | no | 0.03 | |
| renewal_free_rent_months | int | no | 0 | |
| renewal_rent_adjustment_pct | Decimal | no | 0 | vs market |
| general_vacancy_pct | Decimal | no | 0.05 | |
| credit_loss_pct | Decimal | no | 0.01 | |

### GET /properties/{pid}/market-profiles — List
### PUT /properties/{pid}/market-profiles/{mid} — Update
### DELETE /properties/{pid}/market-profiles/{mid} — Delete

---

## Capital Projects

Scheduled building improvements spread across months.

### POST /properties/{property_id}/capital-projects

| Field | Type | Required |
|-------|------|----------|
| description | string | yes |
| total_amount | Decimal | yes |
| start_date | date | yes |
| duration_months | int | yes |

Monthly spend = total_amount / duration_months.

### GET /properties/{pid}/capital-projects — List
### PUT /properties/{pid}/capital-projects/{cpid} — Update
### DELETE /properties/{pid}/capital-projects/{cpid} — Delete

---

## Recovery Structures

Reusable per-category recovery templates assigned to leases.

### POST /properties/{property_id}/recovery-structures

| Field | Type | Required | Default |
|-------|------|----------|---------|
| name | string | yes | |
| description | string | no | |
| default_recovery_type | enum | no | nnn |
| items | array | no | [] |

Each item:
| Field | Type | Required |
|-------|------|----------|
| expense_category | enum | yes |
| recovery_type | enum | yes |
| base_year_stop_amount | Decimal | no |
| cap_per_sf_annual | Decimal | no |
| floor_per_sf_annual | Decimal | no |
| admin_fee_pct | Decimal | no |

### POST /.../recovery-structures/{rs_id}/items — Add item
### DELETE /.../recovery-structures/{rs_id}/items/{item_id} — Remove item
### PUT /.../recovery-structures/{rs_id} — Update header
### DELETE /.../recovery-structures/{rs_id} — Delete

---

## Valuations

### POST /properties/{property_id}/valuations

| Field | Type | Required | Default |
|-------|------|----------|---------|
| name | string | yes | |
| discount_rate | Decimal | yes | | 0 < x < 1 |
| exit_cap_rate | Decimal | yes | | 0 < x < 1 |
| exit_cap_applied_to_year | int | no | -1 | -1 = forward year NOI (Hold + 1) |
| exit_costs_pct | Decimal | no | 0.02 | |
| capital_reserves_per_unit | Decimal | no | 0.25 | $/SF/yr or $/unit/yr |
| use_mid_year_convention | bool | no | false | |
| description | string | no | | |
| loan_amount | Decimal | no | | |
| interest_rate | Decimal | no | | |
| amortization_months | int | no | | |
| loan_term_months | int | no | | |
| io_period_months | int | no | 0 | |

### POST /valuations/{id}/run — Execute valuation engine
### GET /valuations/{id}/reports/full — Full cached results
### GET /valuations/{id}/reports/key-metrics
### GET /valuations/{id}/reports/cash-flow-summary
### GET /valuations/{id}/reports/tenant-detail
### GET /valuations/{id}/reports/rent-roll
### GET /valuations/{id}/reports/lease-expirations

---

## Example: Create and Value a Simple Office Property

```bash
# 1. Create property
PROP=$(curl -s -X POST http://localhost:8001/api/v1/properties \
  -H "Content-Type: application/json" \
  -d '{"name":"100 Main St","property_type":"office","total_area":"50000","area_unit":"sf","analysis_start_date":"2025-01-01"}')
PID=$(echo $PROP | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# 2. Create suite
SUITE=$(curl -s -X POST http://localhost:8001/api/v1/properties/$PID/suites \
  -H "Content-Type: application/json" \
  -d '{"suite_name":"Suite 100","area":"25000","space_type":"office"}')
SID=$(echo $SUITE | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# 3. Create tenant
TENANT=$(curl -s -X POST http://localhost:8001/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Corp","industry":"Technology"}')
TID=$(echo $TENANT | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# 4. Create lease
curl -s -X POST http://localhost:8001/api/v1/suites/$SID/leases \
  -H "Content-Type: application/json" \
  -d "{\"tenant_id\":\"$TID\",\"lease_start_date\":\"2024-01-01\",\"lease_end_date\":\"2028-12-31\",\"base_rent_per_unit\":\"35.00\",\"escalation_type\":\"pct_annual\",\"escalation_pct_annual\":\"0.03\",\"recovery_type\":\"nnn\"}"

# 5. Create expenses
curl -s -X POST http://localhost:8001/api/v1/properties/$PID/expenses \
  -H "Content-Type: application/json" \
  -d '{"category":"real_estate_taxes","base_year_amount":"400000","growth_rate_pct":"0.03"}'

# 6. Create market profile
curl -s -X POST http://localhost:8001/api/v1/properties/$PID/market-profiles \
  -H "Content-Type: application/json" \
  -d '{"space_type":"office","market_rent_per_unit":"38.00","rent_growth_rate_pct":"0.03","downtime_months":6}'

# 7. Create and run valuation
VAL=$(curl -s -X POST http://localhost:8001/api/v1/properties/$PID/valuations \
  -H "Content-Type: application/json" \
  -d '{"name":"Base Case","discount_rate":"0.08","exit_cap_rate":"0.065"}')
VID=$(echo $VAL | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

curl -s -X POST http://localhost:8001/api/v1/valuations/$VID/run | python3 -m json.tool
```
