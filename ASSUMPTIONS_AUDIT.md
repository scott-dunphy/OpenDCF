# OpenDCF Assumptions & Input Field Audit

## Table of Contents
1. [All Assumptions by Category](#1-all-assumptions-by-category)
2. [Duplicates & Redundancies](#2-duplicates--redundancies)
3. [Recommendations](#3-recommendations)

---

## 1. All Assumptions by Category

### A. Property Settings
**Where entered:** Dashboard > New Property / Property Detail > Edit

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Property Name | text `form_name` | `name` | — |
| 2 | Property Type | select `form_property_type` | `property_type` | — |
| 3 | Area Unit | select `form_area_unit` | `area_unit` | sf |
| 4 | Total Area | number `form_total_area` | `total_area` | — |
| 5 | Year Built | number `form_year_built` | `year_built` | null |
| 6 | Address (line1, line2, city, state, zip) | 5 text fields | address fields | null |
| 7 | Analysis Start Date | date `form_analysis_start_date` | `analysis_start_date` | today |
| 8 | Analysis Period (months) | number `form_analysis_period_months` | `analysis_period_months` | 120 |
| 9 | Fiscal Year End Month | number `form_fiscal_year_end_month` | `fiscal_year_end_month` | 12 |

---

### B. Suite (Space) Settings
**Where entered:** Property Detail > Rent Roll Tab > New Suite / Edit Suite

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Suite Name | text `form_suite_name` | `suite_name` | — |
| 2 | Area (SF or Units) | number `form_area` | `area` | — |
| 3 | Space Type | text `form_space_type` | `space_type` | — |
| 4 | Floor | number `form_floor` | `floor` | null |
| 5 | Market Leasing Profile | select `form_market_leasing_profile_id` | `market_leasing_profile_id` | auto-match |

---

### C. Lease Terms
**Where entered:** Property Detail > Rent Roll Tab > New Lease / Edit Lease

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Suite | select `form_suite_id` | `suite_id` | — |
| 2 | Tenant | select `form_tenant_id` | `tenant_id` | null |
| 3 | Lease Type | select `form_lease_type` | `lease_type` | in_place |
| 4 | Payment Frequency | select `form_rent_payment_frequency` | `rent_payment_frequency` | annual |
| 5 | Base Rent | number `form_base_rent_per_unit` | `base_rent_per_unit` | — |
| 6 | Start Date | date `form_lease_start_date` | `lease_start_date` | — |
| 7 | End Date | date `form_lease_end_date` | `lease_end_date` | — |

#### C1. Escalation (conditional section on lease form)

| # | Assumption | Frontend Input | Backend Field | Default | Visible When |
|---|-----------|---------------|--------------|---------|-------------|
| 8 | Escalation Type | select `form_escalation_type` | `escalation_type` | flat | always |
| 9 | Annual Escalation % | number `form_escalation_pct_annual` | `escalation_pct_annual` | null | type=pct_annual |
| 10 | CPI Floor | number `form_cpi_floor` | `cpi_floor` | null | type=cpi |
| 11 | CPI Cap | number `form_cpi_cap` | `cpi_cap` | null | type=cpi |

#### C2. Recovery Settings (conditional section on lease form)

| # | Assumption | Frontend Input | Backend Field | Default | Visible When |
|---|-----------|---------------|--------------|---------|-------------|
| 12 | Recovery Structure | select `form_recovery_structure_id` | `recovery_structure_id` | null | always |
| 13 | Recovery Type | select `form_recovery_type` | `recovery_type` | nnn | no structure selected |
| 14 | Pro Rata Share % | number `form_pro_rata_share_pct` | `pro_rata_share_pct` | auto-calc | no structure selected |
| 15 | Base Year | number `form_base_year` | `base_year` | null | type=base_year_stop |
| 16 | Base Year Stop $ | number `form_base_year_stop_amount` | `base_year_stop_amount` | null | type=base_year_stop |
| 17 | Expense Stop $/SF | number `form_expense_stop_per_sf` | `expense_stop_per_sf` | null | type=modified_gross |

#### C3. Percentage Rent (conditional section on lease form)

| # | Assumption | Frontend Input | Backend Field | Default | Visible When |
|---|-----------|---------------|--------------|---------|-------------|
| 18 | Breakpoint ($) | number `form_pct_rent_breakpoint` | `pct_rent_breakpoint` | null | always |
| 19 | Pct Rent Rate | number `form_pct_rent_rate` | `pct_rent_rate` | null | always |
| 20 | Projected Sales $/SF/yr | number `form_projected_annual_sales_per_sf` | `projected_annual_sales_per_sf` | null | pct_rent_rate > 0 |

#### C4. Renewal Overrides (on lease form)

| # | Assumption | Frontend Input | Backend Field | Default | Notes |
|---|-----------|---------------|--------------|---------|-------|
| 21 | Renewal Probability | number `form_renewal_probability` | `renewal_probability` | null | Overrides market profile |
| 22 | Renewal Rent Spread % | number `form_renewal_rent_spread_pct` | `renewal_rent_spread_pct` | null | Overrides market profile |

---

### D. Lease Sub-Items (entered via modals on lease detail view)

#### D1. Rent Steps
**Where entered:** Lease Detail > Edit Schedule modal

| # | Assumption | Frontend Input | Backend Field |
|---|-----------|---------------|--------------|
| 1 | Effective Date | date `rsDate` | `effective_date` |
| 2 | Rent $/SF/yr | number `rsRent` | `rent_per_unit` |
| 3 | % Increase | number `rsPct` | (computed → rent_per_unit) |

#### D2. Free Rent Periods
**Where entered:** Lease Detail > Add Free Rent modal

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Start Date | date `form_start_date` | `start_date` | — |
| 2 | End Date | date `form_end_date` | `end_date` | — |
| 3 | Applies to Base Rent | checkbox `form_applies_to_base_rent` | `applies_to_base_rent` | true |
| 4 | Applies to Recoveries | checkbox `form_applies_to_recoveries` | `applies_to_recoveries` | false |

#### D3. Expense Recovery Overrides (per-lease, per-category)
**Where entered:** Lease Detail > Add Recovery Override modal

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Expense Category | text `form_expense_category` | `expense_category` | — |
| 2 | Recovery Type | select `form_recovery_type` | `recovery_type` | — |
| 3 | Base Year Stop ($) | number `form_base_year_stop_amount` | `base_year_stop_amount` | null |
| 4 | Cap $/SF/yr | number `form_cap_per_sf_annual` | `cap_per_sf_annual` | null |
| 5 | Floor $/SF/yr | number `form_floor_per_sf_annual` | `floor_per_sf_annual` | null |
| 6 | Admin Fee % | number `form_admin_fee_pct` | `admin_fee_pct` | null |

---

### E. Operating Expenses
**Where entered:** Property Detail > Expenses Tab > New Expense / Edit / Bulk Editor

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Category | text `form_category` | `category` | — |
| 2 | Description | text `form_description` | `description` | null |
| 3 | Base Year Amount ($) | number `form_base_year_amount` | `base_year_amount` | — |
| 4 | Annual Growth Rate | number `form_growth_rate_pct` | `growth_rate_pct` | 0.03 |
| 5 | Recoverable | checkbox `form_is_recoverable` | `is_recoverable` | true |
| 6 | Gross-Up Eligible | checkbox `form_is_gross_up_eligible` | `is_gross_up_eligible` | false |
| 7 | Gross-Up Vacancy % | number `form_gross_up_vacancy_pct` | `gross_up_vacancy_pct` | null |
| 8 | % of EGI | checkbox `form_is_pct_of_egi` | `is_pct_of_egi` | false |
| 9 | Percentage of EGI | number `form_pct_of_egi` | `pct_of_egi` | null |

---

### F. Other Income
**Where entered:** Property Detail > Other Income Tab > New Item / Bulk Editor

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Category | text `form_category` | `category` | — |
| 2 | Description | text `form_description` | `description` | null |
| 3 | Base Year Amount ($) | number `form_base_year_amount` | `base_year_amount` | — |
| 4 | Annual Growth Rate | number `form_growth_rate_pct` | `growth_rate_pct` | 0.03 |

---

### G. Market Leasing Profiles
**Where entered:** Property Detail > Market Assumptions Tab > New Profile / Edit / Bulk Workspace

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Space Type | text `form_space_type` | `space_type` | — |
| 2 | Market Rent | number `form_market_rent_per_unit` | `market_rent_per_unit` | — |
| 3 | Rent Growth Rate | number `form_rent_growth_rate_pct` | `rent_growth_rate_pct` | 0.03 |
| 4 | New Lease Term (months) | number `form_new_lease_term_months` | `new_lease_term_months` | 60 |
| 5 | New TI ($/SF) | number `form_new_tenant_ti_per_sf` | `new_tenant_ti_per_sf` | 0 |
| 6 | New LC % | number `form_new_tenant_lc_pct` | `new_tenant_lc_pct` | 0.06 |
| 7 | New Free Rent (months) | number `form_new_tenant_free_rent_months` | `new_tenant_free_rent_months` | 0 |
| 8 | Downtime (months) | number `form_downtime_months` | `downtime_months` | 3 |
| 9 | Renewal Probability | number `form_renewal_probability` | `renewal_probability` | 0.65 |
| 10 | Renewal Term (months) | number `form_renewal_lease_term_months` | `renewal_lease_term_months` | 60 |
| 11 | Renewal TI ($/SF) | number `form_renewal_ti_per_sf` | `renewal_ti_per_sf` | 0 |
| 12 | Renewal LC % | number `form_renewal_lc_pct` | `renewal_lc_pct` | 0.03 |
| 13 | Renewal Free Rent (months) | number `form_renewal_free_rent_months` | `renewal_free_rent_months` | 0 |
| 14 | Renewal Rent Adjustment | number `form_renewal_rent_adjustment_pct` | `renewal_rent_adjustment_pct` | 0 |
| 15 | General Vacancy % | number `form_general_vacancy_pct` | `general_vacancy_pct` | 0.05 |
| 16 | Credit Loss % | number `form_credit_loss_pct` | `credit_loss_pct` | 0.01 |

#### G1. Concession Timing (Multifamily/Self-Storage only)

| # | Assumption | Frontend Input | Backend Field | Default | Visible When |
|---|-----------|---------------|--------------|---------|-------------|
| 17 | Concession Timing Mode | select `form_concession_timing_mode` | `concession_timing_mode` | blended | unit properties |
| 18 | Year 1 Concession (months) | number | `concession_year1_months` | null | mode=timed |
| 19 | Year 2 Concession (months) | number | `concession_year2_months` | null | mode=timed |
| 20 | Year 3 Concession (months) | number | `concession_year3_months` | null | mode=timed |
| 21 | Year 4 Concession (months) | number | `concession_year4_months` | null | mode=timed |
| 22 | Year 5 Concession (months) | number | `concession_year5_months` | null | mode=timed |
| 23 | Year 6+ Concession (months) | number | `concession_stabilized_months` | null | mode=timed |

---

### H. Capital Projects
**Where entered:** Property Detail > Capital Projects Tab > New Project

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Description | text `form_description` | `description` | — |
| 2 | Total Amount ($) | number `form_total_amount` | `total_amount` | — |
| 3 | Start Date | date `form_start_date` | `start_date` | — |
| 4 | Duration (months) | number `form_duration_months` | `duration_months` | — |

---

### I. Recovery Structures (Templates)
**Where entered:** Property Detail > Recovery Structures Tab > New Structure

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Name | text `form_name` | `name` | — |
| 2 | Default Recovery Type | select `form_default_recovery_type` | `default_recovery_type` | nnn |

**Per-Item (within a structure):**

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 3 | Expense Category | text `form_expense_category` | `expense_category` | — |
| 4 | Recovery Type | select `form_recovery_type` | `recovery_type` | — |
| 5 | Base Year Stop ($) | number | `base_year_stop_amount` | null |
| 6 | Cap $/SF/yr | number | `cap_per_sf_annual` | null |
| 7 | Floor $/SF/yr | number | `floor_per_sf_annual` | null |
| 8 | Admin Fee % | number | `admin_fee_pct` | null |

---

### J. Valuation / DCF Parameters
**Where entered:** Property Detail > Valuations Tab > New Valuation / Edit

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 1 | Valuation Name | text `form_name` | `name` | — |
| 2 | Analysis Start Override | date `form_analysis_start_date_override` | `analysis_start_date_override` | null |
| 3 | Discount Rate | number `form_discount_rate` | `discount_rate` | 0.08 |
| 4 | Exit Cap Rate | number `form_exit_cap_rate` | `exit_cap_rate` | 0.065 |
| 5 | Exit Costs % | number `form_exit_costs_pct` | `exit_costs_pct` | 0.02 |
| 6 | Transfer Tax Preset | select `form_transfer_tax_preset` | `transfer_tax_preset` | none |
| 7 | Custom Transfer Tax % | number `form_transfer_tax_custom_rate` | `transfer_tax_custom_rate` | null |
| 8 | Capital Reserves $/SF/yr | number `form_capital_reserves_per_unit` | `capital_reserves_per_unit` | 0.25 |
| 9 | Exit Cap Applied to Year | number `form_exit_cap_applied_to_year` | `exit_cap_applied_to_year` | -1 |
| 10 | Mid-Year Convention | checkbox `form_use_mid_year_convention` | `use_mid_year_convention` | false |
| 11 | Apply Stabilized Gross-Up | checkbox `form_apply_stabilized_gross_up` | `apply_stabilized_gross_up` | true |
| 12 | Stabilized Occupancy % | number `form_stabilized_occupancy_pct` | `stabilized_occupancy_pct` | 0.95 |

#### J1. Debt Assumptions (optional section on valuation form)

| # | Assumption | Frontend Input | Backend Field | Default |
|---|-----------|---------------|--------------|---------|
| 13 | Loan Amount ($) | number `form_loan_amount` | `loan_amount` | null |
| 14 | Interest Rate | number `form_interest_rate` | `interest_rate` | null |
| 15 | Amortization (months) | number `form_amortization_months` | `amortization_months` | null |
| 16 | Loan Term (months) | number `form_loan_term_months` | `loan_term_months` | null |
| 17 | IO Period (months) | number `form_io_period_months` | `io_period_months` | 0 |

---

### K. Quick Setup / Bulk Editors (Convenience UIs)

These don't introduce new assumptions — they batch-apply the same fields listed above:

| UI | What It Does | Applies To |
|----|-------------|-----------|
| Market Assumption Workspace | Spreadsheet-style bulk edit of market profiles | Section G fields |
| Quick Setup (unit properties) | Apply same assumptions to all unit types at once | Section G fields |
| Bulk Expense Editor | Spreadsheet-style expense editing | Section E fields |
| Bulk Other Income Editor | Spreadsheet-style other income editing | Section F fields |
| In-Place Rent Editor | Bulk edit base rents across leases | Section C field #5 only |

---

## 2. Duplicates & Redundancies

### ISSUE 1: Renewal Probability — 3 places to enter

| Location | Field | Priority |
|----------|-------|----------|
| **Market Profile** (G.9) | `renewal_probability` (default 0.65) | Base assumption for space type |
| **Lease Form** (C.21) | `renewal_probability` | Per-lease override of market profile |
| **Quick Setup** | `same_renewal` | Batch-applies to market profiles |

**Verdict:** The market profile is the source of truth, the lease override is a legitimate per-tenant adjustment, and quick setup is a convenience tool. **Not truly redundant**, but could confuse users since the lease-level override silently wins. The UI doesn't clearly indicate when a lease override is active vs. defaulting to market.

---

### ISSUE 2: Recovery Type — 4 places to enter

| Location | Field | Notes |
|----------|-------|-------|
| **Lease Form** (C.13) | `recovery_type` | Per-lease default |
| **Recovery Structure** (I.2) | `default_recovery_type` | Template default |
| **Recovery Structure Item** (I.4) | `recovery_type` | Per-category within template |
| **Lease Recovery Override** (D3.2) | `recovery_type` | Per-lease per-category override |

**Verdict:** This is the most complex area. The priority chain is: Lease Recovery Override > Recovery Structure Item > Recovery Structure Default > Lease-Level `recovery_type`. **This is architecturally correct** (you need layered overrides for commercial leases), but the UI doesn't explain the precedence. Users may set a recovery type on the lease, assign a recovery structure, and not realize the structure overrides their lease-level setting.

---

### ISSUE 3: Base Year Stop Amount — 3 places to enter

| Location | Field |
|----------|-------|
| **Lease Form** (C.16) | `base_year_stop_amount` |
| **Recovery Structure Item** (I.5) | `base_year_stop_amount` |
| **Lease Recovery Override** (D3.3) | `base_year_stop_amount` |

**Verdict:** Same layered override pattern as recovery type. **Correct but confusing** — users don't know which one is actually being used in the engine.

---

### ISSUE 4: Renewal Rent Spread — 2 places to enter

| Location | Field |
|----------|-------|
| **Market Profile** (G.14) | `renewal_rent_adjustment_pct` |
| **Lease Form** (C.22) | `renewal_rent_spread_pct` |

**Verdict:** Same pattern as renewal probability. Market profile is the default, lease form is the override. **Naming inconsistency** — the market profile calls it `renewal_rent_adjustment_pct` while the lease calls it `renewal_rent_spread_pct`. Should use consistent naming.

---

### ISSUE 5: Free Rent Months — 3 conceptually different inputs

| Location | Field | What It Does |
|----------|-------|-------------|
| **Market Profile** (G.7) | `new_tenant_free_rent_months` | Months of free rent for speculative new tenant leases |
| **Market Profile** (G.13) | `renewal_free_rent_months` | Months of free rent for speculative renewal leases |
| **Lease Free Rent Period** (D2) | `start_date` / `end_date` | Explicit free rent period on an in-place lease |

**Verdict:** These are genuinely different things (market assumption for speculative leases vs. actual concession on a real lease). **Not redundant**, but naming is confusing — "free rent months" on market profile vs. date-range-based free rent on actual leases.

---

### ISSUE 6: Vacancy / Occupancy — 3 related fields, different contexts

| Location | Field | Purpose |
|----------|-------|---------|
| **Market Profile** (G.15) | `general_vacancy_pct` | Structural vacancy applied to GPR |
| **Expense** (E.7) | `gross_up_vacancy_pct` | Occupancy level to gross-up variable expenses to |
| **Valuation** (J.12) | `stabilized_occupancy_pct` | Target occupancy for exit-year gross-up |

**Verdict:** These serve different analytical purposes, but the relationship between them is not obvious. A user might expect `general_vacancy_pct` of 5% to imply 95% occupancy everywhere, but `gross_up_vacancy_pct` and `stabilized_occupancy_pct` are entered separately. **Consider linking or defaulting** `stabilized_occupancy_pct` to `1 - general_vacancy_pct` if unset.

---

### ISSUE 7: Growth Rates — entered separately on every expense and income item

| Location | Field | Default |
|----------|-------|---------|
| **Each Expense** (E.4) | `growth_rate_pct` | 0.03 |
| **Each Other Income** (F.4) | `growth_rate_pct` | 0.03 |
| **Market Profile** (G.3) | `rent_growth_rate_pct` | 0.03 |

**Verdict:** Per-item growth rates are correct for detailed modeling, but most users want a single "inflation" rate for all expenses and a single "rent growth" rate. The bulk editor helps, but there's no "apply one growth rate to all expenses" shortcut.

---

### ISSUE 8: Analysis Start Date — 2 places

| Location | Field |
|----------|-------|
| **Property** (A.7) | `analysis_start_date` |
| **Valuation** (J.2) | `analysis_start_date_override` |

**Verdict:** Legitimate — allows running multiple scenarios with different start dates from the same property data. **Not redundant.**

---

### ISSUE 9: Concession Timing Fields — 6 year-specific fields

The `concession_year1_months` through `concession_stabilized_months` fields (G.18–G.23) are only for multifamily/self-storage with `timed` mode. They create a lot of form clutter for a niche feature.

**Verdict:** Consider replacing with a small inline table/grid rather than 6 separate number inputs.

---

### ISSUE 10: Admin Fee % — 2 places

| Location | Field |
|----------|-------|
| **Recovery Structure Item** (I.8) | `admin_fee_pct` |
| **Lease Recovery Override** (D3.6) | `admin_fee_pct` |

**Verdict:** Same layered override pattern. Not redundant but no global default — most leases use the same admin fee %. Could benefit from a property-level default.

---

## 3. Recommendations

### HIGH PRIORITY — Reduce Confusion

#### R1: Show "Effective Assumptions" on Lease Detail
When viewing a lease, show a read-only summary panel of what the engine will actually use: the resolved recovery type (after layered overrides), the effective renewal probability (lease override vs. market default), etc. This eliminates confusion about which level wins.

#### R2: Consistent Naming for Renewal Rent Adjustment
Rename `renewal_rent_spread_pct` (lease) to `renewal_rent_adjustment_pct` to match the market profile field, or vice versa. Pick one name and use it everywhere.

#### R3: Link Vacancy/Occupancy Defaults
When `stabilized_occupancy_pct` is null on the valuation form, auto-populate the placeholder with `1 - average(general_vacancy_pct)` from market profiles. User can still override.

#### R4: Global Expense Growth Rate Shortcut
Add a "Set all growth rates to ___%" button at the top of the Expenses tab (or in the bulk editor). Most users want the same inflation rate across all line items.

### MEDIUM PRIORITY — Simplify Forms

#### R5: Collapse Recovery Complexity
The current 3-layer recovery system (lease default → recovery structure → lease override) is powerful but overwhelming. Consider:
- **Option A:** Remove recovery structure templates entirely; just use lease-level recovery type + per-category overrides. Simpler and covers 90% of use cases.
- **Option B:** Keep templates but hide them in an "Advanced" section. Default the lease form to just showing recovery type + pro rata share.

#### R6: Concession Timing as Inline Table
Replace the 6 `concession_yearN_months` fields with a small editable table:
```
Year  | Concession (months)
------|--------------------
1     | 2.0
2     | 1.5
3     | 1.0
4-5   | 0.5
6+    | 0.0
```
This is more intuitive and takes less vertical space.

#### R7: Group Lease Form Into Collapsible Sections
The lease form has ~22 fields. Break it into collapsible accordion sections:
1. **Basic Terms** (suite, tenant, dates, rent, frequency) — always expanded
2. **Escalation** — collapsed by default, expand based on type
3. **Recovery** — collapsed, show summary badge ("NNN" or "FSG")
4. **Percentage Rent** — collapsed, hidden for non-retail
5. **Renewal Overrides** — collapsed, show "Using market defaults" when empty

#### R8: Smart Defaults Based on Property Type
- **Office/Industrial:** Default recovery_type=nnn, hide percentage rent section
- **Retail:** Show percentage rent section, default recovery_type=nnn
- **Multifamily:** Hide recovery section entirely, hide escalation (use market rent growth), show concessions
- **Self-Storage:** Similar to multifamily

### LOW PRIORITY — Polish

#### R9: Merge Expense and Other Income Into One Tab
Both have the same structure (category, amount, growth rate). Combine into a single "Operating Budget" tab with an income/expense toggle or type column. This reduces tab count and makes the P&L picture clearer.

#### R10: Move Debt Assumptions to a Separate "Financing" Section
Debt parameters (loan amount, rate, amortization, term, IO period) are conceptually different from valuation assumptions (discount rate, cap rate). Splitting them into a distinct collapsible "Financing" section within the valuation form would improve clarity.

#### R11: Remove `is_available` From Suite Schema (or add to UI)
`is_available` exists on `SuiteBase` in the schema but has no frontend input. Either add a toggle to the suite form or remove it if unused.

---

## Summary Statistics

| Category | Field Count | Where Entered |
|----------|------------|---------------|
| Property Settings | 13 | Property form |
| Suite Settings | 5 | Suite form |
| Lease Terms | 22 | Lease form |
| Lease Sub-Items | 12 | Lease detail modals (rent steps, free rent, recovery overrides) |
| Expenses | 9 | Expense form / bulk editor |
| Other Income | 4 | Other income form / bulk editor |
| Market Profiles | 23 | Market profile form / workspace |
| Capital Projects | 4 | Capital project form |
| Recovery Structures | 8 | Recovery structure form |
| Valuation / DCF | 17 | Valuation form |
| **Total unique assumptions** | **~117** | **10 form types + 3 modals + 4 bulk editors** |

### Fields with Overlapping/Layered Entry Points: 15
(renewal_probability, renewal_rent_spread, recovery_type, base_year_stop_amount, admin_fee_pct, cap/floor, free_rent_months, vacancy/occupancy, growth_rates, analysis_start_date)
