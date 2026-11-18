# OpenDCF valuation research gap analysis

**Research date:** 2026-11-14  
**Scope:** Income-producing U.S. commercial real estate, with emphasis on institutional valuation, investment analysis, and lending. This review compares OpenDCF's current implementation with recent peer-reviewed research, foundational academic work still shaping current methods, and current RICS/IVS professional standards.

## Executive conclusion

OpenDCF is not missing the core mechanics of a modern lease-by-lease DCF. It already handles monthly lease cash flows, contractual and market rent, probability-weighted rollover, downtime, recoveries, vacancy and credit loss, TI/LC, concessions, expenses, capital projects, forward NOI reversion, transfer taxes, debt, returns, sensitivity grids, portfolio scenarios, and full-property Monte Carlo. Its exact reconciliation to ten published appraisal DCFs is unusually strong evidence of computational correctness.

The largest gaps are upstream and downstream of the deterministic DCF:

1. **Market calibration and triangulation.** Discount rates, cap rates, rents, growth, vacancy, and rollover assumptions remain predominantly user-entered rather than estimated from transactions and market time series. OpenDCF also lacks sales-comparison and cost-approach cross-checks.
2. **Risk-consistent stochastic valuation.** The Monte Carlo engine is valuable for risk analysis, but it holds the discount rate fixed, shocks only the terminal cap rate, relies on normal innovations and static correlations, and ships with starting-point parameters that are not a documented property-type/market/vintage calibration. It should not yet be presented as a market-value estimator.
3. **Climate, resilience, energy, and transition cash flows.** There is no structured hazard, insurance, energy-performance, retrofit, regulatory-obsolescence, or business-interruption model.
4. **Empirical appraisal-bias challenger.** Recent CRE research shows that interpretable hybrid econometric/ML models can identify structured appraisal error. OpenDCF has no comparable-sales or AVM challenger, spatial features, confidence interval, or backtest loop.
5. **Tenant and lease event risk.** Renewal is a fixed probability and credit loss is an aggregate percentage. There is no tenant hazard/default model, recovery timing, correlation by industry/parent, or option-exercise model.
6. **Valuation governance.** Input provenance, model versions, and audit logs exist, but the product does not yet expose a complete IVS-style evidence hierarchy, data-quality score, assumption staleness, model limitation statement, backtest record, reviewer sign-off, or valuation uncertainty conclusion.

The recommended strategy is to retain the transparent lease-level DCF as the primary model and surround it with calibrated market evidence, explicit uncertainty, and independent challenger models. The academic evidence does **not** support replacing the DCF with a black-box AVM.

## What OpenDCF already does well

- Explicit monthly lease projection and annual/monthly discounting.
- Contract rent, fixed steps, percentage escalations, CPI floors/caps, free rent, percentage rent, and renewal options.
- Suite-level market leasing, renewal/new-tenant branches, downtime, TI, LC, concessions, and repeated rollover.
- Detailed expense recovery structures, caps, floors, stops, gross-up, occupancy-variable expenses, and management fees.
- General vacancy, credit loss, absorption, other income, capital projects, capital reserves, and stabilized terminal adjustments.
- Forward-year NOI reversion with exit costs, transfer tax, and optional forward capital deduction.
- Unlevered and levered returns, loan amortization, DSCR, debt yield, LTV, direct cap, and rate/cap sensitivity.
- Portfolio assumption profiles and deterministic downside scenarios.
- A full-property Monte Carlo with persistent correlated drivers, shared macro/market/property shocks, recession regimes, rent-level reversion, path percentiles, and driver sensitivities.
- Exact-value regression tests against public appraisal reports, plus a broad automated test suite.

This is closely aligned with the structural view of a property as a portfolio of long-duration leases exposed to market-rent, vacancy, cost, and supply risk in Gupta, Mittal, and Van Nieuwerburgh's office valuation model. Their model explicitly treats stochastic discounting as well as revenues and costs, however, which is one of OpenDCF's remaining gaps ([NBER working paper](https://www.nber.org/papers/w30526)).

## Prioritized recommendations

### P0 — Correct the interpretation and presentation of existing risk outputs

#### 1. Separate three different valuation concepts

Every run should identify its basis and method:

- **Deterministic market-value DCF:** market-participant cash flows and a market-derived discount rate.
- **Investment value:** owner/investor-specific cash flows, financing, tax, or hurdle rate.
- **Risk distribution / stress result:** path distribution around a base valuation, not automatically a probability distribution of market value.

The current Monte Carlo discounts all paths at one fixed user-entered rate. Its mean or median NPV therefore should not be described as a theoretically risk-adjusted value. Expected cash flows and compensation for systematic risk are separate concepts; the stochastic discount factor framework explicitly prices their covariance. The structural CRE model in the NBER paper does this directly, while older and current asset-pricing research finds discount-rate shocks central to CRE price-rent variation ([Miao, Wang, and Zha](https://www.nber.org/papers/w20377)).

**Implementation:** add `basis_of_value`, `intended_use`, `cash_flow_type` (`most_likely`, `scenario_weighted_expected`, `contractual`), and `risk_treatment` metadata. Label Monte Carlo summaries “scenario distribution at the selected discount rate.” Do not silently treat the distribution mean as market value.

#### 2. Eliminate double counting between cash-flow risk and rates

Provide a reconciliation panel showing where each material risk is reflected:

- cash-flow level or scenario probability;
- discount-rate premium;
- exit-cap adjustment;
- separate deduction/reserve.

The user should be warned when the same risk appears in more than one channel—for example, climate risk in insurance/capex, rent growth, discount rate, and exit cap. RICS states that DCF does not remove the need for market evidence and that sustainability factors may be modeled explicitly, but adjustments need an empirical basis for market value ([RICS DCF guidance](https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/discounted-cash-flow-valuation), [RICS ESG guidance](https://www.rics.org/content/dam/ricsglobal/documents/standards/january2022_sustainability_and_esg_guidance_note.pdf)).

### P1 — Build a market-evidence and calibration layer

#### 3. Add comparable-sales and implied-input calibration

For each relevant transaction, store location, property type/subtype, quality, size, age/renovation, occupancy, WALT, NOI definition, price, cap rate, financing/distress flags, sale date, and source. Calculate:

- adjusted price/SF or price/unit;
- going-in cap rate on a normalized NOI definition;
- implied discount rate and implied NOI/rent growth where supported;
- time, location, quality, occupancy, lease-duration, and condition adjustments;
- transaction inclusion/exclusion rationale and evidence weight.

Then reconcile DCF, direct cap, and sales comparison. Add a cost/replacement-cost check for newer, special-purpose, redevelopment, and insurance-related assignments.

This is the most important product gap. The 2025 IVS framework emphasizes relevant observable data, input selection, documentation, and professional skepticism ([IVSC standards](https://ivsc.org/standards/)). RICS likewise says discount rates should be based on market evidence. Recent international evidence shows that office cap rates vary with real rates, discount rates, vacancy, wealth, gateway/financial-center status, sovereign credit/inflation, CBD/suburban location, and transit access—not just property type ([Duca, Hoesli, and Montezuma, 2023](https://onlinelibrary.wiley.com/doi/10.1111/1540-6229.12424)).

#### 4. Estimate a cap-rate/discount-rate term structure, not one timeless scalar

Add an optional market-calibrated required-return model:

`risk-free term structure + CRE market premium + property/lease/location adjustments`.

Support year-specific discount rates and a jointly consistent exit cap. At minimum, expose a bridge from Treasury/real-rate curves to the selected discount and cap rates. Preserve the user override, but record its source and difference from the model indication.

A December 2024 U.S. study uses 2002–2024 appraisal data across more than 60 metros to analyze discount rates, cap rates, and implied NOI growth and explicitly desmooths appraisal series before estimation ([Hoesli and Shmygel working paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5042256)). Treat it as useful recent evidence, but below peer-reviewed work in the evidence hierarchy until publication.

#### 5. Add calibration, backtesting, and uncertainty metrics

Store valuation snapshots and subsequent sales. Report, by model version/property type/market/vintage:

- signed percentage error and median error;
- MAE, MdAE, MAPE, RMSE, and log error;
- percentage within 5%, 10%, and 20%;
- calibration of 50%/80%/95% prediction intervals;
- error by value decile, liquidity, geography, and market regime;
- appraisal lag and stale-input flags.

Published evidence finds appraisal error is structured and cyclically lagged, rather than random. An interpretable boosting model using 7,133 NCREIF properties reduced error dispersion and structural bias, with spatial and structural variables explaining most of the captured variation ([Deppner et al., 2025](https://link.springer.com/article/10.1007/s11146-023-09944-1)).

### P1 — Upgrade stochastic methodology

#### 6. Calibrate risk parameters to data and preserve parameter uncertainty

The current parameter defaults are explicitly described in code as a starting point. Replace a single universal preset with versioned calibrations by property type, metro/market tier, and observation window. Estimate volatility, persistence, cross-driver dependence, recession transitions, and rent-level reversion from transparent time series. Retain posterior or bootstrap uncertainty in the calibrated parameters.

Recommended output:

- historical estimation sample and transformations;
- parameter estimate, standard error/credible interval, and last calibration date;
- out-of-sample diagnostics;
- base calibration versus lender overlays;
- sensitivity to calibration vintage.

#### 7. Add fat tails and regime-dependent dependence

Normal shocks with a single correlation matrix understate joint extremes. Add selectable Student-t or empirical/bootstrap innovations, regime-specific correlations, and explicit event scenarios. Report VaR and expected shortfall only with clear caveats and enough paths. For portfolios, preserve common shocks and add tenant/industry/geographic concentration.

#### 8. Make discount rates and cap rates jointly dynamic

Currently, cash-flow drivers and the exit cap move, but the annual discount rate does not. Add either:

- a transparent state-dependent required-return path tied to real rates, inflation, credit/liquidity conditions, property type, vacancy, and location; or
- an advanced stochastic discount-factor module for research/institutional use.

Avoid independently shocking discount and cap rates. Estimate their joint behavior with expected growth and enforce an explainable identity/bridge. Discount-rate shocks are a major driver of CRE prices ([Miao, Wang, and Zha](https://www.nber.org/papers/w20377)); international cap-rate evidence also links cap rates to discount rates and vacancy ([Duca, Hoesli, and Montezuma](https://onlinelibrary.wiley.com/doi/10.1111/1540-6229.12424)).

#### 9. Add variance decomposition and decision-focused risk measures

The existing correlation-based sensitivity ranking is useful but not causal and can be misleading with correlated nonlinear inputs. Add:

- Sobol/Shapley effects or grouped variance decomposition;
- probability of negative NPV at purchase price;
- probability of breaching DSCR/LTV/debt-yield thresholds by year;
- expected shortfall of value and equity;
- probability-weighted refinance gap and required equity cure;
- terminal-value share of total value and its distribution.

### P1 — Add climate, resilience, and transition cash flows

#### 10. Create a hazard-to-cash-flow framework

Do not implement a generic “ESG cap-rate premium” field. Model observable channels:

- hazard exposure and vulnerability (flood, wind, wildfire, heat, water);
- annual expected damage and event downtime;
- insurance premium, deductible, coverage limit, exclusions, and availability;
- repair/adaptation capex and timing;
- operating-cost effects, especially energy and water;
- tenant demand/rent/occupancy impacts;
- regulation-driven retrofit and stranding risk;
- residual/exit liquidity and cap-rate effect, with double-count checks.

CRE exposed to flood risk after Hurricane Sandy traded at persistent discounts driven by cap rates rather than occupancy ([Addoum et al., 2023](https://onlinelibrary.wiley.com/doi/10.1111/1540-6229.12435)). Newer evidence also finds risk repricing can spill over to undamaged nearby properties, again through cap rates rather than occupancy ([2026 Real Estate Economics study](https://onlinelibrary.wiley.com/doi/full/10.1111/1540-6229.70034)). This directly argues for both physical cash-flow channels and a market-risk/liquidity channel.

RICS's fourth-edition ESG and sustainability standard became effective 30 April 2026 and applies sustainability considerations when material ([RICS announcement](https://www.rics.org/news-insights/rics-publishes-updated-global-standard-esg-sustainability-commercial-property-valuation)).

#### 11. Capture energy and building-quality state

Add energy rating/certification, energy use intensity, emissions intensity, building systems, last major renovation, remaining useful life, deferred maintenance, and planned retrofit. These should affect expenses, capex, rent/occupancy only where market-supported. Research reviews find energy efficiency is generally associated with price premiums and warn that omitting changing building quality biases price indexes ([2026 Review of Income and Wealth survey](https://onlinelibrary.wiley.com/doi/10.1111/roiw.70055)).

### P2 — Add tenant and lease-event models

#### 12. Replace fixed renewal probability with optional hazard models

Retain manual renewal assumptions, but allow a calibrated tenant/lease survival model using:

- tenant credit and parent support;
- industry and local employment exposure;
- rent-to-market spread;
- remaining term, options, contraction/expansion rights, and space criticality;
- tenant investment in place and moving cost;
- building quality, amenities, energy performance, and location;
- market vacancy, sublease availability, and remote-work exposure.

Generate renewal, contraction, expansion, default, and early-termination events rather than only expiry renewal/vacate branches. Model tenant default timing, lost rent, legal/recovery cost, downtime, security deposit/guaranty recovery, and correlation among related tenants.

The post-pandemic office valuation literature shows tenant remote-work exposure predicts leased-space contraction and motivates explicit long-lease, market-rent, vacancy, cost, and supply state variables ([Gupta, Mittal, and Van Nieuwerburgh](https://www.nber.org/papers/w30526)).

#### 13. Add real options and highest-and-best-use analysis

For materially optional assets, add discrete scenarios for renovation, conversion, expansion, demolition/redevelopment, phased lease-up, and sale timing. Use decision trees or least-squares Monte Carlo only when decisions can adapt to future states; otherwise transparent scenario-weighted DCF is preferable. Include entitlement probability, time, carrying cost, construction-cost uncertainty, and residual land value.

### P2 — Add an interpretable market-value challenger

#### 14. Build a hybrid econometric/ML AVM, not a black box

Recommended architecture:

- hierarchical/random-effects time, property-type, metro, submarket, and repeat-sale components;
- nonlinear boosted-tree residual model for property, lease, and spatial characteristics;
- time-based and geography-based cross-validation;
- conformal or quantile prediction intervals;
- comparable retrieval and local explanations;
- strict separation between model indication and final professional conclusion.

A 2024 *Real Estate Economics* paper combining random effects with ML achieved below 11% out-of-sample MAPE on 2,652 Phoenix CRE transactions and produced indexes and locational heat maps ([Francke and van de Minne](https://onlinelibrary.wiley.com/doi/10.1111/1540-6229.12483)). A related ML price-index method improved accuracy but was less stable in small samples and could be biased, which supports explicit sample-size and drift controls ([Calainho, van de Minne, and Francke](https://doi.org/10.1007/s11146-022-09893-1)).

The AVM should challenge and contextualize the DCF, never silently overwrite it. IVSC's current position emphasizes governance, data/input controls, model selection, transparency, quality control, and professional judgment ([IVSC AI paper](https://ivsc.org/navigating-the-rise-of-ai-in-valuation-opportunities-risks-and-standards/)).

### P2 — Complete valuation governance

#### 15. Implement an IVS-style valuation record

Add to every material input:

- source, observation date, effective date, geography, and definition;
- direct observation / derived / proxy / judgment classification;
- transformation and adjustment history;
- preparer, reviewer, and approval state;
- confidence/evidence weight and staleness rule;
- links to supporting comps/documents.

Add a model card documenting intended use, excluded uses, methodology, calibration population, known limitations, validation results, and change history. Add automated reasonableness tests and reviewer challenge notes. IVS 2025 added explicit Data & Inputs, Valuation Models, and Documentation & Reporting standards ([IVSC 2025 overview](https://ivsc.org/new-edition-of-the-international-valuation-standards-ivs-published/)). IVSC also distinguishes process-related valuation risk from uncertainty in the value itself ([IVSC valuation-risk paper](https://ivsc.org/valuation_risk/)).

#### 16. Report a value range and uncertainty narrative

Alongside the point estimate, report:

- DCF/direct-cap/sales-comparison indications and reconciliation weights;
- sensitivity range from market-supported assumptions;
- stochastic range separately, with calibration basis;
- key uncertainty drivers and data limitations;
- model risk and evidence-quality assessment;
- conditions under which the conclusion should be revisited.

Do not convert a sensitivity table into a statistical confidence interval unless its probabilities are calibrated and validated.

## Specific implementation issues to correct

1. **Discount-rate stasis in Monte Carlo.** `path_case` makes the exit cap stochastic but leaves `ValuationParams.discount_rate` unchanged. Add a documented risk-treatment choice before adding dynamic rates.
2. **Normal/static dependence.** The driver generator uses multivariate normal shocks and one Cholesky correlation matrix. Add fat-tail and regime-dependent alternatives.
3. **Universal defaults.** Risk defaults are described as starting points. Prevent production presentation without a calibration label and “illustrative/unvalidated” warning.
4. **Correlation sensitivity is not importance.** The current driver ranking uses correlation with value. Rename it “association” and later add a nonlinear variance-decomposition measure.
5. **Terminal sensitivity timing.** The sensitivity grid discounts the terminal value using the same mid-year offset as operating cash flow. A sale normally occurs at the end of the terminal period even when operating cash flow uses mid-year timing. Preserve the existing convention for published-appraisal parity, but add a separate explicit `terminal_timing` setting and default new analyses to end-of-period sale timing.
6. **IRR robustness.** Newton-Raphson IRR can miss or select among multiple roots. Add XIRR/date-based calculation, root bracketing, multiple-IRR detection, and MIRR when cash flows change sign more than once.
7. **Nominal/real consistency.** Add explicit nominal/real flags for cash flows, growth, discount rates, and debt rates, with validation preventing mixed bases.
8. **Tax and ownership scope.** Make clear that current returns are generally pre-income-tax asset/equity returns. Add optional entity/investor tax only as a separate investment-value module, not market value.
9. **NOI normalization.** Define NOI consistently across direct cap, comps, debt metrics, and terminal value. Record whether reserves, TI/LC, management fees, and nonrecurring items are above or below NOI.
10. **Probability semantics.** Distinguish probability-weighted expected cash flows from a simulated mutually exclusive path. The current deterministic probability tree is an expected-cash-flow technique; it is not itself a distribution of lease outcomes.

## Suggested delivery sequence

### Phase 1 — defensibility and quick wins

1. Basis-of-value and risk-treatment metadata.
2. Input provenance, staleness, evidence-quality, and model-card fields.
3. Monte Carlo labels/warnings; rename correlation sensitivity.
4. Separate terminal timing; robust XIRR/multiple-root diagnostics; nominal/real validation.
5. Comparable-sales schema and manual reconciliation screen.

### Phase 2 — empirical market calibration

1. Comparable ingestion and normalized cap-rate/rent evidence.
2. Market-derived rate bridge and joint cap/growth/discount consistency checks.
3. Snapshot/backtest store and error dashboards.
4. Versioned property-type/market stochastic calibrations.
5. Fat-tail, regime-dependent, and tenant concentration risk.

### Phase 3 — differentiated research-grade features

1. Climate/resilience/insurance/transition cash-flow module.
2. Tenant default and renewal hazard models.
3. Hybrid econometric/ML challenger with prediction intervals and comparable retrieval.
4. Real-options/highest-and-best-use module.
5. Advanced stochastic discount-factor valuation for users who need an asset-pricing-consistent research model.

## Bottom line

OpenDCF's lease-level engine is already ahead of many practical DCF implementations. The next competitive leap is not more line-item mechanics. It is a defensible evidence system around the engine: market-derived inputs, calibrated uncertainty, climate and tenant event channels, independent transaction-based challenge, and standards-grade governance. Those additions would make the platform more accurate, more auditable, and much harder to misuse.
