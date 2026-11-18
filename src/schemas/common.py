import enum
from datetime import date
from typing import Annotated

from pydantic import AfterValidator


def first_of_next_month_unless_first(d: date) -> date:
    """A mid-month date moves to the 1st of the next month; the 1st is kept."""
    if d.day == 1:
        return d
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


# Analysis start: months run from the 1st to month end
MonthStart = Annotated[date, AfterValidator(first_of_next_month_unless_first)]


class PropertyType(str, enum.Enum):
    MULTIFAMILY = "multifamily"
    SELF_STORAGE = "self_storage"
    OFFICE = "office"
    RETAIL = "retail"
    INDUSTRIAL = "industrial"
    MIXED_USE = "mixed_use"
    MARINA = "marina"
    SENIORS_HOUSING = "seniors_housing"


class AreaUnit(str, enum.Enum):
    SF = "sf"      # square feet (office, retail, industrial)
    UNIT = "unit"  # units (multifamily, self-storage)


class EscalationType(str, enum.Enum):
    FIXED_STEP = "fixed_step"     # explicit dollar amounts at specific dates
    PCT_ANNUAL = "pct_annual"     # X% per year on lease anniversary
    CPI = "cpi"                   # CPI-linked with floor/cap
    FLAT = "flat"                 # no escalation


class RecoveryType(str, enum.Enum):
    NNN = "nnn"                              # triple net: tenant pays all recoverable expenses
    FULL_SERVICE_GROSS = "full_service_gross"  # all expenses included in rent
    MODIFIED_GROSS = "modified_gross"         # tenant pays above expense stop/SF
    BASE_YEAR_STOP = "base_year_stop"         # tenant pays above base year expense level
    NONE = "none"                             # absolute net / no recovery


class ExpenseCategoryEnum(str, enum.Enum):
    REAL_ESTATE_TAXES = "real_estate_taxes"
    INSURANCE = "insurance"
    CAM = "cam"
    UTILITIES = "utilities"
    MANAGEMENT_FEE = "management_fee"
    REPAIRS_MAINTENANCE = "repairs_maintenance"
    GENERAL_ADMIN = "general_admin"
    OTHER = "other"


class UponExpiration(str, enum.Enum):
    MARKET = "market"        # probability-weighted renewal / new tenant
    RENEW = "renew"          # renews at market renewal terms (100%)
    VACATE = "vacate"        # vacates: downtime, then a new tenant
    OPTION = "option"        # exercises a contract renewal option, then market
    REABSORB = "reabsorb"    # space returns to vacancy and is not re-leased


class LeaseType(str, enum.Enum):
    IN_PLACE = "in_place"
    MARKET = "market"
    MONTH_TO_MONTH = "month_to_month"


class ValuationStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
