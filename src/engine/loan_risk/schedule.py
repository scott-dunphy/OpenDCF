"""
Contractual mortgage loan schedules measured from origination.

Loans in a lender's book are seasoned: they were originated before the
analysis (as-of) date. The schedule is built from the origination date so
IO periods, amortization and maturity line up with the note, then rolled
forward to the as-of date. A reported balance from the loan tape, when
given, replaces the scheduled balance and the remaining payments are
re-solved from it over the remaining amortization.

Conventions: monthly payments on the origination day-of-month, interest
accrued 30/360 (rate / 12), level payment after the IO period, balloon at
maturity. All arithmetic uses Decimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.engine.date_utils import add_months, months_between

_ZERO = Decimal(0)


@dataclass(frozen=True)
class LoanTerms:
    origination_date: date
    original_balance: Decimal
    maturity_date: date
    rate_type: str = "fixed"                    # fixed | floating
    coupon: Decimal | None = None               # fixed note rate
    spread: Decimal | None = None               # floating: margin over index
    index_floor: Decimal | None = None          # floating: floor on the index
    index_cap: Decimal | None = None            # floating: purchased rate cap strike
    amortization_months: int | None = None      # None or 0 = interest-only to maturity
    io_months: int = 0                          # IO period from origination

    @property
    def term_months(self) -> int:
        return max(1, months_between(self.origination_date, self.maturity_date))

    @property
    def is_full_io(self) -> bool:
        return not self.amortization_months or self.io_months >= self.term_months

    def all_in_rate(self, index_rate: Decimal) -> Decimal:
        """Note rate for a given index level (fixed loans ignore the index)."""
        if self.rate_type != "floating":
            return self.coupon or _ZERO
        idx = index_rate
        if self.index_floor is not None:
            idx = max(idx, self.index_floor)
        return idx + (self.spread or _ZERO)


@dataclass(frozen=True)
class ScheduleRow:
    period: int            # 1 = first payment after the as-of date
    payment_date: date
    beginning_balance: Decimal
    interest: Decimal
    principal: Decimal     # scheduled amortization (excludes the balloon)
    balloon: Decimal       # remaining balance repaid at maturity
    ending_balance: Decimal

    @property
    def payment(self) -> Decimal:
        return self.interest + self.principal + self.balloon


@dataclass(frozen=True)
class LoanState:
    """Where a seasoned loan stands at the as-of date."""
    as_of_date: date
    payments_made: int
    scheduled_balance: Decimal
    balance: Decimal                    # reported balance when given, else scheduled
    balance_difference_pct: Decimal     # (reported - scheduled) / scheduled
    remaining_term_months: int
    remaining_io_months: int
    remaining_amortization_months: int  # 0 = interest-only for the rest of the term
    rate: Decimal                       # all-in rate used for the projection


def level_payment(balance: Decimal, monthly_rate: Decimal, months: int) -> Decimal:
    if months <= 0:
        return balance
    if monthly_rate == _ZERO:
        return balance / Decimal(months)
    factor = (1 + monthly_rate) ** months
    return balance * monthly_rate * factor / (factor - 1)


def payments_made(terms: LoanTerms, as_of: date) -> int:
    """Number of scheduled payment dates on or before the as-of date."""
    k = 0
    while k < terms.term_months and add_months(terms.origination_date, k + 1) <= as_of:
        k += 1
    return k


def scheduled_balance(terms: LoanTerms, k: int, rate: Decimal) -> Decimal:
    """Contractual balance after k payments from origination."""
    balance = terms.original_balance
    if terms.is_full_io or k <= terms.io_months:
        return balance
    r = rate / Decimal(12)
    amort = int(terms.amortization_months or 0)
    pmt = level_payment(balance, r, amort)
    for _ in range(k - terms.io_months):
        balance -= pmt - balance * r
    return max(_ZERO, balance)


def roll_forward(
    terms: LoanTerms,
    as_of: date,
    index_rate: Decimal = _ZERO,
    reported_balance: Decimal | None = None,
) -> LoanState:
    """
    Position at the as-of date. Floating-rate history uses today's all-in rate,
    which only matters for amortizing floating loans.
    """
    rate = terms.all_in_rate(index_rate)
    k = payments_made(terms, as_of)
    sched = scheduled_balance(terms, k, rate)
    balance = reported_balance if reported_balance is not None else sched
    diff = (balance - sched) / sched if sched > _ZERO else _ZERO
    remaining_term = terms.term_months - k
    remaining_io = max(0, terms.io_months - k)
    if terms.is_full_io:
        remaining_amort = 0
    else:
        amortized = max(0, k - terms.io_months)
        remaining_amort = max(1, int(terms.amortization_months or 0) - amortized)
    return LoanState(
        as_of_date=as_of,
        payments_made=k,
        scheduled_balance=sched,
        balance=balance,
        balance_difference_pct=diff,
        remaining_term_months=remaining_term,
        remaining_io_months=remaining_io,
        remaining_amortization_months=remaining_amort,
        rate=rate,
    )


def project_schedule(terms: LoanTerms, state: LoanState) -> list[ScheduleRow]:
    """Remaining contractual payments from the as-of balance through maturity."""
    rows: list[ScheduleRow] = []
    balance = state.balance
    r = state.rate / Decimal(12)
    pmt = (
        level_payment(balance, r, state.remaining_amortization_months)
        if state.remaining_amortization_months
        else _ZERO
    )
    for t in range(1, state.remaining_term_months + 1):
        begin = balance
        interest = begin * r
        principal = _ZERO
        if state.remaining_amortization_months and t > state.remaining_io_months:
            principal = min(begin, pmt - interest)
        balloon = _ZERO
        end = begin - principal
        if t == state.remaining_term_months:
            balloon, end = end, _ZERO
        rows.append(ScheduleRow(
            period=t,
            payment_date=add_months(terms.origination_date, state.payments_made + t),
            beginning_balance=begin,
            interest=interest,
            principal=principal,
            balloon=balloon,
            ending_balance=end,
        ))
        balance = end
    return rows


def weighted_average_life_years(rows: list[ScheduleRow]) -> Decimal:
    """Contractual WAL of the remaining principal (amortization plus balloon)."""
    total = sum((row.principal + row.balloon for row in rows), _ZERO)
    if total == _ZERO:
        return _ZERO
    weighted = sum(
        (Decimal(row.period) / Decimal(12) * (row.principal + row.balloon) for row in rows), _ZERO
    )
    return weighted / total
