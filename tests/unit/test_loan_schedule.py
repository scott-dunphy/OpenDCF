"""Contractual schedules for seasoned loans: built from origination, rolled to the as-of date."""
from datetime import date
from decimal import Decimal

from src.engine.loan_risk.schedule import (
    LoanTerms,
    level_payment,
    payments_made,
    project_schedule,
    roll_forward,
    weighted_average_life_years,
)


def _closed_form_balance(loan, rate, amort, k):
    r = rate / Decimal(12)
    pmt = level_payment(loan, r, amort)
    g = (1 + r) ** k
    return loan * g - pmt * (g - 1) / r


AMORTIZING = LoanTerms(
    origination_date=date(2020, 1, 15),
    original_balance=Decimal("10000000"),
    maturity_date=date(2030, 1, 15),
    coupon=Decimal("0.05"),
    amortization_months=360,
    io_months=24,
)


class TestRollForward:
    def test_payments_counted_from_origination(self):
        # Payments on the 15th: Feb 2020 .. Dec 2024 = 59 by Jan 1, 2025
        assert payments_made(AMORTIZING, date(2025, 1, 1)) == 59
        assert payments_made(AMORTIZING, date(2025, 1, 15)) == 60
        assert payments_made(AMORTIZING, date(2019, 12, 31)) == 0
        assert payments_made(AMORTIZING, date(2035, 1, 1)) == 120

    def test_scheduled_balance_after_io_and_amortization(self):
        state = roll_forward(AMORTIZING, date(2025, 1, 1))
        expected = _closed_form_balance(Decimal("10000000"), Decimal("0.05"), 360, 59 - 24)
        assert abs(state.balance - expected) < Decimal("0.01")
        assert state.remaining_term_months == 61
        assert state.remaining_io_months == 0
        assert state.remaining_amortization_months == 360 - 35

    def test_still_in_io(self):
        state = roll_forward(AMORTIZING, date(2021, 1, 1))
        assert state.balance == Decimal("10000000")
        assert state.remaining_io_months == 24 - 11
        assert state.remaining_amortization_months == 360

    def test_reported_balance_overrides_and_reconciles(self):
        sched = roll_forward(AMORTIZING, date(2025, 1, 1)).scheduled_balance
        state = roll_forward(AMORTIZING, date(2025, 1, 1), reported_balance=sched - Decimal("100000"))
        assert state.balance == sched - Decimal("100000")
        assert state.balance_difference_pct < 0
        rows = project_schedule(AMORTIZING, state)
        assert abs(sum(r.principal + r.balloon for r in rows) - state.balance) < Decimal("0.01")


class TestProjection:
    def test_schedule_runs_to_maturity_with_balloon(self):
        state = roll_forward(AMORTIZING, date(2025, 1, 1))
        rows = project_schedule(AMORTIZING, state)
        assert len(rows) == 61
        assert rows[0].payment_date == date(2025, 1, 15)
        assert rows[-1].payment_date == date(2030, 1, 15)
        assert rows[-1].ending_balance == 0
        assert rows[-1].balloon > Decimal("8000000")
        assert abs(sum(r.principal + r.balloon for r in rows) - state.balance) < Decimal("0.01")
        payment = rows[0].interest + rows[0].principal
        assert abs(payment - level_payment(Decimal("10000000"), Decimal("0.05") / 12, 360)) < Decimal("0.01")

    def test_floating_io_bullet(self):
        terms = LoanTerms(
            origination_date=date(2023, 6, 1),
            original_balance=Decimal("5000000"),
            maturity_date=date(2028, 6, 1),
            rate_type="floating",
            spread=Decimal("0.03"),
            index_floor=Decimal("0.01"),
        )
        state = roll_forward(terms, date(2025, 1, 1), index_rate=Decimal("0.005"))
        assert state.rate == Decimal("0.04")      # floor 1% + 3% spread
        assert state.remaining_amortization_months == 0
        rows = project_schedule(terms, state)
        assert all(r.principal == 0 for r in rows)
        assert rows[-1].balloon == Decimal("5000000")
        assert abs(weighted_average_life_years(rows) - Decimal(len(rows)) / 12) < Decimal("0.0001")
