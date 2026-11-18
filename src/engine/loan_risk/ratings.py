"""
Loan ratings: Moody's-style rating from expected loss, and NAIC commercial
mortgage (CM) risk categories.

Moody's idealized cumulative expected loss (EL) and default (PD) rates, in
percent by horizon year 1-10, from Moody's "Moody's Approach to Rating
Synthetic CDOs" (2003), Appendices A and B. EL = PD x 55% (45% recovery).
A loan's EL over its remaining weighted-average life is compared with the
table at that tenor (linear interpolation; beyond 10 years the 10-year
column is used); the loan gets the best rating whose idealized EL is at
least the loan's EL.

NAIC CM categories follow the Life RBC LR004 matrix for office, industrial,
retail and multifamily loans (with the 2014 correction): DSC = NOI /
(12 payments amortizing the total balance over 300 months at the loan rate),
rounded down to 2 decimals; LTV = total balance / current value, rounded to
the nearest percent. Non-senior loans move one category riskier (cap CM5);
90+ days delinquent is CM6 and foreclosure is CM7.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

MOODYS_RATINGS = [
    "Aaa", "Aa1", "Aa2", "Aa3", "A1", "A2", "A3", "Baa1", "Baa2", "Baa3",
    "Ba1", "Ba2", "Ba3", "B1", "B2", "B3", "Caa1", "Caa2", "Caa3",
]
WORST_RATING = "Ca"

MOODYS_IDEALIZED_EL_PCT: dict[str, list[float]] = {
    "Aaa": [0.0000, 0.0001, 0.0004, 0.0010, 0.0016, 0.0022, 0.0029, 0.0036, 0.0045, 0.0055],
    "Aa1": [0.0003, 0.0017, 0.0055, 0.0116, 0.0171, 0.0231, 0.0297, 0.0369, 0.0451, 0.0550],
    "Aa2": [0.0007, 0.0044, 0.0143, 0.0259, 0.0374, 0.0490, 0.0611, 0.0743, 0.0902, 0.1100],
    "Aa3": [0.0017, 0.0105, 0.0325, 0.0556, 0.0781, 0.1007, 0.1249, 0.1496, 0.1799, 0.2200],
    "A1": [0.0032, 0.0204, 0.0644, 0.1040, 0.1436, 0.1815, 0.2233, 0.2640, 0.3152, 0.3850],
    "A2": [0.0060, 0.0385, 0.1221, 0.1898, 0.2569, 0.3207, 0.3905, 0.4560, 0.5401, 0.6600],
    "A3": [0.0214, 0.0825, 0.1980, 0.2970, 0.4015, 0.5005, 0.6105, 0.7150, 0.8360, 0.9900],
    "Baa1": [0.0495, 0.1540, 0.3080, 0.4565, 0.6050, 0.7535, 0.9185, 1.0835, 1.2485, 1.4300],
    "Baa2": [0.0935, 0.2585, 0.4565, 0.6600, 0.8690, 1.0835, 1.3255, 1.5675, 1.7820, 1.9800],
    "Baa3": [0.2310, 0.5775, 0.9405, 1.3090, 1.6775, 2.0350, 2.3815, 2.7335, 3.0635, 3.3550],
    "Ba1": [0.4785, 1.1110, 1.7215, 2.3100, 2.9040, 3.4375, 3.8830, 4.3395, 4.7795, 5.1700],
    "Ba2": [0.8580, 1.9085, 2.8490, 3.7400, 4.6255, 5.3735, 5.8850, 6.4130, 6.9575, 7.4250],
    "Ba3": [1.5455, 3.0305, 4.3285, 5.3845, 6.5230, 7.4195, 8.0410, 8.6405, 9.1905, 9.7130],
    "B1": [2.5740, 4.6090, 6.3690, 7.6175, 8.8660, 9.8395, 10.5215, 11.1265, 11.6820, 12.2100],
    "B2": [3.9380, 6.4185, 8.5525, 9.9715, 11.3905, 12.4575, 13.2055, 13.8325, 14.4210, 14.9600],
    "B3": [6.3910, 9.1355, 11.5665, 13.2220, 14.8775, 16.0600, 17.0500, 17.9190, 18.5790, 19.1950],
    "Caa1": [9.5599, 12.7788, 15.7512, 17.8634, 19.9726, 21.4317, 22.7620, 24.0113, 25.1195, 26.2350],
    "Caa2": [14.3000, 17.8750, 21.4500, 24.1340, 26.8125, 28.6000, 30.3875, 32.1750, 33.9625, 35.7500],
    "Caa3": [28.0446, 31.3548, 34.3475, 36.4331, 38.4017, 39.6611, 40.8817, 42.0669, 43.2196, 44.3850],
}

MOODYS_IDEALIZED_PD_PCT: dict[str, list[float]] = {
    "Aaa": [0.0001, 0.0002, 0.0007, 0.0018, 0.0029, 0.0040, 0.0052, 0.0066, 0.0082, 0.0100],
    "Aa1": [0.0006, 0.0030, 0.0100, 0.0210, 0.0310, 0.0420, 0.0540, 0.0670, 0.0820, 0.1000],
    "Aa2": [0.0014, 0.0080, 0.0260, 0.0470, 0.0680, 0.0890, 0.1110, 0.1350, 0.1640, 0.2000],
    "Aa3": [0.0030, 0.0190, 0.0590, 0.1010, 0.1420, 0.1830, 0.2270, 0.2720, 0.3270, 0.4000],
    "A1": [0.0058, 0.0370, 0.1170, 0.1890, 0.2610, 0.3300, 0.4060, 0.4800, 0.5730, 0.7000],
    "A2": [0.0109, 0.0700, 0.2220, 0.3450, 0.4670, 0.5830, 0.7100, 0.8290, 0.9820, 1.2000],
    "A3": [0.0389, 0.1500, 0.3600, 0.5400, 0.7300, 0.9100, 1.1100, 1.3000, 1.5200, 1.8000],
    "Baa1": [0.0900, 0.2800, 0.5600, 0.8300, 1.1000, 1.3700, 1.6700, 1.9700, 2.2700, 2.6000],
    "Baa2": [0.1700, 0.4700, 0.8300, 1.2000, 1.5800, 1.9700, 2.4100, 2.8500, 3.2400, 3.6000],
    "Baa3": [0.4200, 1.0500, 1.7100, 2.3800, 3.0500, 3.7000, 4.3300, 4.9700, 5.5700, 6.1000],
    "Ba1": [0.8700, 2.0200, 3.1300, 4.2000, 5.2800, 6.2500, 7.0600, 7.8900, 8.6900, 9.4000],
    "Ba2": [1.5600, 3.4700, 5.1800, 6.8000, 8.4100, 9.7700, 10.7000, 11.6600, 12.6500, 13.5000],
    "Ba3": [2.8100, 5.5100, 7.8700, 9.7900, 11.8600, 13.4900, 14.6200, 15.7100, 16.7100, 17.6600],
    "B1": [4.6800, 8.3800, 11.5800, 13.8500, 16.1200, 17.8900, 19.1300, 20.2300, 21.2400, 22.2000],
    "B2": [7.1600, 11.6700, 15.5500, 18.1300, 20.7100, 22.6500, 24.0100, 25.1500, 26.2200, 27.2000],
    "B3": [11.6200, 16.6100, 21.0300, 24.0400, 27.0500, 29.2000, 31.0000, 32.5800, 33.7800, 34.9000],
    "Caa1": [17.3816, 23.2341, 28.6386, 32.4788, 36.3137, 38.9667, 41.3854, 43.6570, 45.6718, 47.7000],
    "Caa2": [26.0000, 32.5000, 39.0000, 43.8800, 48.7500, 52.0000, 55.2500, 58.5000, 61.7500, 65.0000],
    "Caa3": [50.9902, 57.0088, 62.4500, 66.2420, 69.8212, 72.1110, 74.3303, 76.4853, 78.5812, 80.7000],
}


def idealized_rate(table_row: list[float], tenor_years: float) -> float:
    """Table value (as a decimal) at a tenor, interpolating linearly; 0 at tenor 0."""
    t = max(0.0, tenor_years)
    if t >= len(table_row):
        return table_row[-1] / 100
    lo = int(t)
    prev = table_row[lo - 1] if lo >= 1 else 0.0
    nxt = table_row[lo]
    return (prev + (nxt - prev) * (t - lo)) / 100


def moodys_rating(
    expected_loss: float,
    tenor_years: float,
    el_table: dict[str, list[float]] | None = None,
) -> str:
    """Best rating whose idealized EL at the tenor is at least the loan's EL (decimal)."""
    table = el_table or MOODYS_IDEALIZED_EL_PCT
    for rating in MOODYS_RATINGS:
        if rating in table and expected_loss <= idealized_rate(table[rating], tenor_years) + 1e-12:
            return rating
    return WORST_RATING


# --- NAIC CM categories -------------------------------------------------------

NAIC_CM_FACTORS = {
    "CM1": 0.0090, "CM2": 0.0175, "CM3": 0.0300, "CM4": 0.0500,
    "CM5": 0.0750, "CM6": 0.1800, "CM7": 0.2300,
}
NAIC_DSC_AMORTIZATION_MONTHS = 300
DELINQUENT_90_PLUS = {"90_plus"}
IN_FORECLOSURE = {"foreclosure", "reo"}


def naic_debt_service(balance: Decimal, rate: Decimal) -> Decimal:
    """Standardized annual debt service: 300-month amortization of the total balance at the loan rate."""
    r = rate / Decimal(12)
    n = NAIC_DSC_AMORTIZATION_MONTHS
    if r == 0:
        return balance / Decimal(n) * 12
    factor = (1 + r) ** n
    return balance * r * factor / (factor - 1) * 12


def naic_dsc(noi: Decimal, balance: Decimal, rate: Decimal) -> Decimal | None:
    ds = naic_debt_service(balance, rate)
    if ds <= 0:
        return None
    return (noi / ds).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def naic_ltv(balance: Decimal, value: Decimal) -> Decimal | None:
    if value <= 0:
        return None
    return (balance / value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _cm_matrix(dsc: Decimal, ltv: Decimal) -> int:
    """Performing-loan category 1-5 from the LR004 office/industrial/retail/multifamily matrix."""
    if dsc < Decimal("0.95"):
        if ltv < Decimal("0.85"):
            return 3
        return 4 if ltv < Decimal("1.05") else 5
    if dsc < Decimal("1.15"):
        if ltv < Decimal("0.75"):
            return 2
        return 3 if ltv < Decimal("1.00") else 4
    if dsc < Decimal("1.50"):
        return 2 if ltv < Decimal("1.00") else 3
    if dsc < Decimal("1.75"):
        if ltv < Decimal("0.85"):
            return 1
        return 2 if ltv < Decimal("1.00") else 3
    return 1 if ltv < Decimal("0.85") else 2


def naic_cm_category(
    dsc: Decimal | None,
    ltv: Decimal | None,
    delinquency_status: str = "current",
    senior: bool = True,
) -> str:
    if delinquency_status in IN_FORECLOSURE:
        return "CM7"
    if delinquency_status in DELINQUENT_90_PLUS:
        return "CM6"
    # Missing NOI or value: treat as zero NOI / unbounded LTV (worst performing cell)
    cat = _cm_matrix(dsc if dsc is not None else Decimal(0), ltv if ltv is not None else Decimal(99))
    if not senior:
        cat = min(5, cat + 1)
    return f"CM{cat}"
