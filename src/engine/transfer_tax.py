"""
Transfer-tax presets applied to gross reversion value at sale.

Rates and thresholds are sourced from official jurisdictions (as-of 2026-03-01).
Use `custom_rate` for unsupported jurisdictions.
"""
from __future__ import annotations

from decimal import Decimal

# Common decimal constants
_ZERO = Decimal("0")

# LA city documentary transfer tax + ULA (Measure ULA)
_LA_BASE_TRANSFER_RATE = Decimal("0.0045")  # $4.50 per $1,000 = 0.45%
_LA_ULA_THRESHOLD_1 = Decimal("5300000")
_LA_ULA_THRESHOLD_2 = Decimal("10600000")
_LA_ULA_RATE_1 = Decimal("0.04")
_LA_ULA_RATE_2 = Decimal("0.055")

# San Francisco transfer tax rates (expressed as % of consideration)
_SF_BRACKETS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("250000"), Decimal("0.005")),
    (Decimal("1000000"), Decimal("0.0068")),
    (Decimal("5000000"), Decimal("0.0075")),
    (Decimal("10000000"), Decimal("0.0225")),
    (Decimal("25000000"), Decimal("0.0275")),
)
_SF_TOP_RATE = Decimal("0.03")

# NYC + NYS commercial transfer taxes (combined)
_NYC_RPTT_THRESHOLD = Decimal("500000")
_NYC_RPTT_LOW = Decimal("0.01425")
_NYC_RPTT_HIGH = Decimal("0.02625")
_NYS_BASE = Decimal("0.004")
_NYS_ADDITIONAL_NONRES_THRESHOLD = Decimal("2000000")
_NYS_ADDITIONAL_NONRES = Decimal("0.0025")

# Philadelphia combined city + state rate
_PHILADELPHIA_TOTAL_RATE = Decimal("0.04278")

# Washington, DC transfer + recordation deed taxes
_DC_THRESHOLD = Decimal("400000")
_DC_LOW_COMBINED = Decimal("0.022")  # 1.1% + 1.1%
_DC_HIGH_COMBINED = Decimal("0.029")  # 1.45% + 1.45%

# Washington state REET (state-only), progressive marginal rates
_WA_1 = Decimal("525000")
_WA_2 = Decimal("1525000")
_WA_3 = Decimal("3025000")
_WA_R1 = Decimal("0.011")
_WA_R2 = Decimal("0.0128")
_WA_R3 = Decimal("0.0275")
_WA_R4 = Decimal("0.03")


TRANSFER_TAX_PRESETS: tuple[dict[str, str], ...] = (
    {
        "code": "none",
        "label": "None",
        "description": "No transfer tax applied at sale.",
    },
    {
        "code": "custom_rate",
        "label": "Custom Flat Rate",
        "description": "Apply user-defined flat transfer tax rate to gross reversion.",
    },
    {
        "code": "la_city_ula",
        "label": "Los Angeles: City + ULA",
        "description": "LA city transfer tax plus Measure ULA tiers.",
    },
    {
        "code": "san_francisco_transfer",
        "label": "San Francisco Transfer Tax",
        "description": "San Francisco transfer tax bracket schedule.",
    },
    {
        "code": "nyc_nys_commercial",
        "label": "NYC + NYS Commercial",
        "description": "NYC RPTT plus NY state transfer taxes for non-residential transactions.",
    },
    {
        "code": "philadelphia_realty_transfer",
        "label": "Philadelphia Realty Transfer",
        "description": "Philadelphia city + Pennsylvania state combined transfer tax.",
    },
    {
        "code": "dc_deed_transfer_recordation",
        "label": "Washington, DC Deed Taxes",
        "description": "DC transfer and recordation taxes on deed transfers.",
    },
    {
        "code": "wa_state_reet",
        "label": "Washington State REET",
        "description": "Washington state graduated real estate excise tax (state portion only).",
    },
)


def transfer_tax_presets_metadata() -> list[dict[str, object]]:
    """Metadata payload for UI dropdowns/documentation."""
    base = [dict(item) for item in TRANSFER_TAX_PRESETS]
    source_links = {
        "la_city_ula": [
            "https://finance.lacity.gov/tax-education/new-tax-ordinance-faq",
        ],
        "san_francisco_transfer": [
            "https://www.sf.gov/get-informed-about-property-transfer-tax",
        ],
        "nyc_nys_commercial": [
            "https://www.nyc.gov/site/finance/property/real-property-transfer-tax-rptt.page",
            "https://www.tax.ny.gov/bus/transfer/rptidx.htm",
        ],
        "philadelphia_realty_transfer": [
            "https://www.phila.gov/services/payments-assistance-taxes/taxes/realty-transfer-tax/",
        ],
        "dc_deed_transfer_recordation": [
            "https://otr.cfo.dc.gov/page/tax-rates-and-revenue-rulings",
            "https://otr.cfo.dc.gov/publication/tax-facts-2025",
        ],
        "wa_state_reet": [
            "https://dor.wa.gov/education/industry-guides/real-estate-excise-tax/real-estate-excise-tax-rates-and-fees",
        ],
    }
    for item in base:
        code = str(item["code"])
        item["as_of"] = "2026-03-01"
        item["sources"] = source_links.get(code, [])
    return base


def calculate_transfer_tax_amount(
    gross_sale_price: Decimal,
    preset_code: str,
    custom_rate: Decimal | None = None,
) -> Decimal:
    """Calculate transfer tax dollars for a gross sale price."""
    if gross_sale_price <= _ZERO:
        return _ZERO

    code = (preset_code or "none").strip().lower()

    if code == "none":
        return _ZERO

    if code == "custom_rate":
        rate = custom_rate if custom_rate is not None else _ZERO
        return gross_sale_price * max(_ZERO, rate)

    if code == "la_city_ula":
        ula_rate = _ZERO
        if gross_sale_price > _LA_ULA_THRESHOLD_2:
            ula_rate = _LA_ULA_RATE_2
        elif gross_sale_price > _LA_ULA_THRESHOLD_1:
            ula_rate = _LA_ULA_RATE_1
        return gross_sale_price * (_LA_BASE_TRANSFER_RATE + ula_rate)

    if code == "san_francisco_transfer":
        rate = _SF_TOP_RATE
        for threshold, bracket_rate in _SF_BRACKETS:
            if gross_sale_price < threshold:
                rate = bracket_rate
                break
        return gross_sale_price * rate

    if code == "nyc_nys_commercial":
        nyc_rate = _NYC_RPTT_LOW if gross_sale_price < _NYC_RPTT_THRESHOLD else _NYC_RPTT_HIGH
        nys_rate = _NYS_BASE + (
            _NYS_ADDITIONAL_NONRES if gross_sale_price >= _NYS_ADDITIONAL_NONRES_THRESHOLD else _ZERO
        )
        return gross_sale_price * (nyc_rate + nys_rate)

    if code == "philadelphia_realty_transfer":
        return gross_sale_price * _PHILADELPHIA_TOTAL_RATE

    if code == "dc_deed_transfer_recordation":
        rate = _DC_LOW_COMBINED if gross_sale_price < _DC_THRESHOLD else _DC_HIGH_COMBINED
        return gross_sale_price * rate

    if code == "wa_state_reet":
        return _wa_state_reet(gross_sale_price)

    # Unknown preset: fail safe to no transfer tax.
    return _ZERO


def _wa_state_reet(amount: Decimal) -> Decimal:
    """Washington state graduated REET (marginal schedule)."""
    tax = _ZERO
    first = min(amount, _WA_1)
    tax += first * _WA_R1

    if amount > _WA_1:
        second = min(amount, _WA_2) - _WA_1
        tax += second * _WA_R2

    if amount > _WA_2:
        third = min(amount, _WA_3) - _WA_2
        tax += third * _WA_R3

    if amount > _WA_3:
        tax += (amount - _WA_3) * _WA_R4

    return tax
