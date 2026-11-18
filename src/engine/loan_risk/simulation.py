"""
Monte Carlo default and loss simulation for a book of commercial mortgage loans.

Collateral paths come from collateral Monte Carlo (src.engine.collateral_mc):
for a property with a full model, each path's monthly NOI is a complete
valuation with that path's rent growth, vacancy, renewals, downtime,
concessions and expense inflation. Tape-only collateral uses the same
simulated drivers in reduced form (NOI = revenue - expenses, with revenue
moved by rent growth and vacancy and expenses by inflation). On every path:

- Cap rate = calibrated going-in cap + the path's cap rate deviation, so
  value in month t = forward 12-month NOI / cap rate in month t.
- SOFR = forward curve + the path's SOFR deviation (floating coupons and
  floating-rate refinancing); 10-year Treasury = its curve + deviation
  (fixed-rate refinancing). Both are economy-wide and correlated with cap
  rates and inflation.

Defaults (all loans on a property default together; recoveries are paid by
lien priority):
- Term default: at each quarter end a path defaults with probability set by
  a logistic function of its DSCR and LTV (as in Moody's CMM), drawn from
  the property's own random stream.
- At maturity the loan refinances if the largest new loan (by LTV, DSCR at
  the refinance rate and debt yield, after senior debt) covers it; the sponsor
  can pay down a shortfall up to `max_equity_paydown_pct` of value; otherwise
  it extends (if an option remains and its tests are met), or the borrower
  sells if the sale (net of `sale_cost_pct`) repays all debt on the property,
  or it defaults.
- Loans already 90+ days delinquent or in foreclosure start in default.

Loss = balance at default + advanced interest + workout and carrying costs - (liquidation value
net of selling costs + NOI collected during the workout), allocated senior first. Lender cash flows
on each path are discounted at the index forward curve plus a spread to give
the expected-cash-flow fair value.

Simulation arithmetic uses numpy float64; contractual schedules come in from
the Decimal schedule engine.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np

from src.engine.collateral_mc import (
    CAP,
    IDX,
    MAX_YEARS,
    deviations,
    driver_shocks,
    monthly,
    property_deviations,
)
from src.engine.loan_risk.params import RiskParameters
from src.engine.loan_risk.schedule import LoanState, LoanTerms, ScheduleRow

DEFAULTED_STATUSES = {"90_plus", "foreclosure", "reo"}
KIND_NONE, KIND_TERM, KIND_MATURITY, KIND_EXISTING = 0, 1, 2, 3
PERCENTILES = (5, 25, 50, 75, 95)


@dataclass
class CollateralInput:
    key: str                           # property id (names the property's random streams)
    property_type: str
    monthly_noi: np.ndarray            # base-case NOI for months 1..M after the as-of date
    current_value: float
    market: str | None = None
    exit_cap_rate: float | None = None  # base cap rate for future values (None = going-in cap)
    noi_paths: np.ndarray | None = None  # simulated NOI, paths x months (None = tape reduced form)
    trailing_noi: float | None = None  # last 12 months' NOI at the as-of date


@dataclass
class LoanInput:
    loan_id: str
    collateral_key: str
    balance: float                     # balance at the as-of date
    begin_balance: np.ndarray          # contractual balance at the start of months 1..n
    principal: np.ndarray              # scheduled amortization in months 1..n (balloon excluded)
    rate_type: str = "fixed"
    coupon: float = 0.0
    spread: float = 0.0
    index_floor: float | None = None
    index_cap: float | None = None
    lien_position: int = 1
    extension_count: int = 0
    extension_months: int = 0
    delinquency_status: str = "current"

    @property
    def term_months(self) -> int:
        return len(self.begin_balance)

    @property
    def balloon(self) -> float:
        return float(self.begin_balance[-1] - self.principal[-1]) if self.term_months else 0.0


@dataclass
class LoanRiskResult:
    loan_id: str
    balance: float
    pd_cumulative: float
    pd_term: float
    pd_maturity: float
    pd_one_year: float
    pd_annualized: float
    pd_by_year: list[float]            # cumulative default probability at each year end
    lgd: float | None                  # mean loss / balance at default, given default
    expected_loss: float               # mean loss / current balance
    expected_loss_amount: float
    loss_percentiles: dict[str, float]  # p95 / p99 / p999 of loss as % of balance
    fair_value: float
    fair_value_price: float            # fair value / current balance
    value_percentiles: dict[str, list[float]]  # collateral value fan by year (incl. year 0)
    losses: np.ndarray                 # loss on each path ($), for portfolio aggregation


@dataclass
class PortfolioLossResult:
    total_balance: float
    expected_loss_amount: float
    expected_loss: float
    loss_std: float
    var: dict[str, float]               # p95 / p99 / p999 loss ($)
    expected_shortfall_99: float
    histogram: dict[str, list[float]]   # bin edges ($) and path counts


def _curve(points: list[list[float]], months: int) -> np.ndarray:
    """Curve rate for months 0..months (linear in years, flat beyond the ends)."""
    pts = sorted(points)
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    return np.interp(np.arange(months + 1) / 12.0, xs, ys)


def default_probability(params: RiskParameters, dscr: np.ndarray, ltv: np.ndarray) -> np.ndarray:
    """Annual probability of term default given DSCR and LTV (logistic, as in Moody's CMM)."""
    x = (params.default_intercept
         + params.default_dscr_coef * np.log(np.clip(dscr, 0.05, 5.0))
         + params.default_ltv_coef * np.clip(ltv, 0.0, 2.0))
    return 1 / (1 + np.exp(-x))


def _default_draws(params: RiskParameters, key: str, paths: int) -> np.ndarray:
    """Uniform draws (paths x quarters) deciding term default, from the property's own stream."""
    gen = np.random.default_rng([params.seed, zlib.crc32(f"default:{key}".encode())])
    return gen.random((paths, 4 * MAX_YEARS))


def _extend(series: np.ndarray, length: int) -> np.ndarray:
    """Pad a monthly series to `length` with its last 12 months' average."""
    if len(series) >= length:
        return series[:length]
    if len(series) == 0:
        return np.zeros(length)
    tail = series[-12:].mean()
    return np.concatenate([series, np.full(length - len(series), tail)])


def _tape_noi_factor(params: RiskParameters, dev: np.ndarray, months: int) -> np.ndarray:
    """
    NOI multiplier (paths x months) for tape-only collateral from the simulated drivers.
    Leases are assumed staggered evenly over tape_avg_lease_years: each year one tranche
    re-leases at that year's market rent and keeps it until it rolls again, so market rent and
    vacancy moves reach revenue gradually, as they do for a property with in-place leases.
    Expenses move with inflation immediately.
    """
    n_years = dev.shape[1] - 1
    term = max(1, int(round(params.tape_avg_lease_years)))
    market = np.concatenate([np.ones((dev.shape[0], 1)),
                             np.cumprod(1 + dev[:, 1:, IDX["rent_growth"]], axis=1)], axis=1)   # year 0..n
    y = np.arange(1, n_years + 1)
    # Year each tranche last re-leased (0 = still on its in-place lease)
    last_roll = np.array([np.where(y >= j + 1, y - (y - 1 - j) % term, 0) for j in range(term)])
    rev = market[:, last_roll].mean(axis=1)                                     # paths x years
    v0 = params.tape_base_vacancy
    rolled = np.minimum(1.0, y / term)
    occ = (1 - np.clip(v0 + rolled * dev[:, 1:, IDX["vacancy"]], 0.0, 0.95)) / (1 - v0)
    exp = np.cumprod(1 + dev[:, 1:, IDX["inflation"]], axis=1)
    r = params.tape_expense_ratio
    factor = (rev * occ - r * exp) / (1 - r)          # paths x years
    years = np.minimum(np.arange(months) // 12 + 1, n_years)
    return factor[:, years - 1]


def _annual_constant(rate: np.ndarray, months: int) -> np.ndarray:
    r = np.maximum(rate, 1e-9) / 12
    return 12 * r / (1 - (1 + r) ** -months)


def simulate(
    collateral: list[CollateralInput],
    loans: list[LoanInput],
    params: RiskParameters,
) -> tuple[list[LoanRiskResult], PortfolioLossResult]:
    by_key = {c.key: c for c in collateral}
    groups: dict[str, list[LoanInput]] = {}
    for loan in loans:
        groups.setdefault(loan.collateral_key, []).append(loan)

    max_lag = max([params.liquidation_lag(c.property_type) for c in collateral] + [0])
    horizon = max([l.term_months + l.extension_count * l.extension_months for l in loans] + [1])
    T = horizon + max_lag + 1   # months simulated (index 0 = as-of date)

    # Economy-wide rates: the same deviations for every property on a path
    macro = deviations(params, driver_shocks(params, "", "", None))
    fwd = _curve(params.index_curve, T)
    index = np.maximum(0.0, fwd + monthly(macro[:, :, IDX["sofr"]], T))
    treasury = np.maximum(0.0, _curve(params.treasury_curve, T) + monthly(macro[:, :, IDX["treasury_10y"]], T))
    df = np.concatenate([[1.0], np.cumprod(1 / (1 + (fwd[1:] + params.fair_value_spread) / 12))])

    results: dict[str, LoanRiskResult] = {}
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda l: l.lien_position)
        for loan, res in zip(group, _simulate_group(by_key[key], group, params, T, index, treasury, df)):
            results[loan.loan_id] = res

    ordered = [results[l.loan_id] for l in loans]
    return ordered, portfolio_losses(ordered)


def _simulate_group(
    col: CollateralInput,
    loans: list[LoanInput],
    params: RiskParameters,
    T: int,
    index: np.ndarray,
    treasury: np.ndarray,
    df: np.ndarray,
) -> list[LoanRiskResult]:
    P = params.num_paths
    dev = property_deviations(params, col.key, col.property_type, col.market)

    # Base-case NOI for months 1..T+12 (flat beyond the projection)
    base = _extend(np.asarray(col.monthly_noi, dtype=float), T + 12)
    if col.noi_paths is not None:
        if col.noi_paths.shape[0] != P:
            raise ValueError("Collateral NOI paths do not match the number of paths")
        paths = np.stack([_extend(row, T + 12) for row in np.asarray(col.noi_paths, dtype=float)])
    else:
        paths = base * _tape_noi_factor(params, dev, T + 12)
    noi = np.zeros((P, T + 1))
    noi[:, 1:] = paths[:, :T]
    cs = np.concatenate([np.zeros((P, 1)), np.cumsum(paths, axis=1)], axis=1)
    fwd_noi = cs[:, 12:T + 13] - cs[:, 0:T + 1]                  # months t+1..t+12

    # Future values capitalize forward NOI at the property's exit cap rate plus the path's cap rate
    # deviation; today's value is the current valuation
    base_cap = col.exit_cap_rate
    if not base_cap:
        base_fwd0 = base[:12].sum()
        base_cap = base_fwd0 / col.current_value if col.current_value > 0 and base_fwd0 > 0 else 0.07
    cap = np.maximum(params.cap_rate_floor, base_cap + monthly(dev[:, :, CAP], T))
    value = np.maximum(fwd_noi, 0.0) / cap
    value[:, 0] = col.current_value

    hist = (col.trailing_noi if col.trailing_noi is not None else base[:12].sum()) / 12
    ext = np.concatenate([np.full((P, 11), hist), noi[:, 1:]], axis=1)       # months -10..T
    cs = np.concatenate([np.zeros((P, 1)), np.cumsum(ext, axis=1)], axis=1)
    ttm = np.zeros((P, T + 1))
    ttm[:, 1:] = cs[:, 12:12 + T] - cs[:, 0:T]
    ttm[:, 0] = hist * 12

    n_loans = len(loans)
    default_month = np.full(P, -1)
    kind = np.zeros(P, dtype=int)
    draws = _default_draws(params, col.key, P)
    mat = np.array([[l.term_months] * P for l in loans])                   # loans x paths
    ext_left = np.array([[l.extension_count] * P for l in loans])
    paid = np.zeros((n_loans, P), dtype=bool)
    pv = np.zeros((n_loans, P))
    bal_at_default = np.zeros((n_loans, P))
    rate_at_default = np.zeros((n_loans, P))

    if any(l.delinquency_status in DEFAULTED_STATUSES for l in loans):
        default_month[:] = 0
        kind[:] = KIND_EXISTING
        for i, l in enumerate(loans):
            bal_at_default[i] = l.balance
            rate_at_default[i] = _loan_rate(l, index[:, 0])

    last = max(l.term_months + l.extension_count * l.extension_months for l in loans)
    for t in range(1, last + 1):
        alive = default_month < 0
        if not alive.any():
            break
        begin = np.zeros((n_loans, P))
        prin = np.zeros((n_loans, P))
        rate = np.zeros((n_loans, P))
        active = np.zeros((n_loans, P), dtype=bool)
        for i, l in enumerate(loans):
            active[i] = alive & ~paid[i] & (t <= mat[i])
            b = l.begin_balance[t - 1] if t <= l.term_months else l.balloon
            begin[i] = b
            prin[i] = l.principal[t - 1] if t <= l.term_months else 0.0
            rate[i] = _loan_rate(l, index[:, t])
        service = np.where(active, begin * rate / 12 + prin, 0.0)
        total_service = service.sum(axis=0)
        total_balance = np.where(active, begin, 0.0).sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            dscr = np.where(total_service > 0, ttm[:, t] / (12 * total_service), np.inf)
            ltv = np.where(value[:, t] > 0, total_balance / value[:, t], np.inf)

        # Term default, drawn at quarter ends from the path's conditional PD
        if t % 3 == 0:
            p_annual = default_probability(params, dscr, ltv)
            p_quarter = 1 - (1 - p_annual) ** 0.25
            hit = alive & active.any(axis=0) & (draws[:, t // 3 - 1] < p_quarter)
            _mark_default(hit, t, KIND_TERM, default_month, kind, active, begin, rate,
                          bal_at_default, rate_at_default)
            alive = default_month < 0

        # Maturity: refinance, extend or default (senior loans first)
        senior_outstanding = np.zeros(P)
        max_refi = {
            kind_: np.minimum.reduce([
                value[:, t] * params.refi_max_ltv,
                np.maximum(fwd_noi[:, t], 0) / (params.refi_min_dscr * _annual_constant(rate_, params.refi_amortization_months)),
                np.maximum(fwd_noi[:, t], 0) / params.refi_min_debt_yield,
            ])
            for kind_, rate_ in (("fixed", treasury[:, t] + params.refi_spread_fixed),
                                 ("floating", index[:, t] + params.refi_spread))
        }
        for i, l in enumerate(loans):
            maturing = alive & active[i] & (t == mat[i])
            if maturing.any():
                owed = begin[i] - prin[i]
                capacity = np.maximum(max_refi["floating" if l.rate_type == "floating" else "fixed"]
                                      - senior_outstanding, 0.0)
                refinanced = capacity >= owed
                paid_down = owed - capacity <= value[:, t] * params.max_equity_paydown_pct
                ok = maturing & (refinanced | paid_down)
                extend = (maturing & ~ok & (ext_left[i] > 0)
                          & (dscr >= params.extension_min_dscr) & (ltv <= params.extension_max_ltv))
                # A borrower who cannot refinance or extend sells if the sale clears all the debt
                sold = (maturing & ~ok & ~extend
                        & (value[:, t] * (1 - params.sale_cost_pct) >= total_balance))
                fail = maturing & ~ok & ~extend & ~sold
                pv[i] += np.where(ok, owed, 0.0) * df[t]
                paid[i] |= ok
                for j in range(n_loans):   # the sale repays every loan on the property
                    repaid = sold & active[j] & ~paid[j]
                    pv[j] += np.where(repaid, begin[j] - prin[j], 0.0) * df[t]
                    paid[j] |= repaid
                mat[i] = np.where(extend, mat[i] + l.extension_months, mat[i])
                ext_left[i] = np.where(extend, ext_left[i] - 1, ext_left[i])
                _mark_default(fail, t, KIND_MATURITY, default_month, kind, active, begin, rate,
                              bal_at_default, rate_at_default)
                alive = default_month < 0
            senior_outstanding += np.where(active[i], begin[i], 0.0)

        # Scheduled payments received on loans still performing
        pv += np.where(active & alive, service, 0.0) * df[t]

    # Recoveries and losses on defaulted paths
    losses = np.zeros((n_loans, P))
    lag = params.liquidation_lag(col.property_type)
    d = default_month >= 0
    if d.any():
        liq = np.minimum(np.where(d, default_month, 0) + lag, T)
        rows = np.arange(P)
        noi_cs = np.cumsum(noi, axis=1)
        workout_noi = noi_cs[rows, liq] - noi_cs[rows, np.where(d, default_month, 0)]
        proceeds = (value[rows, liq] * (1 - params.liquidation_cost_pct)
                    + params.workout_noi_to_lender_pct * workout_noi)
        remaining = np.where(d, np.maximum(proceeds, 0.0), 0.0)
        # Carrying costs over the workout, ahead of every lien
        carry = value[rows, np.where(d, default_month, 0)] * params.workout_carry_pct * lag / 12
        remaining = np.maximum(remaining - np.where(d, carry, 0.0), 0.0)
        for i in range(n_loans):
            advances = bal_at_default[i] * rate_at_default[i] * lag / 12 if params.advance_interest else 0.0
            workout_costs = bal_at_default[i] * params.workout_cost_pct   # legal, receiver, servicing
            exposure = np.where(d, bal_at_default[i] + advances + workout_costs, 0.0)
            received = np.minimum(exposure, remaining)
            remaining -= received
            losses[i] = np.where(d, np.maximum(exposure - received, 0.0), 0.0)
            pv[i] += received * df[liq]

    value_fan = _fan(value, last)
    out = []
    for i, l in enumerate(loans):
        out.append(_summarize(l, default_month, kind, bal_at_default[i], losses[i], pv[i], value_fan,
                              mat_years=int(np.ceil((l.term_months + l.extension_count * l.extension_months) / 12))))
    return out


def _loan_rate(loan: LoanInput, index_rate: np.ndarray) -> np.ndarray:
    if loan.rate_type != "floating":
        return np.full(index_rate.shape, loan.coupon)
    idx = index_rate if loan.index_floor is None else np.maximum(index_rate, loan.index_floor)
    if loan.index_cap is not None:
        idx = np.minimum(idx, loan.index_cap)   # a purchased cap limits the borrower's index cost
    return idx + loan.spread


def _mark_default(hit, t, k, default_month, kind, active, begin, rate, bal_at_default, rate_at_default):
    if not hit.any():
        return
    default_month[hit] = t
    kind[hit] = k
    for i in range(active.shape[0]):
        on = hit & active[i]
        bal_at_default[i] = np.where(on, begin[i], bal_at_default[i])
        rate_at_default[i] = np.where(on, rate[i], rate_at_default[i])


def _fan(value: np.ndarray, last_month: int) -> dict[str, list[float]]:
    cols = list(range(0, min(last_month, value.shape[1] - 1) + 1, 12))
    pct = np.percentile(value[:, cols], PERCENTILES, axis=0)
    fan = {f"p{p}": [float(v) for v in row] for p, row in zip(PERCENTILES, pct)}
    fan["month"] = [float(c) for c in cols]
    return fan


def _summarize(loan, default_month, kind, bal_d, losses, pv, value_fan, mat_years) -> LoanRiskResult:
    # A junior loan already repaid when the property later defaults is not in default
    defaulted = (default_month >= 0) & (bal_d > 0)
    if loan.delinquency_status in DEFAULTED_STATUSES:
        defaulted = default_month >= 0
    pd = float(defaulted.mean())
    term_years = max(loan.term_months / 12, 1 / 12)
    with np.errstate(divide="ignore", invalid="ignore"):
        lgd_paths = np.where(defaulted, losses / np.where(bal_d > 0, bal_d, 1.0), np.nan)
    balance = loan.balance
    return LoanRiskResult(
        loan_id=loan.loan_id,
        balance=balance,
        pd_cumulative=pd,
        pd_term=float((defaulted & (kind == KIND_TERM)).mean()),
        pd_maturity=float((defaulted & (kind == KIND_MATURITY)).mean()),
        pd_one_year=float((defaulted & (default_month <= 12)).mean()),
        pd_annualized=1 - (1 - min(pd, 1.0)) ** (1 / term_years),
        pd_by_year=[float((defaulted & (default_month <= 12 * y)).mean()) for y in range(1, mat_years + 1)],
        lgd=float(np.nanmean(lgd_paths)) if defaulted.any() else None,
        expected_loss=float(losses.mean() / balance) if balance > 0 else 0.0,
        expected_loss_amount=float(losses.mean()),
        loss_percentiles={
            k: float(np.percentile(losses, q) / balance) if balance > 0 else 0.0
            for k, q in (("p95", 95), ("p99", 99), ("p999", 99.9))
        },
        fair_value=float(pv.mean()),
        fair_value_price=float(pv.mean() / balance) if balance > 0 else 0.0,
        value_percentiles=value_fan,
        losses=losses,
    )


def loan_input_from_schedule(
    loan_id: str,
    collateral_key: str,
    terms: LoanTerms,
    state: LoanState,
    rows: list[ScheduleRow],
    lien_position: int = 1,
    extension_count: int = 0,
    extension_months: int = 0,
    delinquency_status: str = "current",
) -> LoanInput:
    """Simulator input from the contractual schedule rolled forward to the as-of date."""
    return LoanInput(
        loan_id=loan_id,
        collateral_key=collateral_key,
        balance=float(state.balance),
        begin_balance=np.array([float(r.beginning_balance) for r in rows] or [float(state.balance)]),
        principal=np.array([float(r.principal) for r in rows] or [0.0]),
        rate_type=terms.rate_type,
        coupon=float(terms.coupon or 0),
        spread=float(terms.spread or 0),
        index_floor=float(terms.index_floor) if terms.index_floor is not None else None,
        index_cap=float(terms.index_cap) if terms.index_cap is not None else None,
        lien_position=lien_position,
        extension_count=extension_count,
        extension_months=extension_months,
        delinquency_status=delinquency_status,
    )


def portfolio_losses(results: list[LoanRiskResult], bins: int = 30) -> PortfolioLossResult:
    total_balance = sum(r.balance for r in results)
    if not results:
        return PortfolioLossResult(0.0, 0.0, 0.0, 0.0, {}, 0.0, {"edges": [], "counts": []})
    total = np.sum([r.losses for r in results], axis=0)
    p99 = float(np.percentile(total, 99))
    # Mean of the worst 1% of paths; selecting by `>= p99` would take in every path tied at p99
    tail = np.sort(total)[-math.ceil(0.01 * total.size):]
    counts, edges = np.histogram(total, bins=bins)
    return PortfolioLossResult(
        total_balance=total_balance,
        expected_loss_amount=float(total.mean()),
        expected_loss=float(total.mean() / total_balance) if total_balance else 0.0,
        loss_std=float(total.std()),
        var={"p95": float(np.percentile(total, 95)), "p99": p99, "p999": float(np.percentile(total, 99.9))},
        expected_shortfall_99=float(tail.mean()) if tail.size else p99,
        histogram={"edges": [float(e) for e in edges], "counts": [float(c) for c in counts]},
    )
