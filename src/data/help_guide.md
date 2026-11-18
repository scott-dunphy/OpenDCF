# OpenDCF modeling guide

OpenDCF is a commercial real estate valuation app. You set up a property (space, leases, expenses), create a valuation (rates, hold period, market leasing assumptions), run it, and read the discounted cash flow results. This guide covers how to do things in the app. Text in **bold** is a label shown on screen; quote only those as screen labels.

## Entering numbers

- Percent fields take whole percents: type 3 for 3%. In a percent field, a number between −1 and 1 typed without "%" is multiplied by 100 (0.03 becomes 3%, and 0.5 becomes 50%). For a rate below 1%, type the % sign, e.g. "0.5%".
- One exception: in a self storage **Ancillary income** line with Basis "% of rental income", Amount is a fraction (0.02 means 2%).
- Required fields are marked with *.

## Getting around

- Top navigation:
  - **Properties** (property list).
  - **Portfolio**, with sub-pages **Funds**, **Cash flow rollup** and **Assumptions library**.
  - **Lending**, with sub-pages **Loan book**, **Risk runs**, **Simulations** and **Risk settings**.
  - **More ▾**, with **Import from Excel** and **Help & glossary**.
- **Search** (⌘K, or Ctrl+K on Windows/Linux):
  - Finds properties, valuations and tenants. It does not find loans or funds.
  - Also runs commands: New property, Toggle theme, Go to Properties (G P), Go to Portfolio (G F), Go to Lending (G L), Go to Help, Keyboard shortcuts (?), Ask modeling help.
  - On a property page it adds **New valuation**. On a valuation page it adds **Re-run valuation** and **Export full model**.
  - Pressing **n** on Properties starts a new property.
- The sun/moon icon switches between light and dark mode.
- **Help & glossary** (More ▾) has formulas and worked examples: the revenue waterfall, NOI/CFBD, recoveries, gross-up, reversion and DCF metrics.

## 1. Create a property

1. On **Properties**, click **New property**.
2. Fill in **Property Name**, **Property Type**, **Size** (rentable SF, or the number of units / slips / beds), and the address fields. **Area Unit** is set automatically from the type.
3. To add more detail, open the property and click **Edit details**:
   - **Year Built**, **Address Line 2**, **Market / submarket**, **Census market (CBSA)**, **Quality (1-5)**.
   - **Defaults for new valuations**: Analysis Start, Hold Period (months).
   - **Ownership & mapping**: Ownership Share %, Latitude, Longitude, Comment / Source Note.

Property Type options are Office, Retail, Industrial, Mixed Use, Multifamily, Self Storage, Marina and Seniors Housing. Multifamily, Self Storage, Marina and Seniors Housing are measured in units; the rest in SF.

Property page tabs depend on the type:

| Type | Tabs |
|---|---|
| Office, retail, industrial, mixed use | **Rent Roll**, **Operating Budget**, **Market Leasing**, **Recoveries** (structures, pools and the tenant recovery audit). **More** adds Capital Projects, Tenant list, Sales Comparables and Loans. |
| Multifamily | **Rent Roll** (unit types), **Operating Budget**. No Market Leasing or Recoveries. |
| Self storage with a unit mix | **Unit Mix**, **Operating Budget**. |
| Marina | **Slip Inventory**, **Operations**. |
| Seniors housing | **Unit Mix**, **Operations**. |

The property page shows a readiness card ("Set up this property" or "Ready to value, with gaps"). Each open item has an **Add** or **Review** button.

**Duplicate properties**: when the same building was created more than once (for example by several imports), the Properties page shows "N possible duplicate groups — review". To combine them, open the property to keep and use **More → Merge duplicates…**, tick the duplicates and confirm **Merge and delete**. Their valuations, comparable sales, loans, portfolio memberships and history move to the kept property, and the ticked properties are then permanently deleted. Only properties of the same type merge. Frozen (in review or approved) valuations move unchanged and still verify. If a duplicate had a different size, start date, hold or ownership, re-run its moved draft valuations.

## 2. Suites and space (office, retail, industrial, mixed use)

**Rent Roll** tab buttons: **Add / paste rent roll**, **New Suite**, **New Lease**. Each row's menu has **Edit suite** / **Delete suite**.

**New Suite** fields:
- **Suite Name**, **Area (SF)**, **Space Type**, **Floor**.
- **Re-lease As**: which market leasing profile the space uses when it rolls over. The default is "— Same as space type —".
- **Comment / Source Note**.
- **Lease-Up (vacant space)** section: **Leasing Begins** (blank = when the space is vacant) and **Lease-Up Months**. Use these to model vacant space that leases up over time.

**Add / paste rent roll** is a grid for entering many suites at once. Columns:
- Suite, Area SF, Space Type.
- Tenant (blank = vacant).
- Lease Start, Lease End.
- Rent $/SF/yr.
- Bumps %/yr: any value above 0 becomes a Pct Annual escalation.
- Recoveries.

Each lease row needs start, end and rent.

**Zero-SF space (antenna, signage, parking income tied to no area):**
1. Use **New Suite** with Area 0. The paste grid does not accept 0 area.
2. On the lease, set **Rent Basis** to "Total $ amount (e.g. antenna, 0 SF)".
3. Base Rent is then the whole dollar amount.

## 3. Tenants

- Add a tenant from the lease form with the **+ New Tenant** link next to **Tenant**, or from **More ▸ Tenant list** → **New Tenant**.
- Fields are **Tenant Name**, **Credit Rating**, **Industry**, **Contact Name**, **Contact Email** and **Comment / Source Note**. For multifamily and self storage the name is shown as **Resident Name**, and credit rating and industry are hidden.
- To rename a tenant, click the tenant cell in the rent roll.

## 4. Leases

Open with **New Lease** (Rent Roll tab) or a row's edit action (**Edit Lease**).

### Core terms
- **Suite**: chosen only when creating a lease.
- **Tenant**: "— None (Vacant) —" leaves the suite vacant.
- **Lease Type**: In Place, Market, or Month To Month.
- **Payment Frequency**:
  - "Annual ($/SF/yr)" or "Monthly ($/unit/mo)".
  - Choose it when creating the lease. Changing it later on Edit Lease does not take effect; delete and re-create the lease instead.
- **Rent Basis**: "Per SF / unit × area" or "Total $ amount (e.g. antenna, 0 SF)".
- **Base Rent** (must be above 0), **Start Date**, **End Date**.

### Rent increases
Set **Escalation Type**:
- **Flat**: no increases.
- **Pct Annual**: set **Annual Escalation %**. Rent compounds on each lease anniversary.
- **Cpi**:
  - Set **CPI Floor (%)** and **CPI Cap (%)** on the lease. Rent steps on each anniversary by CPI, held between the floor and the cap.
  - The CPI rate itself is on the valuation (**Rates & exit** → Reserves, inflation & conventions): **CPI Rate** (blank = 2.5%) and **CPI by Year (%)**.
- **Fixed Step**: specific dated rent steps.
  1. Set Escalation Type to **Fixed Step** and save. Steps are ignored under any other type, and adding steps does not change the type for you.
  2. From the lease row menu choose **Rent schedule (n)**.
  3. Under **Add Rent Step**, enter an **Effective Date** and either **Rent $/SF/yr** (or $/Unit/mo) or "% Increase from previous".
  4. Click **Add Step**.

### Free rent
1. From the lease row menu choose **Free rent & recovery overrides (n)**.
2. Under **Free Rent Periods**, click **Add**.
3. Enter **Start Date** and **End Date**. **Applies to base rent** is on by default. Tick **Applies to recoveries** if the tenant also doesn't pay recoveries during that time.

Free rent is abated by day count. Free rent for future (market) leases comes from the market leasing profile. A fraction of a month there (e.g. 2.5 months from a by-year schedule) abates that fraction of the next month's rent, and the leasing commission counts the same abated rent.

### Expense recoveries
Lease form, Recovery section:
- **Recovery Type**:
  - **Nnn**: tenant pays its share of recoverable expenses.
  - **Full Service Gross** / **None**: no recoveries.
  - **Modified Gross**: recoveries over a pooled stop. Set **Expense Stop $/SF**. With no stop the tenant pays every recoverable expense, like NNN. A recoverable % of EGI fee (management fee) is in the pool too.
  - **Base Year Stop**: tenant pays increases over a base year. Set **Base Year**, or enter **Base Year Stop $** directly.
- **Pro Rata Share %**: blank = suite area ÷ property area, or ÷ the recovery pool's denominator for expenses in a pool (below). A typed share replaces the area ÷ denominator for every expense. For an expense in a pool it is a share of what the pool bills (after excluded tenants' payments are deducted, with the pool's gross-up rule), not of the whole expense. Market leases keep a typed share only when the profile's Recovery Structure is "Same as expiring lease". For Modified Gross it applies to the excess over the stop: (pooled $/SF − stop) × property area (or pool denominator) × share.
- **Recovery Structure**: picks a saved template (below). **+ New** makes one without leaving the lease; **Edit overrides** changes the picked one's category rules. When a template is chosen, the template's default type replaces the lease's Recovery Type (hidden); Pro Rata Share still applies.
- The Rent Roll's **Recovery** column shows what applies (template or type, plus overrides); click it to open the lease's overrides. A vacant suite shows the market profile and template it leases up with.

How base year stops resolve: a category override's stop first, then the lease's Base Year Stop $, then the actual expense in the Base Year, then the Year 1 expense. When two or more categories use the lease's base-year stop, the stop is pooled across them automatically.

Which categories share the pooled stop (Base Year Stop and Modified Gross alike): every category on the lease's recovery type, unless its override (or template item) sets its own stop or a different recovery type; that category is measured alone. An override that only adds a cap, floor or admin fee keeps its category in the pool, and the cap, floor or fee applies to that category's part of the pooled recovery.

**Recoverable % of EGI fees (management fee and any other % of EGI line):** each line is recovered on the lease's terms for that line (its Recovery Type or category override, pool, gross-up, cap, floor and admin fee), like any other expense.
- Net: the tenant pays its share of the line's fee. The fee depends on EGI, which the reimbursement raises, so the two are solved together.
- Base Year Stop: the tenant pays its share of the line's increase over its fee in the base year. For a base year before the analysis, that fee is estimated from the first analysis year's fee, moved in line with the other recoverable expenses (the first year's fee when there are none).
- Modified Gross: the fee is in the pool measured against the stop.
- Base Year Stop and Modified Gross need the fee by year, which their reimbursement changes: the cash flow is re-run until the fee moves by less than a cent (a few passes; at most 10).

**Per-category rules (caps, floors, admin fees, different treatment for taxes vs CAM, and so on):**
1. From the lease row menu choose **Free rent & recovery overrides (n)**.
2. Under **Expense Recovery Overrides**, click **Add**.
3. Fill in:
   - **Expense Category**, **Recovery Type**, **Base Year Stop ($)** (base year stop rows), **Expense Stop $/SF/yr** (modified gross rows: this category alone is measured against it).
   - **Cap $/SF/yr**, **Floor $/SF/yr** (not used for modified gross), **Admin Fee %**.
   - **Cap Group**: a name shared by categories that have one combined cap.
   - **Cap Growth %/yr**.
- Order on each category: the admin fee, then the floor, then the cap. When the floor is above the cap, the cap wins (published DCF software applies the minimum and then the maximum). A cap includes the admin fee, with or without a Cap Group.
- How caps work:
  - **Cap $/SF/yr** with no Cap Group is a flat annual cap on that category's recovery (cap × tenant area). It does not grow.
  - **Cap Growth %/yr** only works when **Cap Group** is filled in. The group's combined recovery may grow at most that rate each year from its level in the year the lease starts. When the group's categories are Base Year Stop or Modified Gross, the cap limits the tenant's share of their expenses instead, and the stop comes off the capped amount (so a base-year lease recovers the capped increase, not $0). A management fee in the group counts too; for a lease that started before the analysis, its fee in the start year is estimated from the first analysis year's fee, moved in line with the group's other expenses. For a growth cap on a single category (e.g. CAM capped at 5% a year), give that category a Cap Group name of its own, such as "CAM".
  - Categories in the same Cap Group share one cap: a $/SF cap on their combined recovery, a growth cap, or both. The group's Cap $/SF/yr and Cap Growth %/yr come from whichever member has them.
- Caps, floors and admin fees can only be set here or in a recovery structure, not on the main lease form.
- Older models entered a Modified Gross override's stop as its **Floor $/SF/yr**; it is still read as the stop when **Expense Stop $/SF/yr** is blank.

**Recovery templates (reuse one recovery setup across many leases):**
1. Go to the **Recoveries** tab → **Structures** → **New Recovery Structure** (or **+ New** beside a lease's or market profile's Recovery Structure field) (Name, Description, **Default Recovery Type**; for Modified Gross, **Expense Stop $/SF/yr**). The template's stop replaces a lease's own stop when set.
2. Each card lists the leases and market profiles using it. The category overrides grid opens next: one row per category, using the same fields as above. Edit them later with **Edit Category Overrides** on the template's card; blank cells clear a value.
3. Pick the template in a lease's **Recovery Structure** field. A lease's own per-category overrides win over template items.
4. To give future market leases (renewals, new tenants, vacant space leasing up) these terms, pick the template in the market leasing profile's **Recovery Structure** field (section 8).

**Recovery pools (share some expenses over a different area, e.g. anchors excluded from shop CAM):**
1. Go to the **Recoveries** tab → **Pools** → **New Recovery Pool**. An expense's pool can also be picked in its **Recovery Pool** field on the Operating Budget, where each pooled expense shows its pool's name.
2. Tick the **Expense Categories** in the pool. Each recoverable expense can be in one pool only. Expenses in no pool are shared over the whole property area, as before.
3. Pick the **Denominator** (each tenant's share = its area ÷ the denominator):
   - "Property area less excluded suites" (default).
   - "Fixed area": enter **Fixed Denominator Area**.
   - "Occupied area": the leased area of the included suites, averaged over each recovery year (a lease ending or starting mid-month counts for the days it covers). Optional **Minimum Occupancy %** sets a floor (e.g. 90% = the denominator is never below 90% of the included area). Expenses in an occupied-area pool are not grossed up, since tenants already share the vacancy.
4. Under **Excluded Suites**, tick anchors or outparcels to leave out of the denominator. Their leases still recover on their own terms (Recovery Type, caps, overrides) over the whole property area.
5. **Deduct what excluded suites pay from the pool before others share it** (on by default): the other tenants share the expense less what the excluded tenants pay. Untick it if the leases say inline tenants share the full expense over the smaller area.
- Applies to in-place and future market leases. Pools belong to the valuation; a copy or roll-forward takes its own copy.
- The **Tenant Recovery Audit** shows each row's **Recovery Pool**, **Share Denominator** and **Pool Deduction**.
- Gross-up in a "Property area less excluded suites" pool with excluded suites grosses up only the included suites' vacancy: the expense is taken at the occupancy the property would have with the included suites at the gross-up occupancy and the excluded suites as they are. A dark anchor's space is not grossed back up and billed to the shops. A pool with no excluded suites, and a "Fixed area" pool (its area need not be the included suites'), gross up at property occupancy like an unpooled expense.
- A base year stop in a deducting pool is net of what the excluded tenants paid in the base year. A base year before the analysis uses the Year 1 pool expense net of what they paid, moved back as the expense is deflated (an unpooled pre-analysis base year deflates the Year 1 expense as entered).
- A base-year lease in a deducting pool measures its stop and each later year the same way: the pool's expense less what the excluded tenants actually paid that year. If an anchor is dark in a shop lease's base year, it paid nothing, so the stop is the full expense; once the anchor re-leases and pays, the pool's net expense falls below the stop and the shop recovers nothing. The reverse also holds: an anchor that pays in the base year and goes dark later leaves its share above the stop for the shops. To avoid either, enter a **Base Year Stop $** on the lease or structure, or untick the deduction.
- A base-year lease in an occupied-area pool: the pool is not grossed up, so its stop is the expense incurred at the base year's occupancy and each later year is the expense incurred at that year's occupancy. When occupancy rises after the base year, the tenant pays the extra variable cost even though the cost per occupied SF has not changed. Published DCF software does not document gross-up for occupied-area pools. To bill only real cost increases, use a "Property area less excluded suites" pool with gross-up, or enter a **Base Year Stop $**.
- An occupied-area pool with no minimum puts the whole expense on the tenants in place, however few. Set a Minimum Occupancy % to cap their share.
- A % of EGI fee in a pool uses the pool's denominator, and with the deduction ticked the other tenants share the fee less what the excluded tenants pay toward it, whatever their recovery types: a Net anchor's share of the fee comes off Base Year Stop and Modified Gross shops' fee, and a Base Year Stop or Modified Gross anchor's fee payment comes off Net shops' share. A fee grosses up like the pool's other lines: in a "Property area less excluded suites" pool only the included suites' vacancy is grossed up, so a dark anchor does not raise the shops' fee. A fee in an occupied-area pool is not grossed up.
- Pools hold expense categories by name: renaming an expense category takes it out of its pool, so tick it again.

**Gross-up** is not a lease setting:
- On each expense line, tick **Gross-up eligible** and set **Gross-Up Occupancy %**.
- On the valuation, optionally tick **Apply stabilized gross-up** with **Stabilized Occupancy %**.
- Gross-up changes only the expense pool tenants are billed against. NOI expenses stay as entered.
- A % of EGI line is grossed up on its own Gross-up eligible tick and Gross-Up Occupancy %, whatever its category name. (Published DCF software documentation suggests % of revenue lines are not occupancy-adjusted there; leave the tick off to match.)
- Occupancy is the leased area averaged over the year, counting a lease that ends or starts mid-month for the days it covers.
- With **Calendar-year recoveries**, each calendar year is billed at that calendar year's average occupancy, the same occupancy its base-year stop uses, even when the analysis year ends in another month. A market lease therefore recovers nothing in its own base year.

Recovery audit: **Recoveries ▸ Tenant Recovery Audit** shows per-tenant recovery math (columns explained on Help & glossary). For Modified Gross rows, **Pooled Exp/SF** is the pooled $/SF that row's stop is tested against; a line with its own stop is measured alone, so it shows that line's own $/SF.

### Percentage rent (retail)
- In the Percentage Rent section, fill **Breakpoint ($)**, **Pct Rent Rate (%)** and **Projected Sales $/SF/yr**. All three are needed; otherwise no percentage rent is charged.
- Formula: (sales/SF × suite area − breakpoint) × rate.
- Not available for multifamily or self storage.

### Renewal and expiration (per lease)
- **Renewal Probability (%)** and **Renewal Rent Adjustment (%)** override the market profile for this lease's first rollover only. Blank uses the market profile.
- **Credit tenant: exclude from general vacancy and credit loss**:
  - Stops the general vacancy and credit loss deductions from applying to this tenant.
  - Sub-option **Exclude upon rollover** ends the exclusion when this lease expires.
- **Upon Expiration** decides what happens at lease end:
  - "Market (renewal probability blend)": a blend of renewal and new tenant per the market profile.
  - **Renew**: the tenant renews.
  - **Vacate**: the tenant leaves and the space re-leases to a new tenant.
  - **Contract Option**: a fixed option. Set **Option Rent**, **Option Term (months)**, **Option TI ($/SF)** and **Option LC %**. A blank Option Rent is the market rent at exercise (plus the renewal adjustment), paid in the market profile's rent units and frequency.
  - "Reabsorb (stays vacant)": the space stays vacant.

### Leasing costs already committed
- **Committed TI ($ total)** and **Committed LC ($ total)** are paid at lease start, or at analysis start if the lease already began.
- TI and LC for future leases come from the market leasing profile.

### Lease types, month-to-month and vacancy
- **Month To Month**: treated as expiring at the end of the End Date month, then rolls to market. Set End Date to the month you expect it to end.
- A lease whose End Date is before the analysis start rolls over on that date at Year 1 market terms (rent, free rent, escalation, leasing costs). A base-year stop on the market lease uses the year it starts, with that year's expenses deflated from Year 1. Its TI and leasing commission were spent before the analysis, so they are not charged; later market leases pay theirs as usual.
- **Market** lease type is projected like In Place but is left out of the property page's Occupancy figure. Use it for leases signed at market terms that you don't want counted as current occupancy.
- A vacant suite with no lease: leased up using market assumptions from analysis start. If Leasing Begins or Lease-Up Months is set, it leases up on that timing instead. Blank Lease-Up Months uses the profile's downtime.
- Before a suite's first future lease starts: the space is vacant.
- No matching market profile: if no market profile matches the suite's space type (or Re-lease As), the space is never re-leased and stays vacant after expiry.
- Security deposits are not modeled.

### Common lease errors
- "lease_end_date must be after lease_start_date"
- "Lease date range overlaps an existing lease for this suite": end the old lease before the new one starts.
- "Tenant belongs to a different property"
- Base rent and rent steps must be above zero.
- Percent limits:
  - Annual Escalation, Pro Rata Share, Renewal Probability, Pct Rent Rate, Option LC and Admin Fee: 0–100%.
  - Renewal Rent Adjustment: −100% to 200%.
- Free rent: end date must be on or after start date.
- Lease-Up Months: 0–120.

## 5. Multifamily

On the **Rent Roll** tab click **Add Unit Type**. Fields:
- **Unit Type Name**, **Unit Type Key**, **Unit Count**.
- **Vacant (no current lease)**.
- Current Lease: **Resident Name**, **Rent $/Unit/mo**, **Lease Start**, **Lease End**.

Each unit type gets one flat monthly lease with no recoveries; a multifamily or self storage lease never recovers expenses, whatever recovery type it was saved or imported with. Escalations, recoveries, percentage rent and per-lease renewal settings are hidden for unit properties. Expenses are entered as "$ per unit per year".

## 6. Operating expenses and other income

**Operating Budget** tab (called **Operations** for marina and seniors housing).

**New Expense** fields:
- **Category**:
  - Commercial: real estate taxes, insurance, CAM, utilities, management fee, repairs & maintenance, general & admin, other.
  - Multifamily and self storage: also payroll, marketing and contract services; no CAM.
- **Amount Entered As**: "Total $ per year" or "$ per SF per year" ("$ per unit per year" for multifamily).
- **Base Year Amount ($)**.
- **Annual Growth Rate** (default 3%), or **Growth by Year (%)** for a different rate each year.
- **Amount by Year**: optional amounts for Year 1, Year 2, … (for example a budget), in the basis chosen in Amount Entered As. They replace the base amount and growth for those years. Later years, including the year after the hold used for the sale, grow from the last amount at the growth rate.
- **Variable with Occupancy %**: the share of the expense that moves with occupancy.
- **Recoverable from tenants**: include it in tenant recoveries.
- **Gross-up eligible** / **Gross-Up Occupancy %**: hidden for multifamily and self storage.
- **% of EGI (instead of fixed amount)** with **Percentage of EGI**: use this for a management fee as a percent of income.

**Bulk Edit** opens the Expense Workspace grid. It includes **Set All Growth Rates**.

**Other income** (parking, signage, and so on): section **Custom Revenue Line Items** → **New Revenue Item**. Fields are Category, Description, Base Year Amount ($), Annual Growth Rate, Growth by Year (%) and **Amount by Year ($)** (works like the expense field above).

## 7. Capital projects and reserves

- One-off capital projects: on the property page, **More → Capital Projects** → **New Project**. Enter Description, **Total Amount ($)**, **Start Date** and **Duration (months)**; the cost is spread evenly over the months. Not available for marina or seniors housing.
- Ongoing reserves are on the valuation: **Capital Reserves $/SF/yr** ($/Unit/yr for unit properties) and **Capital Reserves Growth**.

## 8. Market leasing assumptions (what happens when leases expire and vacant space leases)

Market leasing profiles belong to each valuation. A new valuation copies the latest valuation's profiles.

Edit them on the property's **Market Leasing** tab (pick the valuation in the **Valuation** picker), or from the valuation page's **Market leasing (N)** button.
- You need a valuation first: "Add a valuation first: market leasing belongs to each valuation".
- Frozen valuations are read only.
- Hidden for multifamily, self storage, marina and seniors housing.

Click **New Market Profile**. Fields:
- **Space Type**: must match the suite's Space Type or **Re-lease As**.
- **Market Rent ($/SF/yr)**, **Rent Basis**.
- **Rent Growth Rate**, or **Rent Growth by Year (%)**.
- **New Tenant Assumptions**:
  - Lease Term (months).
  - TI ($/SF).
  - Leasing Commission %, Leasing Commission ($/SF).
  - **LC % by Lease Year**: optional. A rate for each lease year, counted from the lease start (year 1 = its first 12 months), not the analysis year. Example: `6, 6, 6, 6, 6, 3` = 6% of years 1-5 and 3% of later years. The last rate carries forward and a short final year takes that year's rate. Replaces the single %; still paid up front when the lease starts. With blended leasing, each year's rate is weighted between renewal and new tenant.
  - Free Rent (months).
  - **Downtime (months)**: months vacant before a new tenant.
  - **Free Rent by Year (months)** and **Downtime by Year (months)**: optional values by year. Free rent goes by the year the new lease starts; downtime by the year the old lease expires.
- **Renewal Assumptions**:
  - Renewal Probability (default 65%), Renewal Term (months).
  - Renewal TI ($/SF), Renewal LC %, Renewal LC ($/SF), **Renewal LC % by Lease Year**.
  - Renewal Free Rent (months), Renewal Rent Adjustment.
  - **Renewal Rent**: Market (market rent × the renewal adjustment), or the **greater** or **lesser of market or prior rent**.
    - Prior rent = the expiring lease's rent in its last month, including steps and escalations, ignoring free rent. It is converted to the profile's rent basis and frequency.
    - The comparison is with market rent after the renewal adjustment.
    - New tenants always pay market.
    - With blended leasing, the rule applies to the renewal share before weighting: a 60% renewal at a $40 prior rent and 40% new tenant at $35 market is $38. This is an Ares choice; published DCF software documentation found so far does not settle it.
    - Vacant space leasing up has no prior rent and pays market.
  - **Renewal Probability by Year (%)** (by the year the lease expires) and **Renewal Free Rent by Year (months)** (by the year the renewal starts).
  - Leasing Cost Growth, or **Leasing Cost Growth by Year (%)**.
- Every "by Year" field is optional: Year 1, Year 2, …; the last value carries forward, and it overrides the single value next to it. Separate values with ";" or ", " ("120,000" is read as one number).
- **Rollover Method**:
  - "Weighted branches": renewal and new-tenant outcomes are weighted by probability.
  - "Blended lease (published DCF software)": a single blended lease.
- **Market Lease Escalation** and **Market Lease Rent Steps**: increases within future market leases.
  - **Market Lease Escalation ($/SF/yr)**: a fixed annual increase (for example $0.50/SF each year) instead of the %. Set one or the other.
- **Vacancy & Credit**: **General Vacancy %** and **Credit Loss %** are set here, per profile, not on the valuation. **General Vacancy by Year (%)** and **Credit Loss by Year (%)** set a different rate for each analysis year.
- A fund assumption profile or scenario that sets vacancy, credit loss, renewal probability, downtime or free rent replaces the by-year values; one that shifts them moves every year.
- **Upon Expiration Use MLA**: chain to another profile for the next rollover.
- **Expense Recoveries ▸ Recovery Structure**: the recovery template (section 5) used by every market lease under this profile: renewals, new tenants and vacant space leasing up. It also sets the recoveries assumed when vacant months are filled at full occupancy.
  - "— Same as expiring lease —" (the default): a market lease keeps the expiring lease's whole recovery assignment: its Recovery Type, its per-category overrides and template items (caps, floors, admin fees, categories it does or does not pay), its Modified Gross stop and its typed Pro Rata Share. Each later market lease in the suite keeps them too. Space never leased (including lease-up before a suite's first lease) is NNN with the area share.
  - With a template, the lease uses the template's terms, including its Modified Gross stop, and the area share (suite area ÷ property area, or the pool's denominator); a typed Pro Rata Share on the expiring lease is not carried.
  - The base year resets on every market lease: Base Year Stop uses the year the market lease starts, and a fixed Base Year Stop $ (on the lease or on a template category) is dropped. Modified Gross with no stop set becomes a base-year stop from that year. Growth caps restart from the market lease's start.
  - Full occupancy: each vacancy is filled by a lease on these same terms, with its base year in the year that vacancy starts.
  - Contract Option leases keep the expiring lease's recovery type, per-category overrides and stop; the base year resets to the option start (Modified Gross with no stop becomes a base-year stop), and growth caps keep growing from the original lease start. Market leases after the option follow the option's terms.

**Assumption Workspace** is a grid for editing many profiles quickly. Its columns are Space Type, Mkt Rent, Growth %, Vacancy %, Credit %, Renewal %, New TI, New Concession, Renewal Concession, Concession Timing, Recovery Structure and Comment. Downtime, terms, LCs and renewal TI are edited in the profile form.

Each lease's **Upon Expiration** setting (section 4) decides whether these assumptions are used at its expiry. The **Lease Details** dialog shows "Effective Assumptions (resolved)": the lease's override versus the market default.

## 9. Valuation settings

Create with **New valuation** on the property page (the button saves and runs: **Create & run**). Change later with **Rates & exit** on the valuation page. **Rent roll & expenses** opens this valuation's model (rent roll, expenses, market leasing, recoveries) on the property page.

- Top of the form:
  - Valuation Name, **Analysis Start**, **Hold Period (years)** (1–30).
  - **Discount Rate** (default 8%), **Exit Cap Rate** (default 6.5%).
  - **Purchase Price ($)**: needed for a meaningful IRR.
- **Sale & exit** section:
  - Exit Costs % (default 2%).
  - Exit Cap Applied to Year: −1 = forward-year NOI. By default the sale uses Year N+1 NOI.
  - Transfer Tax presets or Custom Transfer Tax %; Sale Proceeds Timing.
  - "Deduct Year N+1 TI/LC/capex from sale".
  - "Capitalize reversion NOI adjusted for full occupancy", with Stabilized Vacancy %.
- **Acquisition**: Acquisition Costs %, Direct Cap Rate.
- **Financing**: Loan Amount ($), Interest Rate, Amortization (months), Loan Term (months), Interest-Only Period (months), Loan Fees %.
  - **Additional Loans** (second mortgage, mezzanine): one per line, `label; amount; rate %; amortization months; term months; interest-only months; fees %`. Example: `Mezz; 1,000,000; 10; ; 60; 60; 1`. Blank amortization = 360 months; blank term = outstanding until the sale.
  - Not offered for marina and seniors housing models, which use their own debt inputs.
  - Every loan is funded at close. Debt service, the balance repaid at sale and loan fees are the sum of all loans. LTV, debt yield and DSCR use the total loan and total debt service.
- **Reserves, inflation & conventions**:
  - Capital reserves.
  - Mid-year discounting.
  - **CPI Rate** / **CPI by Year (%)**.
  - General vacancy options.
  - Calendar-year recoveries.
  - **Apply stabilized gross-up** with **Stabilized Occupancy %**.
- **Basis of value & notes**: Basis of Value, Intended Use, Risk Treatment, Cash Flow Basis, Discount Rate Basis. Cash Flow Basis and Discount Rate Basis must match.

Analysis years are 12-month periods counted from the Analysis Start date (Year 1 = the first 12 months); there is no separate fiscal year setting.

## 10. Running a valuation

- Click **Run valuation** / **Re-run** on the valuation page, or **Run** / **Re-run** in the property's Valuations panel.
- What blocks a run ("Not ready to run: …"):
  - A rent roll property with no suites (or unit types). Add them on the Rent Roll tab.
  - A seniors housing property with no unit mix and operations.
- Warnings that don't block:
  - No in-place leases (modeled fully vacant).
  - No market assumptions for a space type (that space is never re-leased).
  - No operating expenses (NOI equals revenue).
  - Suite areas not matching the property size.
- Status pills: Draft, Not run, Current, Needs re-run, In review, Approved.
- "Property inputs changed after this ran." means inputs changed since the last run. Click **Re-run now**.
- "The valuation engine was updated after this ran." (pill: **Needs re-run (engine updated)**) means OpenDCF's calculations changed since the last run; the inputs did not. Click **Re-run now**. A frozen valuation keeps its result; **Valuation → Verify frozen result** compares it with today's engine.

## 11. Reading results

- Headline figures: Value (NPV), Going-in cap, Terminal value, Avg occupancy, WALT, and IRR (shown only with a purchase price).
- Chart: NOI or Cash flow before debt.
- **Annual Cash Flow Summary**:
  - **Annual/Monthly** toggle.
  - Rows such as Scheduled Base Rent, Free Rent, Expense Recoveries, Turnover Vacancy, Operating Expenses, Tenant Improvements and Leasing Commissions expand to show each tenant.
  - Other rows: Gross Potential Income, General Vacancy, Credit Loss, Effective Gross Income, Net Operating Income, Capital Reserves, Building Improvements, Cash Flow Before Debt, Debt Service, Levered Cash Flow.
  - Hover a tenant's name in an expanded row to see its current rent today (from the lease in force today) and the market profile for its space type.
- The reversion (terminal value) calculation sits directly under the cash flow table.
- Further sections:
  - **Acquisition Returns**: XIRR, periodic IRR, MIRR, multiples, DSCR, LTV.
  - **Value Sensitivity: Discount Rate × Exit Cap**.
  - Lease Expiration Schedule.
- **Export** menu:
  - Full model (Excel), Investment memo (PDF): both need results.
  - Rent roll (Excel).
  - **Deal package (.odcf.zip)**: the self-contained file to send someone. It holds the model, the source documents, their AI readings and the extracted facts with their review status (accepted, rejected or proposed). A frozen valuation exports its frozen model.
  - **Model and facts only (.odcf.json)**: the same without the document files.
- Key formulas (more on Help & glossary):
  - EGI = gross potential income − general vacancy − credit loss.
  - NOI = EGI − operating expenses.
  - Cash flow before debt = NOI − TI − LC − reserves − building improvements.
  - Terminal value = NOI basis ÷ exit cap − exit costs − transfer tax.

## 12. Exploring changes: what-if, chat and copilot

- What-if panel (valuation page, titled **What-if**):
  - Sliders for **Discount rate** and **Exit cap rate**. Not saved.
  - **Reset to saved** returns to the saved rates.
  - **Save as scenario** duplicates the valuation with the new rates and runs it.
  - Not available for marina or seniors housing.
- **Analyze → What if…**:
  - Ask a what-if in plain words, e.g. "what if market rent is 10% lower?". It runs the engine on a temporary copy and shows the change in value.
  - Nothing is saved.
- **Analyze → AI copilot**:
  - Asks about, or proposes edits to, this valuation's inputs. You confirm with **Apply changes** or **Reject**.
  - **Always allow changes** skips confirmation (marked Dangerous).
- What-if chat and the copilot work on draft valuations only. For a frozen valuation, duplicate it first.
- **Scenarios**: to compare alternatives, use **Valuation → Copy valuation and model**. It copies assumptions and market profiles, not results, named "(copy)". Edit the copy and run it.

## 13. Review lifecycle

- **Submit for review…**: enter your name and a note, then **Run, freeze & submit**. The valuation is frozen, so its inputs and results can't change.
- **Approve…** marks it approved. **Reopen…** returns it to draft and requires a reason.
- **Valuation** menu: **Verify frozen result**, **Review history**, **Copy valuation and model**, **Roll forward…**, **Delete valuation…**. A valuation with review history can't be deleted.
- Editing a frozen valuation gives "…is frozen for review; reopen or duplicate it to change…".

## 14. Importing data

**From documents** (Properties → **Import ▾ → From documents**, or the property page's **More → New valuation from documents**):
- Accepts PDF, Excel (.xlsx/.xlsm), CSV, text and images, such as OMs, rent rolls, operating statements and appraisals.
- Steps:
  1. **Upload**: add files and check each file's detected type. Click **Continue**.
  2. **Check**: review sections "Please check" (low confidence), "Read with high confidence", "Left out" and "Documents disagree", plus the "Rent roll" grid. Use **Use** or ✕ to keep or drop items. Click **Build model**.
  3. **Create**: confirm Key inputs, Lease terms and "When leases expire" (Market rent, Rent growth, Renewal chance, Downtime; **Add assumptions**). Optionally **Edit details**. Click **Create valuation**.

**From Excel** (More ▾ → **Import from Excel**, or Import ▾ → From Excel workbook):
- Accepts .xlsx/.xlsm up to 25 MB.
- Use **Download template** for the expected layout. Workbooks exported from published DCF software and plain sheets with one header row also work.
- Click **Preview import**, then **Import**.
- Sheets it reads: property, leases, rent schedules, market leasing, expenses, other income, capex, vacancy, credit loss, inflation, valuation, multifamily/unit mix, storage, assumption profiles, loans and loan tape.

**From OpenDCF package**: imports a .odcf.zip deal package or a .odcf.json package exported from OpenDCF. It creates a new property and a draft valuation and does not overwrite existing data. The documents and facts come with it, with their review status. A .odcf.json package lists its documents without their files: the facts still show their source, and uploading the same file to the valuation later restores it.

## 15. Assumptions library

**Portfolio → Assumptions library**:
- Profiles by **Property Type**, **Census market (CBSA)** and **Quality**, with State and Market name. Each holds valuation, market leasing and growth values and ranges.
- Buttons: **House defaults → Edit**, **Quality directions**, **Download template**, **Export library**, **Import**, **New Profile**.

Matching order: CBSA + type + quality, then CBSA + type, then state + type, then type, then house default. Set a property's CBSA and Quality under **Edit details**.

There is no button to apply a profile to a single property. The library is used in two places:
- It seeds capital reserves on new valuations.
- It feeds fund runs.

## 16. Self storage

- A self storage property can be valued from a **unit mix** instead of suites and leases.
  - On the **Unit Mix** tab, click **Set up unit mix** (later **Edit unit mix**).
  - If it still has a rent roll, click **Convert rent roll to a unit mix**.
- Unit mix columns:
  - Unit type, SF each.
  - Climate, Access (Interior / Drive-up / Parking).
  - Units, Occupied.
  - In-place $/mo, Street $/mo.
  - Stabilized: blank keeps today's occupancy.
- **Revenue assumptions → Edit**:
  - Street rate growth / yr; Move-outs / month; Growth by year (Year 1, Year 2, …).
  - **Raise rates on existing customers** (existing-customer rate increases): First increase after (months), Then every (months), Increase, Extra move-outs on increase.
  - Discount off first month; Credit loss.
  - "Lease-up: most units gained per month" (blank = already stabilized).
- **Ancillary income → Edit**: Line, Basis, Amount, Participation, Growth / yr.
  - Basis options: "$ per occupied unit / month", "$ per move-in", "% of rental income" (Amount as a fraction), "$ per year".
- After a run, "Year 1 rental build" and "By year" tables appear.

## 17. Marina

- **Slip Inventory → Add Slip Class**:
  - Class Name; Kind (Wet Slip / Dry Stack / Mooring); Slip Count; Length Class; Utility Service.
  - Contract Mix: Annual / Seasonal / Transient Share, which must sum to 1.0.
  - Rates: Annual ($/yr), Seasonal ($/season), Transient ($/day).
  - Occupancy and transient capture.
  - Per-slip ancillary fees.
- **Demand & Growth Assumptions → Edit**:
  - Churn, seasonal replacement, waitlist.
  - Rent growth by contract type, ancillary growth.
  - V&C Loss %, Management Fee %.
- **Operations** tab: **Add Revenue**, **Add Line** (operating expense), **Add Cyclical Cost**, **Add CapEx Item**, plus Legal tenure (fee simple / leasehold, submerged land lease, ground lease) and Fuel dock.

## 18. Seniors housing

- **Unit Mix → Edit unit mix**:
  - Name; Acuity (Independent Living, Assisted Living, Memory Care, Skilled Nursing); Unit Type.
  - Units, Avg SF.
  - Base Fee $/mo, Community Fee $.
  - Stab. Occ., Turnover/yr.
  - 2nd Person %, 2nd Person $/mo.
- **Edit expenses**: Name, Category, Fixed $/yr, $/Occ. Unit/mo, % of Revenue, Growth %.
- Shown but not editable in the app:
  - Care-level tiers.
  - SNF Payer Mix.
  - Ancillary revenue and capex.
  - Occupancy ramp.
  - The Valuation Assumptions card (fee and expense growth, discount rate, exit cap, hold).

## 19. Funds (portfolio)

- **Portfolio → Funds → New Fund** (Name, Description, Properties).
- On the fund page:
  - **Add Properties**.
  - **Ownership** per property: Effective Ownership (%), dates, acquisition cost, commitment.
  - **View** shows the resolved assumptions.
- **New Scenario**:
  - Name, Description, Probability (%).
  - Rules that **Shift** or **Set** assumptions, by Property Type and Market.
- Running a fund:
  - Choose "Live: latest valuations, current inputs", "Approved as of …", or "Approved as of another date…", then click **Run Portfolio**.
  - Results show value (ownership share), vs Base, Yr 1 NOI, Implied Cap and Portfolio XIRR, broken down by property type, market and property.
  - **Disposition Sensitivity** tests selling properties on given dates and prices.
- **Cash flow rollup** sums cash flows across properties.

## 20. Lending

- **Loan book → New Loan**, or a property's **More → Loans** tab.
- Loan fields:
  - Collateral Property, Loan ID, Fund, Lien Position, Sponsor / Borrower, Recourse.
  - Dates, Original Balance.
  - Rate Type, Coupon or Spread, Index Floor/Cap.
  - Amortization (blank = interest only), Interest-Only Months, extensions.
  - **Loan Tape**: Reported Balance, Balance As Of, Delinquency, Value at Origination.
  - **Tape Collateral**: NOI, value, growth and exit cap. Used when the property has no full model.
- Loan pages show LTV/DSCR, PD, LGD and expected loss.
- **Risk runs**: name, as-of date, loans (whole book or a fund), **Run Simulation**. Results include loss VaR, weighted PD/LGD and the top 10 loans by expected loss.
- **Risk settings** (Risk Admin) holds model parameters and **Load Live Rates (FRED)**.
- Collateral Monte Carlo: valuation page **Monte Carlo** section → Paths → **Run Monte Carlo**. Not offered for marina, seniors housing or unit-mix storage.

## 21. Sales comparables

- **More → Sales Comparables**: **Add Comparable Sale**, **Edit Subject Amenities**, **Select** / **Edit Selection** (weight, include, adjustments, rationale).
- **Run Statistical Model** gives a statistical value and a 95% prediction range.

## Common "how do I…" answers

- Free rent up front: Free rent & recovery overrides → Free Rent Periods → Add (section 4).
- Rent bumps of 3% a year: Escalation Type Pct Annual, Annual Escalation % = 3.
- Specific step-ups (e.g. $30 then $32): Escalation Type Fixed Step, then Rent schedule → Add Rent Step.
- Gross lease with a base year: Recovery Type Base Year Stop, set Base Year.
- Tax-only recoveries: Expense Recovery Overrides per category, with Recovery Type None on the categories the tenant doesn't pay.
- CAM capped at 5% a year: Expense Recovery Override for CAM with Cap Group "CAM" and Cap Growth %/yr 5 (a growth cap needs a Cap Group).
- Tenant known to leave: Upon Expiration = Vacate. **Tenant known to stay**: Renew. **Fixed renewal option**: Contract Option.
- Space stays dark after expiry: Upon Expiration = "Reabsorb (stays vacant)".
- Vacant suite leasing up in 9 months: Suite → Lease-Up (vacant space) → Lease-Up Months.
- Management fee as % of income: expense with % of EGI.
- Lower rent for renewals: Market profile Renewal Rent Adjustment, or a lease's Renewal Rent Adjustment (%).
- Different vacancy for retail vs office: General Vacancy % on each space type's market profile.
- Compare two cases: Copy valuation and model, or use What if… for a quick unsaved test.
- IRR missing: enter a Purchase Price on the valuation.
