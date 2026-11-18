# UI Polish Plan (web app only)

Status: built and merged (uncommitted), 2026-11-14. The desktop (Tauri) app is out of scope; only the locally run web app matters.

Source: review of award-winning and widely cited interfaces (Oura 2026 Webby Best UI, Linear, Stripe, Mercury)
against OpenDCF. Principles: lead with the answer, statement-grade money tables, dense pro layout,
keyboard path to everything, color only for meaning, instant feedback.

## Workstreams (run in parallel, each in its own git worktree)

Each workstream owns specific code. New CSS goes in its own file `frontend/css/<ws>.css`; new JS in its own
file. Do not edit `frontend/index.html` (links are added at merge). Do not rename existing CSS variables or
shared helpers; add new ones instead.

### WS1 Foundation: tokens, color, accessibility, dark mode
Owns: `:root` variables in `frontend/style.css`, type/status badge styles, `showFormModal` / modal focus
handling, global focus ring.
- Neutral property-type badges; color only for status (Current, Needs re-run, Failed, Draft).
- Text tokens pass WCAG AA 4.5:1 on their backgrounds (fix faint grays).
- Dialogs trap focus, Esc closes, focus returns to the opener.
- Visible, consistent `:focus-visible` ring on all controls.
- Dark theme: `prefers-color-scheme` plus a manual toggle (`data-theme` on `<html>`), remembered in
  localStorage; charts read colors from tokens.
- Density tokens on a 4px grid: `--row-h-compact: 34px`, 13px table text.
Done when: contrast check script passes; every route renders in both themes; Tab cannot leave an open dialog.

### WS2 Property workspace tables
Owns: `renderRentRollTab` and its wiring, other property-page tables (expenses, market, capital, recovery),
`tenantsView`, home table.
- Rows ~34px, tabular figures, right-aligned numbers, units in headers not cells, sticky header and first column.
- Per-row actions move into a "⋯" menu (no hover-only actions).
- Inline editing in the rent roll for rent, start, end, tenant name (Enter saves, Esc cancels, saves via
  existing PUT endpoints, marks valuations stale like any edit).
Done when: rent roll edit inline updates the API value; tables render on seed properties with no console errors.

### WS3 Valuation page
Owns: `valuationView` and its helpers/charts, valuation cash-flow tables, valuation reports UI.
Backend: `GET /api/v1/valuations/{id}/reports/what-if?discount_rate=&exit_cap_rate=` reprices the last
completed run's cash flows (same math as the sensitivity matrix; no save, no re-run), with tests.
- Lead: value as headline with one sentence ("$13.6M ($221/SF) at 10.00% discount and 8.00% exit cap,
  10-year hold"), then supporting metrics smaller.
- One cash-flow chart with a NOI / cash flow toggle, replacing the two near-identical charts.
- Statement-grade cash-flow table: negatives in parentheses, subtotal rules (EGI, NOI, CFBD), sticky label
  column and year header.
- What-if: discount and exit cap sliders update value live (debounced) beside the sensitivity grid; "Save as
  scenario" duplicates the valuation with those rates; clear "not saved" labeling.
Done when: what-if at the saved rates equals the stored NPV to the cent (test); sliders change the value.

### WS4 Command palette
Owns: new `frontend/palette.js`, new `frontend/css/palette.css`, backend `GET /api/v1/search?q=`.
- Cmd/Ctrl+K opens; fuzzy search properties, valuations, tenants; actions (New property, New valuation on the
  current property, Re-run current valuation, Export, Toggle theme, Go to Portfolio / Lending).
- Arrow keys + Enter; shortcut hints; works from every route; `?` lists shortcuts.
Done when: API test for search; palette opens and navigates (verified at merge).

### WS5 Speed
Owns: data loading at the top of `propertyView` (before rendering), new backend
`GET /api/v1/properties/{id}/workspace` returning property, leases, expenses, other income, market profiles,
capital projects, recovery structures, valuations, readiness in one response; skeleton loading styles.
- Property page uses the one endpoint; Comparables and Loans tabs load when opened.
- Skeleton placeholders instead of spinners on home, property and valuation pages.
- Measure before/after on a large property (seed DB and a 200-suite generated property).
Done when: API test for the workspace endpoint; property page makes 1 request for its main data; timing noted.

## Merge
Integrator applies each worktree diff to the main tree (3-way), adds CSS/JS links to `index.html`, resolves
overlaps, runs full pytest, then browser-checks every route in light and dark themes.

## Shared contract (in the base tree before workstreams start)
- CSS variables: existing `:root` names plus `--surface-raised`, `--text-table`, `--row-h-compact`,
  `--num-font-features`, `--skeleton-base`, `--skeleton-shine`, `--chart-1..3`, `--chart-grid`, `--chart-text`.
  No hard-coded colors in new CSS or JS (charts read tokens via `getComputedStyle`).
- Theme: `<html data-theme="light|dark">`; WS1 defines `window.setTheme(mode)` with mode `light|dark|system`
  and `window.getTheme()`. Others call `window.setTheme?.(...)`.
- Skeletons: WS5 defines `.skeleton`, `.skeleton-line`, `.skeleton-block`, `.skeleton-row`; WS3 uses them.
- Shortcuts registry: WS4 defines `window.registerShortcut(key, label, handler)`; others may call it if present.
- Ownership in `propertyView`: WS5 = data loading and tab switching; WS2 = table renderers and their row wiring.
- Integrator only: `index.html`, `src/main.py` router registration. No migrations. New tests in new files.
