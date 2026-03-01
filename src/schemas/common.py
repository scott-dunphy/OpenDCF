import enum


class PropertyType(str, enum.Enum):
    MULTIFAMILY = "multifamily"
    SELF_STORAGE = "self_storage"
    OFFICE = "office"
    RETAIL = "retail"
    INDUSTRIAL = "industrial"
    MIXED_USE = "mixed_use"


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


class LeaseType(str, enum.Enum):
    IN_PLACE = "in_place"
    MARKET = "market"
    MONTH_TO_MONTH = "month_to_month"


class ValuationStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
