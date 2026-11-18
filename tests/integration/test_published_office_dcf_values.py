"""Independent office-property DCF checks from public appraisal reports.

Each report prints its annual cash flow before debt service, net property resale,
selected annual discount rate, and unrounded value indication.  These tests use
those disclosed inputs to verify OpenDCF's annual present-value calculation.

Sources:
* 250 Greenwich Street (2024), pages 62-63:
  https://mayafiles.tase.co.il/rpdf/1583001-1584000/P1583608-01.pdf
* 7 World Trade Center (2021), pages 102-104:
  https://mayafiles.tase.co.il/rpdf/1359001-1360000/P1359106-01.pdf
* The Epic (2026), pages 83-84:
  https://mayafiles.tase.co.il/rpdf/1745001-1746000/P1745280-00.pdf
* 535-545 Fifth Avenue and 3 Columbus Circle (2023), pages 70-71 and 76-77:
  https://mayafiles.tase.co.il/rpdf/1509001-1510000/P1509757-01.pdf

The source tables report whole dollars, so sub-dollar differences can arise from
discounting the displayed figures rather than the reports' unrounded internals.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.dcf import discount_cash_flows
from src.engine.types import AnnualPropertyCashFlow


@dataclass(frozen=True)
class OfficeCase:
    name: str
    cash_flows: tuple[int, ...]
    net_resale: int
    discount_rate: str
    published_value: int


CASES = (
    OfficeCase(
        "250 Greenwich Street",
        (43372277, 52582536, 56680183, 42989934, -93893839, 61952375, 74890223),
        1594105330,
        "0.0575",
        1272114560,
    ),
    OfficeCase(
        "7 World Trade Center",
        (49073181, 36017632, 21096163, 53975447, 60161289, 61546725, 53371119, -52838110),
        1531008785,
        "0.055",
        1230942246,
    ),
    OfficeCase(
        "The Epic",
        (2450544, -3380798, 3335460, 4638390, 11375874, 9915573, 12138944, 11919454, 12813474, 13197878),
        172516411,
        "0.10",
        106593160,
    ),
    OfficeCase(
        "535-545 Fifth Avenue",
        (14048213, 20892688, 22825891, 28049234, 30149193, 28296083, 26142383, 29578334, 32704517),
        687649529,
        "0.065",
        557098474,
    ),
    OfficeCase(
        "3 Columbus Circle",
        (58563033, 57345088, 56966527, 60484179, 63075705, 48637936, 63739431, 65938207, 67098768),
        1271553406,
        "0.0675",
        1100037442,
    ),
)


def _cash_flow(year: int, amount: int) -> AnnualPropertyCashFlow:
    zero = D(0)
    return AnnualPropertyCashFlow(
        year=year,
        period_start=date(2000 + year, 1, 1),
        period_end=date(2000 + year, 12, 31),
        gross_potential_rent=zero,
        free_rent=zero,
        absorption_vacancy=zero,
        loss_to_lease=zero,
        expense_recoveries=zero,
        percentage_rent=zero,
        other_income=zero,
        gross_potential_income=zero,
        general_vacancy_loss=zero,
        credit_loss=zero,
        effective_gross_income=zero,
        operating_expenses=zero,
        net_operating_income=zero,
        tenant_improvements=zero,
        leasing_commissions=zero,
        capital_reserves=zero,
        building_improvements=zero,
        cash_flow_before_debt=D(amount),
        debt_service=zero,
        levered_cash_flow=D(amount),
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_published_office_discounting_only(case: OfficeCase):
    cash_flows = [_cash_flow(year, amount) for year, amount in enumerate(case.cash_flows, 1)]
    _, _, value = discount_cash_flows(cash_flows, D(case.net_resale), D(case.discount_rate))

    assert abs(value - D(case.published_value)) < D(2)
