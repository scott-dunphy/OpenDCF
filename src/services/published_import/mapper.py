"""
Map XL4ADW / plain workbook sheets onto Ares import entities.

Sheets are recognized by their VIEW cell or sheet name (XL4ADW sheet names such
as PropertyAssets, Leases, MarketLeases, OperatingExpenses), falling back to
header content. Columns are matched to Ares fields through alias lists on the
normalized header, with and without its XL4ADW type suffix. Callers may supply
an explicit {sheet: {header: field}} mapping that takes precedence.

The full XL4ADW column list is not published; aliases cover the documented
names (e.g. MR_Amount_APM, TI_NewAmount_APM, FixedExpiryDate, FixedTerm_PD,
LeaseProfile_ExternalID, Amount1_APM) plus common rent-roll headers. Unmapped
columns are reported in the preview so the alias table can be extended.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.engine.assumption_overrides import PROFILE_FIELDS as ALL_FIELDS
from src.engine.date_utils import add_months
from src.schemas.imports import (
    ImportedAssumptionProfile,
    ImportedCapitalProject,
    ImportedExpense,
    ImportedLease,
    ImportedLoan,
    ImportedMarketProfile,
    ImportedOtherIncome,
    ImportedProperty,
    ImportedRentStep,
    ImportedSuite,
    ImportedValuation,
    ImportOptions,
    ImportPayload,
    SheetReport,
)
from src.schemas.portfolio import AssumptionValues
from src.services.published_import.timeseries import (
    parse_dated_list,
    parse_period_months,
    parse_series,
    to_decimal,
)
from src.services.published_import.workbook import Sheet, normalize

D = Decimal

# =========================================================================
# Sheet kinds and column aliases (all aliases are normalized: lowercase alnum)
# =========================================================================

SHEET_KINDS: dict[str, set[str]] = {
    "property": {"propertyassets", "propertyasset", "property", "properties", "assets", "propertyinfo"},
    "classification": {"propertyclassifications", "classifications"},
    "area": {"areameasures"},
    "lease": {"leases", "lease", "rentroll", "tenancyschedule", "tenants", "tenantrentroll"},
    "rent_schedule": {"rentschedules", "rentsteps", "rentschedule"},
    "market": {"marketleases", "marketleasing", "mla", "mlas", "leasingassumptions", "marketleasingprofiles"},
    "expense": {"operatingexpenses", "expenses", "opex"},
    "other_income": {"otherrevenues", "miscellaneousrevenues", "otherincome", "miscellaneousrents", "parkingrevenues"},
    "capital": {"capitalexpenses", "capex", "capitalprojects"},
    "vacancy": {"vacancies", "generalvacancy"},
    "credit_loss": {"creditlosses", "creditloss"},
    "inflation": {"inflationrates", "inflation"},
    "loan": {"loans", "debt", "debtfinancing"},
    "valuation": {"valuation", "valuations", "dcf", "sales", "resale", "acquisitioncostsdcf", "capitalizationyields"},
    "multifamily": {"multifamily", "unitmix", "multifamilyrents"},
    "storage": {"storagerevenues", "storage", "storageunits"},
    "assumption_profiles": {"assumptionprofiles", "assumptions", "portfolioassumptions"},
    "loan_tape": {"loantape", "mortgageloans", "mortgageloan", "loanbook", "commercialmortgages", "mortgages",
                  "loanportfolio", "loanholdings", "cmlportfolio"},
}

PROPERTY_REF = ["propertyexternalid", "propertyid", "property", "propertyname", "propertycode", "assetid"]

ALIASES: dict[str, dict[str, list[str]]] = {
    "property": {
        "external_id": PROPERTY_REF[:2] + ["externalid", "propertycode", "assetid", "id"],
        "name": ["name", "propertyname", "assetname"],
        "property_type": ["propertytype", "type", "usetype", "propertyusetype", "assettype", "propertytypeid"],
        "address_line1": ["address", "address1", "addressline1", "street", "streetaddress"],
        "city": ["city"],
        "state": ["state", "stateprovince", "province", "county"],
        "zip_code": ["zip", "zipcode", "postalcode", "postcode"],
        "market": ["market", "msa", "metro", "cbsa"],
        "analysis_start": ["analysisbegin", "analysisstart", "analysisbegindate", "analysisstartdate", "startdate"],
        "analysis_end_plus_one": ["analysisendplusone"],
        "analysis_months": ["analysislength", "analysisterm", "analysisperiod", "holdperiod", "analysisperiodmonths"],
        "total_area": ["buildingarea", "rentablearea", "totalarea", "nra", "gla", "netrentablearea", "area", "totalsf"],
        "area_unit": ["areaunit", "measure", "unitofmeasure", "areameasure"],
        "year_built": ["yearbuilt", "built"],
        "purchase_price": ["purchaseprice", "acquisitionprice", "price"],
        "portfolio_name": ["portfolioname", "portfolio", "fund"],
        "fiscal_year_end": ["fiscalyearend", "fiscalyearendmonth", "yearendmonth"],
    },
    "classification": {
        "property_ref": PROPERTY_REF,
        "name": ["name", "classification", "classificationname", "type", "category"],
        "value": ["value", "classificationvalue", "description", "item"],
    },
    "area": {
        "property_ref": PROPERTY_REF,
        "name": ["name", "areatype", "measure", "description"],
        "area": ["area", "amount", "value", "size"],
    },
    "lease": {
        "property_ref": PROPERTY_REF,
        "external_id": ["externalid", "leaseid", "leaseexternalid", "id"],
        "tenant_name": ["tenantname", "tenant", "name", "lessee", "occupant"],
        "suite": ["suite", "suitenumber", "suitename", "suiteid", "unit", "unitname", "unitnumber", "space", "spaceid"],
        "floor": ["floor", "level"],
        "area": ["area", "leasedarea", "sf", "rsf", "size", "rentablearea", "squarefeet", "nra"],
        "start": ["leasebegin", "leasestart", "begin", "begindate", "start", "startdate", "commencement",
                  "commencementdate", "leasecommencement", "leasestartdate", "leasebegindate"],
        "end": ["fixedexpirydate", "leaseend", "expiration", "expirationdate", "expiry", "expirydate", "end",
                "enddate", "leaseexpiration", "leaseenddate", "leaseexpirationdate"],
        "term": ["fixedterm", "term", "termlength", "leaseterm", "termmonths"],
        "base_rent": ["baserent", "rent", "currentrent", "baserentamount", "rentamount", "contractrent",
                      "baserentpersf", "rentpersf", "annualrentpersf", "currentbaserent", "inplacerent"],
        "rent_unit": ["baserentunit", "rentunit", "rentbasis", "amountunit", "baserentbasis"],
        "annual_rent_total": ["annualrent", "annualbaserent", "currentannualrent"],
        "monthly_rent_total": ["monthlyrent", "monthlybaserent", "currentmonthlyrent"],
        "lease_status": ["leasestatus", "status", "leasetype"],
        "upon_expiration": ["uponexpiration", "expirationaction", "onexpiration"],
        "market_profile": ["leaseprofile", "leaseprofileexternalid", "marketleasingprofile", "mla",
                           "marketleasing", "marketleasingassumption"],
        "recovery": ["recoverystructure", "recoverystructureextid", "recovery", "recoverymethod", "recoverytype",
                     "reimbursement", "reimbursementmethod", "recoveries"],
        "free_rent": ["rentfree", "freerent", "freerentmonths", "abatement", "abatementmonths"],
        "escalation_pct": ["annualincrease", "escalation", "escalationpct", "escalationrate", "increase",
                           "fixedincrease", "stepincrease", "annualescalation", "fixedsteps", "fssingleamount"],
        "cpi_floor": ["cpifloor", "cpiminimum", "cpimin"],
        "cpi_cap": ["cpicap", "cpimaximum", "cpimax"],
        "cpi_basis": ["cpitimingincreasebasislease", "cpi", "cpiincreases"],
        "pct_rent_rate": ["percentagerent", "prrate", "overagepercent", "prpercent", "percentagerentrate",
                          "prsalespercent"],
        "pct_rent_breakpoint": ["breakpoint", "prbreakpoint", "percentagerentbreakpoint"],
        "sales": ["prsalesamount", "sales", "salespersf", "annualsales", "salesamount"],
        "renewal_probability": ["renewalprobability", "renewprobability"],
        "base_year": ["baseyear"],
        "expense_stop": ["expensestop", "stoppersf", "expensestoppersf"],
        "pro_rata": ["prorata", "proratashare", "proratasharepct"],
        "space_type": ["spacetype", "usetype", "space"],
    },
    "rent_schedule": {
        "property_ref": PROPERTY_REF,
        "lease_ref": ["leaseexternalid", "lease", "leaseid", "tenant", "tenantname"],
        "date": ["begindate", "date", "effectivedate", "start", "startdate", "stepdate"],
        "rent": ["amount", "rent", "rentamount", "baserent", "rentpersf"],
        "unit": ["unit", "amountunit", "rentunit"],
    },
    "market": {
        "property_ref": PROPERTY_REF,
        "key": ["externalid", "id", "leaseprofileexternalid"],
        "name": ["name", "marketleasingprofile", "profilename", "leaseprofile", "mla", "spacetype", "description"],
        "market_rent": ["mramount", "marketrent", "newmarketrent", "newmktrent", "mrnewamount"],
        "renewal_market_rent": ["mrrenewamount", "renewmarketrent", "renewmktrent"],
        "rent_unit": ["mrunit", "marketrentunit"],
        "rent_growth": ["mrinflation", "marketrentgrowth", "rentgrowth", "marketrentinflation"],
        "term": ["termlength", "term", "leaseterm", "newterm", "termmonths"],
        "renewal_term": ["renewterm", "renewalterm"],
        "renewal_probability": ["renewalprobability", "renewprobability", "renewal", "renewpct"],
        "downtime": ["monthsvacant", "downtime", "downtimemonths", "vacantmonths"],
        "ti_new": ["tinewamount", "newti", "tinew", "tenantimprovementsnew", "newtenantimprovements"],
        "ti_renew": ["tirenewamount", "renewti", "tirenew", "tenantimprovementsrenew"],
        "lc_new": ["amount", "lcnew", "newlc", "lcnewamount", "leasingcommissionnew", "newleasingcommission"],
        "lc_renew": ["renewamount", "lcrenew", "renewlc", "lcrenewamount", "leasingcommissionrenew"],
        "free_rent_new": ["rfamount", "freerentnew", "newfreerent", "freerent", "rfnewamount"],
        "free_rent_renew": ["rfrenewamount", "freerentrenew", "renewfreerent"],
        "general_vacancy": ["generalvacancy", "vacancy", "vacancypct"],
        "credit_loss": ["creditloss", "creditlosspct"],
        "renewal_rent_adjustment": ["renewalrentadjustment", "renewaladjustment"],
    },
    "expense": {
        "property_ref": PROPERTY_REF,
        "name": ["name", "expense", "account", "category", "description", "expensename", "lineitem"],
        "amount": ["amount1", "amount", "annualamount", "year1amount", "budget", "annual", "year1"],
        "unit": ["unit", "amountunit", "expenseunit", "basis", "expensebasis", "unitofmeasure"],
        "growth": ["amount1inflation", "inflation", "growth", "growthrate", "inflationrate"],
        "recoverable": ["isrecoverable", "recoverable"],
        "gross_up_pct": ["grossup", "grossuppct", "grossupoccupancy", "grossuppercent"],
    },
    "other_income": {
        "property_ref": PROPERTY_REF,
        "name": ["name", "revenue", "account", "category", "description", "lineitem"],
        "amount": ["amount1", "amount", "annualamount", "year1amount", "annual", "year1"],
        "unit": ["unit", "amountunit", "basis"],
        "growth": ["amount1inflation", "inflation", "growth", "growthrate"],
    },
    "capital": {
        "property_ref": PROPERTY_REF,
        "name": ["name", "description", "project", "account", "item"],
        "amount": ["amount1", "amount", "totalamount", "cost", "budget", "values"],
        "start": ["startdate", "start", "begindate", "date"],
        "duration": ["duration", "durationmonths", "months", "term"],
    },
    "vacancy": {
        "property_ref": PROPERTY_REF,
        "rate": ["rate", "percent", "generalvacancy", "vacancy", "vacancypct", "amount", "vacancyrate", "value"],
    },
    "credit_loss": {
        "property_ref": PROPERTY_REF,
        "rate": ["rate", "percent", "creditloss", "creditlosspct", "amount", "value"],
    },
    "inflation": {
        "property_ref": PROPERTY_REF,
        "name": ["name", "inflationname", "description", "type"],
        "rate": ["rate", "inflation", "inflationrate", "rates", "amount", "value", "values"],
    },
    "loan": {
        "property_ref": PROPERTY_REF,
        "amount": ["amount", "principal", "loanamount", "initialprincipal", "proceeds"],
        "rate": ["interestrate", "rate", "interest", "couponrate"],
        "amortization": ["amortization", "amortizationterm", "amortizationperiod", "amortizationmonths"],
        "term": ["term", "loanterm", "maturity", "termmonths", "loantermmonths"],
        "io": ["interestonly", "ioperiod", "interestonlyperiod", "iomonths"],
        "fees": ["loanfees", "fees", "points", "originationfee", "loanfeepct"],
        "name": ["loanname", "name", "description", "lender"],
    },
    "valuation": {
        "property_ref": PROPERTY_REF,
        "discount_rate": ["discountrate", "unleverageddiscountrate", "pvrate", "discount", "targetirr"],
        "exit_cap_rate": ["exitcaprate", "resalecaprate", "terminalcaprate", "reversionarycaprate", "caprate",
                          "exitcap", "capitalizationrate", "saleyield", "exityield"],
        "exit_costs": ["sellingcosts", "costofsale", "exitcosts", "salecosts", "sellingcost", "costsofsale"],
        "purchase_price": ["purchaseprice", "acquisitionprice"],
    },
    "multifamily": {
        "property_ref": PROPERTY_REF,
        "name": ["name", "unittype", "floorplan", "type", "description", "plan"],
        "units": ["units", "numberofunits", "unitcount", "count", "nounits", "totalunits"],
        "market_rent": ["marketrent", "mramount", "rent", "marketrentperunit"],
        "current_rent": ["currentrent", "inplacerent", "avgrent", "contractrent", "averagerent"],
        "occupancy": ["occupancy", "occupancypct", "occupied"],
        "vacancy": ["vacancy", "vacancypct"],
        "growth": ["rentgrowth", "growth", "mrinflation", "inflation"],
        "turnover_cost": ["turnovercost", "makeready", "turncost", "tiamount", "tinewamount"],
        "concession_months": ["concessions", "concessionmonths", "freerent", "rfamount"],
        "renewal_probability": ["renewalprobability", "retention", "renewprobability"],
        "term": ["leaseterm", "term", "termlength"],
        "downtime": ["downtime", "monthsvacant", "downtimemonths"],
    },
}
# Reference sheets of the assumptions library template: not data, so no "not recognized" warning
REFERENCE_SHEETS = {"readme", "fields", "cbsas"}

ALIASES["storage"] = {
    **ALIASES["multifamily"],
    "name": ["name", "unittype", "unitsize", "size", "type", "description", "dimensions"],
    "units": ["units", "numberofunits", "unitcount", "count", "nounits", "totalunits", "totalunitcount"],
    "market_rent": ["streetrate", "streetrent", "askingrent", "webrate", "marketrent", "rent", "standardrate"],
    "current_rent": ["inplacerent", "currentrent", "avgrent", "averagerent", "inplacerate", "actualrent"],
    "occupied_units": ["occupiedunits", "unitsoccupied", "rentedunits", "occupiedcount", "rented"],
    "sf_per_unit": ["sfperunit", "unitsf", "squarefeet", "sqft", "sf", "unitarea", "area"],
    "width": ["width"],
    "depth": ["depth", "length"],
    "climate": ["climatecontrolled", "climate", "cc", "heated"],
}

# A lender's loan tape (not XL4ADW, which has no lender view). Period columns accept
# months, "5Y0M0W0D" or "5 years"; headers mentioning years are read as years.
ALIASES["loan_tape"] = {
    "external_id": ["loanid", "loannumber", "loanno", "loanexternalid", "loancode", "externalid", "loan", "id"],
    "property_ref": ["propertyexternalid", "propertyid", "propertycode", "assetid", "collateralid"],
    "property_name": ["propertyname", "property", "collateral", "collateralname", "assetname"],
    "property_type": ["propertytype", "collateraltype", "assettype", "type", "usetype"],
    "market": ["market", "msa", "metro", "cbsa", "submarket"],
    "address_line1": ["address", "propertyaddress", "streetaddress", "street", "address1"],
    "city": ["city"],
    "state": ["state", "stateprovince"],
    "zip_code": ["zip", "zipcode", "postalcode"],
    "total_area": ["nra", "netrentablearea", "rentablearea", "squarefeet", "sf", "totalsf", "totalarea", "area",
                   "units", "unitcount", "numberofunits"],
    "name": ["loanname", "dealname", "name"],
    "portfolio_name": ["portfolioname", "portfolio", "fund"],
    "lien_position": ["lienposition", "lien", "position", "priority", "notetype", "tranche"],
    "sponsor": ["sponsor", "borrower", "borrowername", "guarantor"],
    "recourse": ["recourse", "isrecourse"],
    "origination_date": ["originationdate", "origdate", "closingdate", "fundingdate", "notedate", "origination"],
    "original_balance": ["originalbalance", "originalloanamount", "originalamount", "origbalance", "loanamount",
                         "commitment", "originalprincipal"],
    "maturity_date": ["maturitydate", "initialmaturitydate", "maturity"],
    "rate_type": ["ratetype", "interestratetype", "fixedfloating", "fixfloat", "fixedorfloating"],
    "coupon": ["coupon", "noterate", "interestrate", "fixedrate", "rate", "allinrate"],
    "index_name": ["index", "rateindex", "benchmark"],
    "spread": ["spread", "margin", "floatingspread"],
    "index_floor": ["indexfloor", "floor", "sofrfloor"],
    "index_cap": ["indexcap", "ratecap", "capstrike", "cap"],
    "amortization_months": ["amortizationmonths", "amortization", "amortizationterm", "amortterm", "amort",
                            "amortizationyears", "amortizationperiod"],
    "io_months": ["iomonths", "interestonly", "ioperiod", "interestonlyperiod", "io", "ioyears",
                  "interestonlymonths"],
    "extension_count": ["extensions", "extensionoptions", "numberofextensions", "extensioncount"],
    "extension_months": ["extensionmonths", "extensionterm", "extensionlength", "extensionperiod"],
    "reported_balance": ["currentbalance", "outstandingbalance", "upb", "unpaidprincipalbalance",
                         "principalbalance", "balance", "currentprincipal"],
    "balance_as_of_date": ["asofdate", "balanceasofdate", "balancedate", "reportdate", "asof", "reportingdate"],
    "delinquency_status": ["delinquencystatus", "delinquency", "paymentstatus", "loanstatus", "status"],
    "origination_value": ["originationvalue", "originalappraisedvalue", "origvalue", "appraisedvalueatorigination",
                          "origappraisal", "originalvalue"],
    "origination_noi": ["originationnoi", "underwrittennoi", "uwnoi", "originalnoi"],
    "tape_noi": ["currentnoi", "mostrecentnoi", "ttmnoi", "t12noi", "annualnoi", "noi"],
    "tape_value": ["currentvalue", "mostrecentvalue", "currentappraisedvalue", "appraisedvalue", "marketvalue",
                   "value"],
    "tape_value_date": ["valuedate", "appraisaldate", "valuationdate", "currentvaluedate"],
    "tape_occupancy": ["occupancy", "currentoccupancy", "physicaloccupancy"],
    "tape_noi_growth": ["noigrowth", "noigrowthrate"],
    "tape_exit_cap_rate": ["exitcap", "exitcaprate", "terminalcaprate", "residualcaprate"],
}
LOAN_TAPE_SIGNATURE = (
    set(ALIASES["loan_tape"]["origination_date"]),
    set(ALIASES["loan_tape"]["maturity_date"]),
    set(ALIASES["loan_tape"]["original_balance"]) | set(ALIASES["loan_tape"]["reported_balance"]),
)
_DELINQUENCY = [
    ("foreclos", "foreclosure"), ("reo", "reo"), ("90", "90_plus"), ("120", "90_plus"),
    ("60", "60"), ("30", "30"), ("current", "current"), ("perform", "current"),
]

PROPERTY_TYPE_KEYWORDS = [
    ("selfstorage", "self_storage"), ("storage", "self_storage"),
    ("multifamily", "multifamily"), ("apartment", "multifamily"), ("residential", "multifamily"),
    ("seniors", "seniors_housing"), ("senior", "seniors_housing"),
    ("marina", "marina"),
    ("mixed", "mixed_use"),
    ("industrial", "industrial"), ("warehouse", "industrial"), ("flex", "industrial"),
    ("logistics", "industrial"), ("distribution", "industrial"),
    ("retail", "retail"), ("shopping", "retail"), ("mall", "retail"),
    ("office", "office"), ("medical", "office"),
]

EXPENSE_CATEGORY_KEYWORDS = [
    ("tax", "real_estate_taxes"), ("insur", "insurance"),
    ("manage", "management_fee"), ("mgmt", "management_fee"),
    ("util", "utilities"), ("electric", "utilities"), ("water", "utilities"), ("gas", "utilities"),
    ("repair", "repairs_maintenance"), ("rm", "repairs_maintenance"),
    ("cam", "cam"), ("commonarea", "cam"), ("janitor", "cam"), ("landscap", "cam"), ("snow", "cam"),
    ("security", "cam"), ("maint", "cam"), ("clean", "cam"),
    ("admin", "general_admin"), ("ga", "general_admin"), ("general", "general_admin"),
]


# =========================================================================
# Helpers
# =========================================================================

@dataclass
class BoundSheet:
    """A sheet with its recognized kind and the header chosen for each field."""
    sheet: Sheet
    kind: str | None
    fields: dict[str, str] = field(default_factory=dict)   # field -> header
    suffixes: dict[str, str | None] = field(default_factory=dict)

    def get(self, row: dict, name: str):
        h = self.fields.get(name)
        return row.get(h) if h else None

    def suffix(self, name: str) -> str | None:
        return self.suffixes.get(name)

    def has(self, name: str) -> bool:
        return name in self.fields


def _text(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if isinstance(v, float) and v.is_integer():
        s = str(int(v))
    return s or None


def _date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %Y", "%Y/%m", "%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:  # Excel serial date
        return date(1899, 12, 30) + timedelta(days=int(v))
    return None


def _bool(v) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "yes", "y", "1", "x"):
        return True
    if s in ("false", "no", "n", "0"):
        return False
    return None


def _rate(v, suffix: str | None = None, share: bool = False) -> Decimal | None:
    """
    Fraction from a cell: series -> first value; 5 -> 0.05 when it looks like a percent.
    A rate of 1 is 1%; a share (probability, pro rata, occupancy) of 1 is 100%.
    """
    if v is None or v == "":
        return None
    d = parse_series(v, suffix).first() if (suffix or (isinstance(v, str) and ";" in v)) else to_decimal(v)
    if d is None:
        return None
    return d / D(100) if (d > 1 if share else d >= 1) else d


def _rate_schedule(v, suffix: str | None = None, share: bool = False) -> list[Decimal]:
    """Year-by-year rates from a yearly series (_AEY/_APY) with more than one entry, else [].
    Scaled as _rate does: a rate of 1 is 1%, a share of 1 is 100%."""
    return [d / D(100) if (d > 1 if share else d >= 1) else d for d in _number_schedule(v, suffix)]


# Accepted range of each by-year market profile value (schemas/market.py)
_SCHEDULE_BOUNDS: dict[str, tuple[Decimal, Decimal]] = {
    "rent_growth_schedule": (D(-1), D(1)),
    "general_vacancy_schedule": (D(0), D(1)),
    "credit_loss_schedule": (D(0), D(1)),
    "renewal_probability_schedule": (D(0), D(1)),
    "downtime_schedule": (D(0), D(120)),
    "new_free_rent_schedule": (D(0), D(120)),
    "renewal_free_rent_schedule": (D(0), D(120)),
}


def _number_schedule(v, suffix: str | None = None) -> list[Decimal]:
    """Year-by-year values from a yearly series (_AEY/_APY) with more than one entry, else []."""
    if suffix not in ("_AEY", "_APY") or v is None or v == "":
        return []
    values = parse_series(v, suffix).values
    return values if len(values) >= 2 else []


def _number(v, suffix: str | None = None) -> Decimal | None:
    if v is None or v == "":
        return None
    if suffix or (isinstance(v, str) and (";" in v or "|" in v)):
        return parse_series(v, suffix).first()
    return to_decimal(v)


def _months(v) -> int | None:
    return parse_period_months(v)


_UPON_EXPIRATION = [
    ("reabsorb", "reabsorb"), ("vacate", "vacate"), ("option", "option"), ("renew", "renew"), ("market", "market"),
]


def _keyword_map(value: str | None, table: list[tuple[str, str]]) -> str | None:
    if not value:
        return None
    n = normalize(value)
    for kw, mapped in table:
        if kw in n:
            return mapped
    return None


def map_property_type(value: str | None, default: str) -> str:
    return _keyword_map(value, PROPERTY_TYPE_KEYWORDS) or default


def map_expense_category(name: str) -> str:
    n = normalize(name)
    for kw, cat in EXPENSE_CATEGORY_KEYWORDS:
        if (kw in ("rm", "ga") and n == kw) or (kw not in ("rm", "ga") and kw in n):
            return cat
    return name.strip()[:50] or "other"


def map_recovery(value: str | None, property_type: str) -> tuple[str, bool]:
    """(recovery_type, was_defaulted)."""
    n = normalize(value or "")
    if n:
        if "modified" in n:
            return "modified_gross", False
        if "baseyear" in n or "stop" in n or n.startswith("by"):
            return "base_year_stop", False
        if "fullservice" in n or n in ("fsg", "gross", "fullgross") or "grossfull" in n:
            return "full_service_gross", False
        if "net" in n or "nnn" in n or "triple" in n or "prorata" in n:
            return "nnn", False
        if n in ("none", "absolute", "absolutenet"):
            return "none", False
        if "gross" in n:
            return "full_service_gross", False
    return ("base_year_stop" if property_type == "office" else "nnn"), True


def _looks_like_loan_tape(headers: set[str]) -> bool:
    return all(headers & names for names in LOAN_TAPE_SIGNATURE)


def classify_sheet(sheet: Sheet) -> str | None:
    headers = {c.base for c in sheet.columns} | {normalize(c.header) for c in sheet.columns}
    for candidate in (normalize(sheet.view or ""), normalize(sheet.name)):
        for kind, names in SHEET_KINDS.items():
            if candidate in names:
                # A plain sheet called "Loans" with origination/maturity/balance columns is a
                # lender's loan tape; XL4ADW Loans sheets are the owner's property-level debt
                if kind == "loan" and not sheet.is_xl4adw and _looks_like_loan_tape(headers):
                    return "loan_tape"
                return kind
    if _looks_like_loan_tape(headers):
        return "loan_tape"
    if headers & set(ALIASES["lease"]["start"]) and headers & set(ALIASES["lease"]["tenant_name"]):
        return "lease"
    if headers & set(ALIASES["market"]["market_rent"]) and headers & set(ALIASES["market"]["downtime"]):
        return "market"
    return None


def bind_sheet(sheet: Sheet, mapping: dict[str, str] | None = None) -> BoundSheet:
    kind = classify_sheet(sheet)
    bound = BoundSheet(sheet=sheet, kind=kind)
    if kind is None:
        return bound
    aliases = ALIASES.get(kind, {})
    if kind == "assumption_profiles":
        aliases = {
            "name": ["name", "profilename", "profile"],
            "portfolio_name": ["portfolio", "portfolioname", "fund"],
            "property_type": ["propertytype", "type", "usetype"],
            "market": ["market", "msa", "metro"],
            "cbsa_code": ["cbsacode", "cbsa"],
            "state": ["state"],
            "quality_score": ["qualityscore", "quality"],
            "as_of": ["asof", "asofdate", "vintage"],
            "source": ["source"],
            "comment": ["comment", "comments", "notes"],
            **{f: [normalize(f) + "base", normalize(f)] for f in ALL_FIELDS},
            **{f"{f}__low": [normalize(f) + "low"] for f in ALL_FIELDS},
            **{f"{f}__high": [normalize(f) + "high"] for f in ALL_FIELDS},
        }
    taken: set[str] = set()
    for header, target in (mapping or {}).items():
        col = next((c for c in sheet.columns if c.header == header), None)
        if col is not None and target:
            bound.fields[target] = col.header
            bound.suffixes[target] = col.suffix
            taken.add(col.header)
    for fname, names in aliases.items():
        if fname in bound.fields:
            continue
        for alias in names:  # alias order = priority
            col = next(
                (c for c in sheet.columns
                 if c.header not in taken and (normalize(c.header) == alias or c.base == alias)),
                None,
            )
            if col is not None:
                bound.fields[fname] = col.header
                bound.suffixes[fname] = col.suffix
                taken.add(col.header)
                break
    return bound


def sheet_report(b: BoundSheet) -> SheetReport:
    mapped = {h: f for f, h in b.fields.items()}
    return SheetReport(
        sheet=b.sheet.name,
        view=b.sheet.view,
        format="xl4adw" if b.sheet.is_xl4adw else "plain",
        recognized_as=b.kind,
        rows=len(b.sheet.rows),
        mapped_columns=mapped,
        unmapped_columns=[c.header for c in b.sheet.columns if c.header not in mapped] if b.kind else [],
    )


def _first_of_next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _rent_to_per_unit_year(
    rent: Decimal, unit: str | None, area: Decimal, residential: bool
) -> tuple[Decimal, str]:
    """
    Convert a rent amount to Ares conventions: $/SF/yr (commercial) or $/unit/mo
    (residential). Returns (rent, rent_payment_frequency).
    """
    u = normalize(unit or "")
    per_area = "area" in u or "sf" in u or "sqft" in u or "squarefoot" in u or "persf" in u
    monthly = "month" in u or "mo" == u or u.endswith("mo")
    if residential:
        if u and not per_area and not monthly and ("year" in u or "annual" in u):
            return rent / D(12), "monthly"
        return rent, "monthly"
    if not u:
        return rent, "annual"
    if per_area:
        return (rent * D(12) if monthly else rent), "annual"
    # Total-dollar units ("$ Amount", "$/Month", "$/Year")
    if area <= 0:
        return rent, "annual"
    total_annual = rent * D(12) if monthly else rent
    return total_annual / area, "annual"


# =========================================================================
# Build payload
# =========================================================================

@dataclass
class _PropAccumulator:
    prop: ImportedProperty
    explicit_area: bool = False
    suites: dict[str, ImportedSuite] = field(default_factory=dict)

    def area(self) -> Decimal | None:
        if self.prop.total_area:
            return self.prop.total_area
        total = sum((s.area for s in self.suites.values()), D(0))
        return total or None


class ImportMapper:
    def __init__(self, sheets: list[Sheet], options: ImportOptions, filename: str = "import"):
        self.options = options
        self.filename = filename
        self.bound = [bind_sheet(s, options.column_mapping.get(s.name)) for s in sheets]
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.props: dict[str, _PropAccumulator] = {}
        self._name_index: dict[str, str] = {}

    # -- property resolution ------------------------------------------------

    def _default_start(self) -> date:
        return self.options.analysis_start_date or _first_of_next_month(date.today())

    def _new_property(self, external_id: str, name: str | None = None) -> _PropAccumulator:
        acc = _PropAccumulator(prop=ImportedProperty(
            external_id=external_id,
            name=name or external_id,
            property_type=self.options.default_property_type,
            analysis_start_date=self._default_start(),
            analysis_period_months=self.options.analysis_period_months,
        ))
        self.props[external_id] = acc
        self._name_index[normalize(acc.prop.name)] = external_id
        return acc

    def _prop_for_row(self, b: BoundSheet, row: dict) -> _PropAccumulator:
        ref = _text(b.get(row, "property_ref"))
        if ref:
            if ref in self.props:
                return self.props[ref]
            by_name = self._name_index.get(normalize(ref))
            if by_name:
                return self.props[by_name]
            return self._new_property(ref)
        if len(self.props) == 1:
            return next(iter(self.props.values()))
        if not self.props:
            stem = self.filename.rsplit(".", 1)[0] or "Imported Property"
            return self._new_property(stem, stem)
        # Several properties and no reference column: attach to the first, with a warning
        self.warnings.append(f"{b.sheet.name}: no property reference column; rows assigned to first property")
        return next(iter(self.props.values()))

    # -- sheet handlers -----------------------------------------------------

    def _properties(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            ext = _text(b.get(row, "external_id")) or _text(b.get(row, "name"))
            if not ext:
                continue
            acc = self.props.get(ext) or self._new_property(ext, _text(b.get(row, "name")))
            p = acc.prop
            if _text(b.get(row, "name")):
                p.name = _text(b.get(row, "name"))
                self._name_index[normalize(p.name)] = ext
            raw_type = _text(b.get(row, "property_type"))
            p.property_type = map_property_type(raw_type, self.options.default_property_type)
            if raw_type and not _keyword_map(raw_type, PROPERTY_TYPE_KEYWORDS):
                p.warnings.append(f"Property type '{raw_type}' not recognized; using {p.property_type}")
            for attr in ("address_line1", "city", "state", "zip_code", "market", "portfolio_name"):
                val = _text(b.get(row, attr))
                if val:
                    setattr(p, attr, val)
            start = _date(b.get(row, "analysis_start"))
            if start and start.day != 1:
                p.warnings.append(f"Analysis start {start} moved to the first of the next month")
                start = _first_of_next_month(start)
            if start:
                p.analysis_start_date = start
            end_plus_one = _date(b.get(row, "analysis_end_plus_one"))
            months = _months(b.get(row, "analysis_months"))
            if end_plus_one and start:
                months = (end_plus_one.year - start.year) * 12 + end_plus_one.month - start.month
            if months:
                if months % 12:
                    # No stub years: extend a partial final year to a whole year
                    p.warnings.append(f"Analysis period of {months} months extended to {-(-months // 12)} whole years")
                    months = -(-months // 12) * 12
                p.analysis_period_months = max(12, min(360, months))
            area = _number(b.get(row, "total_area"), b.suffix("total_area"))
            if area and area > 0:
                p.total_area = area
                acc.explicit_area = True
            unit = normalize(_text(b.get(row, "area_unit")) or "")
            if unit in ("unit", "units"):
                p.area_unit = "unit"
            yb = _number(b.get(row, "year_built"))
            if yb and 1800 <= yb <= 2100:
                p.year_built = int(yb)
            fy = _number(b.get(row, "fiscal_year_end"))
            if fy and 1 <= fy <= 12:
                p.fiscal_year_end_month = int(fy)
            price = _number(b.get(row, "purchase_price"))
            if price and price > 0:
                p.valuation = p.valuation or ImportedValuation()
                p.valuation.purchase_price = price

    def _classifications(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            name = normalize(_text(b.get(row, "name")) or "")
            value = _text(b.get(row, "value"))
            if value and name in ("market", "msa", "metro", "cbsa"):
                self._prop_for_row(b, row).prop.market = value

    def _areas(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            if acc.explicit_area:
                continue
            name = normalize(_text(b.get(row, "name")) or "")
            area = _number(b.get(row, "area"), b.suffix("area"))
            if area and area > 0 and ("building" in name or "rentable" in name or not name):
                acc.prop.total_area = area
                acc.explicit_area = True

    def _market_profiles(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            name = _text(b.get(row, "name"))
            key = _text(b.get(row, "key")) or name
            rent = _number(b.get(row, "market_rent"), b.suffix("market_rent"))
            if not key or rent is None:
                continue
            mp = ImportedMarketProfile(key=key, space_type=(name or key)[:100], market_rent_per_unit=rent)
            residential = acc.prop.property_type in ("multifamily", "self_storage")
            unit = _text(b.get(row, "rent_unit"))
            if unit:
                mp.market_rent_per_unit, _ = _rent_to_per_unit_year(rent, unit, D(1), residential)
            g = _rate(b.get(row, "rent_growth"), b.suffix("rent_growth"))
            if g is not None:
                mp.rent_growth_rate_pct = g
            mp.rent_growth_schedule = _rate_schedule(b.get(row, "rent_growth"), b.suffix("rent_growth"))
            term = _months(b.get(row, "term"))
            if term:
                mp.new_lease_term_months = term
                mp.renewal_lease_term_months = term
            rterm = _months(b.get(row, "renewal_term"))
            if rterm:
                mp.renewal_lease_term_months = rterm
            rp = _rate(b.get(row, "renewal_probability"), b.suffix("renewal_probability"), share=True)
            if rp is not None:
                mp.renewal_probability = rp
            mp.renewal_probability_schedule = _rate_schedule(
                b.get(row, "renewal_probability"), b.suffix("renewal_probability"), share=True)
            dt = _number(b.get(row, "downtime"), b.suffix("downtime"))
            if dt is not None:
                mp.downtime_months = int(dt)
            mp.downtime_schedule = [int(d) for d in _number_schedule(b.get(row, "downtime"), b.suffix("downtime"))]
            for fld, attr in (("ti_new", "new_tenant_ti_per_sf"), ("ti_renew", "renewal_ti_per_sf")):
                v = _number(b.get(row, fld), b.suffix(fld))
                if v is not None:
                    setattr(mp, attr, v)
            for fld, attr in (("lc_new", "new_tenant_lc_pct"), ("lc_renew", "renewal_lc_pct")):
                v = _number(b.get(row, fld), b.suffix(fld))
                if v is None:
                    continue
                if v > 1 and v <= 100:
                    v = v / D(100)
                if v > 1:
                    acc.prop.warnings.append(
                        f"MLA '{key}': leasing commission {v} is not a percentage; kept default"
                    )
                    continue
                setattr(mp, attr, v)
            for fld, attr, sched in (("free_rent_new", "new_tenant_free_rent_months", "new_free_rent_schedule"),
                                     ("free_rent_renew", "renewal_free_rent_months", "renewal_free_rent_schedule")):
                v = _number(b.get(row, fld), b.suffix(fld))
                if v is not None:
                    setattr(mp, attr, int(v))
                setattr(mp, sched, _number_schedule(b.get(row, fld), b.suffix(fld)))
            renew_rent = _number(b.get(row, "renewal_market_rent"), b.suffix("renewal_market_rent"))
            if renew_rent and rent:
                mp.renewal_rent_adjustment_pct = renew_rent / rent - D(1)
            adj = _rate(b.get(row, "renewal_rent_adjustment"))
            if adj is not None:
                mp.renewal_rent_adjustment_pct = adj
            for fld, attr, sched in (("general_vacancy", "general_vacancy_pct", "general_vacancy_schedule"),
                                     ("credit_loss", "credit_loss_pct", "credit_loss_schedule")):
                v = _rate(b.get(row, fld), b.suffix(fld))
                if v is not None:
                    setattr(mp, attr, v)
                setattr(mp, sched, _rate_schedule(b.get(row, fld), b.suffix(fld)))
            acc.prop.market_profiles.append(mp)

    def _leases(self, b: BoundSheet) -> None:
        for i, row in enumerate(b.sheet.rows, start=1):
            acc = self._prop_for_row(b, row)
            p = acc.prop
            where = f"{b.sheet.name} row {i}"
            suite = _text(b.get(row, "suite"))
            tenant = _text(b.get(row, "tenant_name"))
            area = _number(b.get(row, "area"), b.suffix("area"))
            if not suite and not tenant:
                continue
            suite = suite or tenant
            if area is None or area <= 0:
                existing = acc.suites.get(suite)
                if existing is None:
                    p.warnings.append(f"{where}: no area for '{suite}'; skipped")
                    continue
                area = existing.area

            space_type = _text(b.get(row, "space_type")) or _text(b.get(row, "market_profile")) or p.property_type
            if suite not in acc.suites:
                floor = _number(b.get(row, "floor"))
                acc.suites[suite] = ImportedSuite(
                    suite_name=suite[:100], area=area, space_type=space_type[:100],
                    floor=int(floor) if floor is not None else None,
                )

            status = normalize(_text(b.get(row, "lease_status")) or "")
            if tenant is None or normalize(tenant) in ("vacant", "available", "") or status == "vacant":
                continue  # vacant suite: no lease

            start = _date(b.get(row, "start"))
            end = _date(b.get(row, "end"))
            term = _months(b.get(row, "term"))
            if start and not end and term:
                end = add_months(start, term) - timedelta(days=1)
            if not start or not end:
                p.warnings.append(f"{where}: '{tenant}' missing lease start/end; lease skipped (suite kept)")
                continue

            residential = p.property_type in ("multifamily", "self_storage")
            rent_cell = b.get(row, "base_rent")
            rent = _number(rent_cell, b.suffix("base_rent"))
            unit = _text(b.get(row, "rent_unit"))
            if rent is None:
                total = _number(b.get(row, "annual_rent_total"))
                monthly = _number(b.get(row, "monthly_rent_total"))
                if total is not None:
                    rent, unit = total, "$/year"
                elif monthly is not None:
                    rent, unit = monthly, "$/month"
            if rent is None:
                p.warnings.append(f"{where}: '{tenant}' has no base rent; lease skipped")
                continue
            rent_per_unit, freq = _rent_to_per_unit_year(rent, unit, area, residential)

            lease = ImportedLease(
                external_id=_text(b.get(row, "external_id")),
                suite_name=suite[:100],
                tenant_name=tenant[:255],
                lease_start_date=start,
                lease_end_date=end,
                base_rent_per_unit=rent_per_unit,
                rent_payment_frequency=freq,
                upon_expiration=_keyword_map(_text(b.get(row, "upon_expiration")), _UPON_EXPIRATION),
                market_profile_key=_text(b.get(row, "market_profile")),
            )
            if "speculative" in status:
                lease.lease_type = "market"
            if "monthtomonth" in status or "mtm" == status:
                lease.lease_type = "month_to_month"

            # Base rent series on an APCL/APUL column carries the rent steps directly
            if isinstance(rent_cell, str) and "|" in rent_cell:
                series = parse_series(rent_cell, b.suffix("base_rent") or "_APCL")
                prev = None
                for m_idx, val in enumerate(series.values):
                    if val != prev:
                        step_rent, _ = _rent_to_per_unit_year(val, unit, area, residential)
                        lease.rent_steps.append(ImportedRentStep(
                            effective_date=add_months(start, m_idx), rent_per_unit=step_rent,
                        ))
                        prev = val
                if lease.rent_steps:
                    lease.base_rent_per_unit = lease.rent_steps[0].rent_per_unit
                    lease.escalation_type = "fixed_step" if len(lease.rent_steps) > 1 else "flat"

            esc = _rate(b.get(row, "escalation_pct"), b.suffix("escalation_pct"))
            if esc and lease.escalation_type == "flat":
                lease.escalation_type = "pct_annual"
                lease.escalation_pct_annual = esc
            cpi_basis = normalize(_text(b.get(row, "cpi_basis")) or "")
            if cpi_basis and cpi_basis not in ("none", "false", "no", "0"):
                lease.escalation_type = "cpi"
                lease.cpi_floor = _rate(b.get(row, "cpi_floor"))
                lease.cpi_cap = _rate(b.get(row, "cpi_cap"))

            rec_raw = _text(b.get(row, "recovery"))
            lease.recovery_type, defaulted = map_recovery(rec_raw, p.property_type)
            if residential:
                lease.recovery_type = "none"
            elif defaulted:
                p.warnings.append(
                    f"{where}: recovery '{rec_raw or 'blank'}' not recognized; using {lease.recovery_type}"
                )
            by = _number(b.get(row, "base_year"))
            if by and 1900 < by < 2200:
                lease.base_year = int(by)
            stop = _number(b.get(row, "expense_stop"))
            if stop is not None:
                lease.expense_stop_per_sf = stop
            prs = _rate(b.get(row, "pro_rata"), share=True)
            if prs is not None:
                lease.pro_rata_share_pct = prs

            fr_cell = b.get(row, "free_rent")
            if fr_cell not in (None, ""):
                if isinstance(fr_cell, str) and ("|" in fr_cell or ";" in fr_cell):
                    series = parse_series(fr_cell, b.suffix("free_rent") or "_APUL")
                    months = 0
                    for val in series.values:
                        if val > 0:
                            months += 1
                        else:
                            break
                    lease.free_rent_months = months
                else:
                    lease.free_rent_months = int(_number(fr_cell) or 0)

            rate = _rate(b.get(row, "pct_rent_rate"))
            if rate:
                lease.pct_rent_rate = rate
                lease.pct_rent_breakpoint = _number(b.get(row, "pct_rent_breakpoint"))
                sales = _number(b.get(row, "sales"), b.suffix("sales"))
                if sales is not None:
                    # XL4ADW sales amounts are monthly series; per-SF figures stay as-is
                    lease.projected_annual_sales_per_sf = (
                        sales * D(12) / area if b.suffix("sales") == "_APM" and area else sales
                    )
            rp = _rate(b.get(row, "renewal_probability"), share=True)
            if rp is not None:
                lease.renewal_probability = rp
            p.leases.append(lease)

    def _rent_schedules(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            ref = _text(b.get(row, "lease_ref"))
            eff = _date(b.get(row, "date"))
            rent = _number(b.get(row, "rent"))
            if not ref or not eff or rent is None:
                continue
            lease = next(
                (l for l in acc.prop.leases if l.external_id == ref or (l.tenant_name or "") == ref), None
            )
            if lease is None:
                acc.prop.warnings.append(f"{b.sheet.name}: rent step for unknown lease '{ref}'")
                continue
            suite = acc.suites.get(lease.suite_name)
            area = suite.area if suite else D(1)
            per_unit, _ = _rent_to_per_unit_year(
                rent, _text(b.get(row, "unit")), area, acc.prop.property_type in ("multifamily", "self_storage")
            )
            lease.rent_steps.append(ImportedRentStep(effective_date=eff, rent_per_unit=per_unit))
            lease.rent_steps.sort(key=lambda s: s.effective_date)
            lease.escalation_type = "fixed_step"

    def _annual_amount(self, b: BoundSheet, row: dict, fld: str) -> Decimal | None:
        """XL4ADW Amount1 columns are monthly series: annual = first 12 months."""
        cell = b.get(row, fld)
        suf = b.suffix(fld)
        if cell is None or cell == "":
            return None
        if suf in ("_APM", "_AEM", "_APCL", "_APUL", "_ATL"):
            return parse_series(cell, suf).sum_first(12)
        if suf in ("_APY", "_AEY"):
            return parse_series(cell, suf).first()
        return _number(cell)

    def _expenses(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            name = _text(b.get(row, "name"))
            if not name:
                continue
            unit = normalize(_text(b.get(row, "unit")) or "")
            growth = _rate(b.get(row, "growth"), b.suffix("growth"))
            if "egr" in unit or "egi" in unit or "effectivegross" in unit or unit.startswith("percent") or "%" in (
                _text(b.get(row, "unit")) or ""
            ):
                pct = _rate(b.get(row, "amount"), b.suffix("amount"))
                if pct is None:
                    continue
                acc.prop.expenses.append(ImportedExpense(
                    category=map_expense_category(name), description=name[:255], base_year_amount=D(0),
                    growth_rate_pct=D(0), is_recoverable=bool(_bool(b.get(row, "recoverable"))),
                    is_pct_of_egi=True, pct_of_egi=pct,
                ))
                continue
            amount = self._annual_amount(b, row, "amount")
            if amount is None:
                continue
            if "area" in unit or "sf" in unit or "unit" in unit:
                if acc.area():
                    amount = amount * acc.area()
                else:
                    acc.prop.warnings.append(f"Expense '{name}' is per area but property area is unknown")
            exp = ImportedExpense(
                category=map_expense_category(name), description=name[:255], base_year_amount=amount,
            )
            if growth is not None:
                exp.growth_rate_pct = growth
            exp.growth_schedule = _rate_schedule(b.get(row, "growth"), b.suffix("growth"))
            rec = _bool(b.get(row, "recoverable"))
            if rec is not None:
                exp.is_recoverable = rec
            elif exp.category == "management_fee":
                exp.is_recoverable = False
            gu = _rate(b.get(row, "gross_up_pct"), share=True)
            if gu:
                exp.is_gross_up_eligible = True
                exp.gross_up_vacancy_pct = gu
            acc.prop.expenses.append(exp)

    def _other_income(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            name = _text(b.get(row, "name"))
            amount = self._annual_amount(b, row, "amount")
            if not name or amount is None:
                continue
            unit = normalize(_text(b.get(row, "unit")) or "")
            if ("area" in unit or "sf" in unit) and acc.area():
                amount = amount * acc.area()
            oi = ImportedOtherIncome(category=name[:100], description=name[:255], base_year_amount=amount)
            g = _rate(b.get(row, "growth"), b.suffix("growth"))
            if g is not None:
                oi.growth_rate_pct = g
            oi.growth_schedule = _rate_schedule(b.get(row, "growth"), b.suffix("growth"))
            acc.prop.other_income.append(oi)

    def _capital(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            name = _text(b.get(row, "name")) or "Capital project"
            cell = b.get(row, "amount")
            suf = b.suffix("amount")
            if cell is None or cell == "":
                continue
            start = acc.prop.analysis_start_date
            if suf == "_ATL" or (isinstance(cell, str) and "/" in cell and "|" in cell):
                points = [(d, a) for d, a in parse_dated_list(cell) if a]
                if not points:
                    continue
                total = sum((a for _, a in points), D(0))
                first, last = points[0][0], points[-1][0]
                duration = (last.year - first.year) * 12 + last.month - first.month + 1
                acc.prop.capital_projects.append(ImportedCapitalProject(
                    description=name[:255], total_amount=total, start_date=first, duration_months=duration,
                ))
                continue
            if suf:
                series = parse_series(cell, suf)
                nz = [i for i, v in enumerate(series.values) if v]
                if not nz:
                    continue
                step = 12 if suf in ("_APY", "_AEY") else 1
                total = sum((series.values[i] for i in nz), D(0))
                acc.prop.capital_projects.append(ImportedCapitalProject(
                    description=name[:255], total_amount=total,
                    start_date=add_months(start, nz[0] * step),
                    duration_months=(nz[-1] - nz[0] + 1) * step,
                ))
                continue
            total = _number(cell)
            if not total:
                continue
            acc.prop.capital_projects.append(ImportedCapitalProject(
                description=name[:255], total_amount=total,
                start_date=_date(b.get(row, "start")) or start,
                duration_months=_months(b.get(row, "duration")) or 1,
            ))

    def _rates(self, b: BoundSheet, attr: str) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            v = _rate(b.get(row, "rate"), b.suffix("rate"))
            if v is not None:
                setattr(acc, f"_{attr}", v)
                setattr(acc, f"_{attr}_schedule", _rate_schedule(b.get(row, "rate"), b.suffix("rate")))

    def _inflation(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            name = normalize(_text(b.get(row, "name")) or "general")
            v = _rate(b.get(row, "rate"), b.suffix("rate"))
            if v is None:
                continue
            store = getattr(acc, "_inflation", {})
            store[name] = (v, _rate_schedule(b.get(row, "rate"), b.suffix("rate")))
            setattr(acc, "_inflation", store)

    def _loans(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            amount = _number(b.get(row, "amount"), b.suffix("amount"))
            if not amount:
                continue
            v = acc.prop.valuation = acc.prop.valuation or ImportedValuation()
            if v.loan_amount:
                rate = _rate(b.get(row, "rate"), b.suffix("rate"))
                if rate is None:
                    acc.prop.warnings.append(f"Loan of {amount:,.0f} has no interest rate; not imported")
                    continue
                v.additional_loans.append({
                    "label": _text(b.get(row, "name")),
                    "loan_amount": amount, "interest_rate": rate,
                    "amortization_months": _months(b.get(row, "amortization")),
                    "loan_term_months": _months(b.get(row, "term")),
                    "io_period_months": _months(b.get(row, "io")) or 0,
                    "loan_fees_pct": _rate(b.get(row, "fees")) or Decimal(0),
                })
                continue
            v.loan_amount = amount
            v.interest_rate = _rate(b.get(row, "rate"), b.suffix("rate"))
            v.amortization_months = _months(b.get(row, "amortization"))
            v.loan_term_months = _months(b.get(row, "term"))
            v.io_period_months = _months(b.get(row, "io"))
            v.loan_fees_pct = _rate(b.get(row, "fees"))

    def _tape_period(self, b: BoundSheet, row: dict, fld: str) -> int | None:
        """Months from a period cell; a header that says years (e.g. 'Amortization (Years)') is read as years."""
        n = _months(b.get(row, fld))
        if n is not None and "year" in normalize(b.fields.get(fld, "")):
            n *= 12
        return n

    def _loan_tape(self, b: BoundSheet, out: list[ImportedLoan]) -> None:
        for i, row in enumerate(b.sheet.rows, start=1):
            ext = _text(b.get(row, "external_id"))
            if not ext:
                continue
            label = f"{b.sheet.name} row {i} ({ext})"
            orig = _date(b.get(row, "origination_date"))
            mat = _date(b.get(row, "maturity_date"))
            original = _number(b.get(row, "original_balance"))
            current = _number(b.get(row, "reported_balance"))
            if original is None and current is not None:
                original = current
            if not (orig and mat and original and original > 0):
                self.warnings.append(f"{label}: needs origination date, maturity date and balance; skipped")
                continue
            if mat <= orig:
                self.warnings.append(f"{label}: maturity is not after origination; skipped")
                continue
            warnings: list[str] = []
            if _number(b.get(row, "original_balance")) is None:
                warnings.append("No original balance; current balance used")

            coupon = _rate(b.get(row, "coupon"))
            spread = to_decimal(b.get(row, "spread")) if b.get(row, "spread") not in (None, "") else None
            if spread is not None:
                # 275 = basis points, 2.75 = percent, 0.0275 = decimal
                spread = spread / D(10000) if abs(spread) > 20 else (spread / D(100) if abs(spread) > 1 else spread)
            kind = normalize(_text(b.get(row, "rate_type")) or "")
            if kind:
                rate_type = "floating" if any(k in kind for k in ("float", "arm", "variable", "sofr")) else "fixed"
            else:
                rate_type = "floating" if spread is not None and coupon is None else "fixed"
            if rate_type == "fixed" and coupon is None:
                self.warnings.append(f"{label}: fixed-rate loan without a coupon; skipped")
                continue
            if rate_type == "floating" and spread is None:
                self.warnings.append(f"{label}: floating-rate loan without a spread; skipped")
                continue

            raw_amort = normalize(_text(b.get(row, "amortization_months")) or "")
            amort = None if raw_amort in ("io", "interestonly", "none", "0", "") else \
                self._tape_period(b, row, "amortization_months")
            if amort is not None and 0 < amort <= 50:
                warnings.append(f"Amortization {amort} read as years")
                amort *= 12
            term = (mat.year - orig.year) * 12 + mat.month - orig.month
            raw_io = normalize(_text(b.get(row, "io_months")) or "")
            if raw_io in ("yes", "y", "full", "fullio", "true"):
                io = term
            elif raw_io in ("no", "n", "false", "none"):
                io = 0
            else:
                io = self._tape_period(b, row, "io_months") or 0
            if not amort:
                amort, io = None, 0

            lien_raw = normalize(_text(b.get(row, "lien_position")) or "")
            if lien_raw.isdigit():
                lien = max(1, int(lien_raw))
            elif lien_raw == "b" or any(k in lien_raw for k in ("junior", "second", "subordinate", "mezz", "bnote")):
                lien = 2
            else:
                lien = 1

            status_raw = _text(b.get(row, "delinquency_status"))
            status = _keyword_map(status_raw, _DELINQUENCY) or "current"
            if status_raw and not _keyword_map(status_raw, _DELINQUENCY):
                warnings.append(f"Delinquency status '{status_raw}' not recognized; treated as current")

            raw_type = _text(b.get(row, "property_type"))
            area_unit = "unit" if normalize(b.fields.get("total_area", "")) in ("units", "unitcount", "numberofunits") \
                else "sf"
            out.append(ImportedLoan(
                external_id=ext[:100],
                property_ref=_text(b.get(row, "property_ref")),
                property_name=_text(b.get(row, "property_name")),
                property_type=map_property_type(raw_type, self.options.default_property_type) if raw_type else None,
                market=_text(b.get(row, "market")),
                address_line1=_text(b.get(row, "address_line1")),
                city=_text(b.get(row, "city")),
                state=_text(b.get(row, "state")),
                zip_code=_text(b.get(row, "zip_code")),
                total_area=_number(b.get(row, "total_area")),
                area_unit=area_unit,
                name=_text(b.get(row, "name")),
                portfolio_name=_text(b.get(row, "portfolio_name")),
                lien_position=lien,
                sponsor=_text(b.get(row, "sponsor")),
                recourse=bool(_bool(b.get(row, "recourse"))),
                origination_date=orig,
                original_balance=original,
                maturity_date=mat,
                rate_type=rate_type,
                coupon=coupon if rate_type == "fixed" else None,
                index_name=_text(b.get(row, "index_name")) or ("SOFR" if rate_type == "floating" else None),
                spread=spread if rate_type == "floating" else None,
                index_floor=_rate(b.get(row, "index_floor")),
                index_cap=_rate(b.get(row, "index_cap")),
                amortization_months=amort,
                io_months=min(io, term),
                extension_count=int(_number(b.get(row, "extension_count")) or 0),
                extension_months=self._tape_period(b, row, "extension_months") or 0,
                reported_balance=current,
                balance_as_of_date=_date(b.get(row, "balance_as_of_date")),
                delinquency_status=status,
                origination_value=_number(b.get(row, "origination_value")),
                origination_noi=_number(b.get(row, "origination_noi")),
                tape_noi=_number(b.get(row, "tape_noi")),
                tape_value=_number(b.get(row, "tape_value")),
                tape_value_date=_date(b.get(row, "tape_value_date")),
                tape_occupancy=_rate(b.get(row, "tape_occupancy"), share=True),
                tape_noi_growth=_rate(b.get(row, "tape_noi_growth")),
                tape_exit_cap_rate=_rate(b.get(row, "tape_exit_cap_rate")),
                warnings=warnings,
            ))

    def _valuation(self, b: BoundSheet) -> None:
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            v = acc.prop.valuation = acc.prop.valuation or ImportedValuation()
            for fld, attr in (("discount_rate", "discount_rate"), ("exit_cap_rate", "exit_cap_rate"),
                              ("exit_costs", "exit_costs_pct")):
                r = _rate(b.get(row, fld), b.suffix(fld))
                if r is not None:
                    setattr(v, attr, r)
            price = _number(b.get(row, "purchase_price"))
            if price:
                v.purchase_price = price

    def _storage_unit_mix(self, b: BoundSheet) -> bool:
        """Self storage rows with unit sizes become an operating model; False if sizes are missing."""
        import json
        import re

        def size(row, name):
            sf = _number(b.get(row, "sf_per_unit"))
            if sf:
                return sf
            w, d = _number(b.get(row, "width")), _number(b.get(row, "depth"))
            if w and d:
                return w * d
            m = re.search(r"(\d+(?:\.\d+)?)\s*[x×X]\s*(\d+(?:\.\d+)?)", name or "")
            return D(m.group(1)) * D(m.group(2)) if m else None

        parsed = []
        for row in b.sheet.rows:
            name = _text(b.get(row, "name"))
            units = _number(b.get(row, "units"))
            street = _number(b.get(row, "market_rent"))
            if not name or not units or units <= 0 or street is None:
                continue
            sf = size(row, name)
            if not sf:
                return False
            occupied = _number(b.get(row, "occupied_units"))
            if occupied is None:
                occ = _rate(b.get(row, "occupancy"), share=True)
                vac = _rate(b.get(row, "vacancy"))
                share = occ if occ is not None else (D(1) - vac if vac is not None else D(1))
                occupied = units * share
            climate = _bool(b.get(row, "climate"))
            current = _number(b.get(row, "current_rent"))
            parsed.append((self._prop_for_row(b, row), {
                "name": name[:100], "sf_per_unit": str(sf), "count": int(units),
                "occupied_units": str(min(occupied, units)), "climate_controlled": bool(climate),
                "access": "interior" if climate else "drive_up" if "drive" in name.lower() else "interior",
                "in_place_rate": str(current if current is not None else street), "street_rate": str(street),
            }, _rate(b.get(row, "growth"), b.suffix("growth"))))
        if not parsed:
            return False
        # A size can appear twice (climate controlled and drive-up): keep names unique
        seen: dict[str, int] = {}
        for _, unit, _ in parsed:
            base = unit["name"]
            if base in seen:
                seen[base] += 1
                label = ("CC" if unit["climate_controlled"]
                         else "non-CC" if unit["access"] == "interior" else unit["access"].replace("_", "-"))
                unit["name"] = f"{base} ({label})" if f"{base} ({label})" not in seen else f"{base} ({seen[base]})"
            seen.setdefault(unit["name"], 1)
        from pydantic import ValidationError

        from src.schemas.self_storage import SelfStorageOperatingModel
        try:
            SelfStorageOperatingModel.model_validate({"unit_types": [u for _, u, _ in parsed]})
        except ValidationError as exc:
            self.warnings.append(f"{b.sheet.name}: storage unit mix not usable ({exc.errors()[0]['msg']})")
            return False
        by_prop: dict[int, tuple] = {}
        for acc, unit, growth in parsed:
            entry = by_prop.setdefault(id(acc), (acc, [], []))
            entry[1].append(unit)
            if growth is not None:
                entry[2].append(growth)
        for acc, units, growths in by_prop.values():
            p = acc.prop
            p.property_type, p.area_unit = "self_storage", "sf"
            p.total_area = sum((D(u["sf_per_unit"]) * u["count"] for u in units), D(0))
            acc.explicit_area = True
            model = {"unit_types": units, "street_rate_growth_pct": str(growths[0] if growths else D(0))}
            p.self_storage_assumptions_json = json.dumps(model)
            p.warnings.append(
                "Self storage unit mix imported; set churn, rate increases and ancillary income on the Unit Mix tab"
            )
        return True

    def _unit_mix(self, b: BoundSheet, property_type: str) -> None:
        if property_type == "self_storage":
            if self._storage_unit_mix(b):
                return
            self.warnings.append(
                f"{b.sheet.name}: no unit sizes (SF, width x depth, or a size like 10x10), "
                "so storage units were imported as a rent roll"
            )
        for row in b.sheet.rows:
            acc = self._prop_for_row(b, row)
            p = acc.prop
            if p.property_type not in ("multifamily", "self_storage"):
                p.property_type = property_type
            p.area_unit = "unit"
            name = _text(b.get(row, "name"))
            units = _number(b.get(row, "units"))
            mrent = _number(b.get(row, "market_rent"), b.suffix("market_rent"))
            if not name or not units or units <= 0 or mrent is None:
                continue
            acc.suites[name] = ImportedSuite(suite_name=name[:100], area=units, space_type=name[:100])
            mp = ImportedMarketProfile(
                key=name, space_type=name[:100], market_rent_per_unit=mrent,
                new_lease_term_months=12, renewal_lease_term_months=12, downtime_months=1,
                new_tenant_lc_pct=D(0), renewal_lc_pct=D(0), credit_loss_pct=D("0.01"),
            )
            occ = _rate(b.get(row, "occupancy"), share=True)
            vac = _rate(b.get(row, "vacancy"))
            if occ is not None:
                mp.general_vacancy_pct = D(1) - occ
            elif vac is not None:
                mp.general_vacancy_pct = vac
            g = _rate(b.get(row, "growth"), b.suffix("growth"))
            if g is not None:
                mp.rent_growth_rate_pct = g
            mp.rent_growth_schedule = _rate_schedule(b.get(row, "growth"), b.suffix("growth"))
            tc = _number(b.get(row, "turnover_cost"), b.suffix("turnover_cost"))
            if tc is not None:
                mp.new_tenant_ti_per_sf = tc
            cm = _number(b.get(row, "concession_months"), b.suffix("concession_months"))
            if cm is not None:
                mp.new_tenant_free_rent_months = int(cm)
            rp = _rate(b.get(row, "renewal_probability"), share=True)
            if rp is not None:
                mp.renewal_probability = rp
            term = _months(b.get(row, "term"))
            if term:
                mp.new_lease_term_months = mp.renewal_lease_term_months = term
            dt = _number(b.get(row, "downtime"))
            if dt is not None:
                mp.downtime_months = int(dt)
            p.market_profiles.append(mp)
            cur = _number(b.get(row, "current_rent"))
            if cur is not None:
                # In-place rents: one blended lease per unit type, rolling 6 months in (average remaining term)
                p.leases.append(ImportedLease(
                    suite_name=name[:100], tenant_name=f"{name} in-place",
                    lease_start_date=add_months(p.analysis_start_date, -6),
                    lease_end_date=add_months(p.analysis_start_date, 6) - timedelta(days=1),
                    base_rent_per_unit=cur, rent_payment_frequency="monthly", recovery_type="none",
                    market_profile_key=name,
                ))
                if "In-place unit rents imported as one lease per unit type expiring 6 months in" not in p.warnings:
                    p.warnings.append("In-place unit rents imported as one lease per unit type expiring 6 months in")

    def _assumption_profiles(self, b: BoundSheet, out: list[ImportedAssumptionProfile]) -> None:
        from src.schemas.portfolio import RangeBounds, check_ranges
        from src.services import cbsa

        def num(row, key):
            v = b.get(row, key)
            return None if v in (None, "") else to_decimal(v)

        for i, row in enumerate(b.sheet.rows, start=1):
            name = _text(b.get(row, "name")) or f"{b.sheet.name} row {i}"
            label = f"{b.sheet.name} '{name}'"
            values, ranges = {}, {}
            for f in ALL_FIELDS:
                base, low, high = num(row, f), num(row, f"{f}__low"), num(row, f"{f}__high")
                if base is None:
                    if low is not None or high is not None:
                        self.warnings.append(f"{label}: {f} has a range but no base; skipped")
                    continue
                values[f] = base
                if low is None and high is None:
                    continue
                rng = RangeBounds(low=low, high=high) if low is not None and high is not None else None
                try:
                    if rng is None:
                        raise ValueError(f"{f}: give both low and high")
                    check_ranges({f: base}, {f: rng})
                except ValueError as exc:
                    self.warnings.append(f"{label}: {exc}; range ignored")
                    continue
                ranges[f] = rng
            if not values:
                continue
            raw_type = _text(b.get(row, "property_type"))
            market = _text(b.get(row, "market"))
            code = _text(b.get(row, "cbsa_code"))
            state = cbsa.state_code(_text(b.get(row, "state")))
            if code:
                code = code.zfill(5)
                if cbsa.get(code) is None:
                    self.warnings.append(f"{label}: unknown CBSA code {code}; ignored")
                    code = None
            elif market and cbsa.match_market(market, state):
                code, market = cbsa.match_market(market, state), None
            quality = num(row, "quality_score")
            if quality is not None and not (1 <= quality <= 5 and quality == int(quality)):
                self.warnings.append(f"{label}: quality score must be a whole number 1-5; ignored")
                quality = None
            out.append(ImportedAssumptionProfile(
                name=name[:255],
                portfolio_name=_text(b.get(row, "portfolio_name")),
                property_type=map_property_type(raw_type, "") or None if raw_type else None,
                market=market,
                values=AssumptionValues(**values),
                ranges=ranges,
                cbsa_code=code,
                state=state,
                quality_score=int(quality) if quality is not None else None,
                as_of=_date(b.get(row, "as_of")),
                source=_text(b.get(row, "source")),
                comment=_text(b.get(row, "comment")),
            ))

    # -- finalize -------------------------------------------------------------

    def _finalize(self, acc: _PropAccumulator) -> None:
        p = acc.prop
        p.suites = list(acc.suites.values())
        suite_area = sum((s.area for s in p.suites), D(0))
        if not p.total_area:
            p.total_area = suite_area if suite_area > 0 else None
        if p.property_type in ("multifamily", "self_storage") and not p.self_storage_assumptions_json:
            p.area_unit = "unit"
            if suite_area > 0:
                p.total_area = suite_area

        vac = getattr(acc, "_vacancy", None)
        vac_schedule = getattr(acc, "_vacancy_schedule", [])
        cl = getattr(acc, "_credit_loss", None)
        cl_schedule = getattr(acc, "_credit_loss_schedule", [])
        infl = getattr(acc, "_inflation", {})   # name -> (rate, year-by-year rates)
        general = next((v for k, v in infl.items() if "general" in k), None)
        market_g = next((v for k, v in infl.items() if "market" in k or "rent" in k), general)
        expense_g = next((v for k, v in infl.items() if "expense" in k or "opex" in k), general)

        # Leases reference MLAs by external id; give suites the MLA name as space type
        mp_by_key = {m.key: m for m in p.market_profiles}
        for lease in p.leases:
            mp = mp_by_key.get(lease.market_profile_key or "")
            if mp is not None:
                suite = acc.suites.get(lease.suite_name)
                if suite is not None:
                    suite.space_type = mp.space_type
        # Suites with no lease (vacant) carry the MLA's external id as their space type
        for suite in acc.suites.values():
            if (mp := mp_by_key.get(suite.space_type)) is not None:
                suite.space_type = mp.space_type
        # Every suite space type needs a market profile; otherwise expiries go vacant
        for st in {s.space_type for s in p.suites} - {m.space_type for m in p.market_profiles}:
            p.warnings.append(f"No market leasing profile for space type '{st}'; space goes vacant at expiry")
        seen = set()
        unique = []
        for m in p.market_profiles:
            if m.space_type in seen:
                p.warnings.append(f"Duplicate market profile for space type '{m.space_type}' ignored")
                continue
            seen.add(m.space_type)
            # Property vacancy / credit loss replace the MLA's, schedule included
            if vac is not None:
                m.general_vacancy_pct, m.general_vacancy_schedule = vac, list(vac_schedule)
            if cl is not None:
                m.credit_loss_pct, m.credit_loss_schedule = cl, list(cl_schedule)
            # Inflation rates fill in growth only where the MLA left it at the default
            if market_g is not None and "rent_growth_rate_pct" not in m.model_fields_set:
                m.rent_growth_rate_pct, m.rent_growth_schedule = market_g[0], list(market_g[1])
            # A by-year value outside what a profile accepts would make the saved profile unreadable
            for attr, (lo, hi) in _SCHEDULE_BOUNDS.items():
                values = getattr(m, attr)
                if any(not (lo <= v <= hi) for v in values):
                    p.warnings.append(
                        f"MLA '{m.key}': {attr.replace('_', ' ')} has a value outside {lo}-{hi}; "
                        "by-year values dropped, the single value applies every year"
                    )
                    setattr(m, attr, [])
            unique.append(m)
        p.market_profiles = unique
        if expense_g is not None:
            for e in p.expenses:
                if not e.is_pct_of_egi and "growth_rate_pct" not in e.model_fields_set:
                    e.growth_rate_pct, e.growth_schedule = expense_g[0], list(expense_g[1])

        # Leases that end before they start, or MTM end-of-month caps
        for lease in p.leases:
            if lease.lease_end_date < lease.lease_start_date:
                p.warnings.append(f"Lease '{lease.tenant_name}' ends before it starts; dates swapped")
                lease.lease_start_date, lease.lease_end_date = lease.lease_end_date, lease.lease_start_date
            if lease.lease_type == "month_to_month":
                last = calendar.monthrange(p.analysis_start_date.year, p.analysis_start_date.month)[1]
                lease.lease_end_date = max(lease.lease_end_date, date(
                    p.analysis_start_date.year, p.analysis_start_date.month, last
                ))

        if p.valuation and not any(
            getattr(p.valuation, f) is not None for f in ImportedValuation.model_fields
        ):
            p.valuation = None

    def build(self) -> tuple[ImportPayload, list[SheetReport]]:
        loans: list[ImportedLoan] = []
        order = ["property", "classification", "area", "market", "lease", "rent_schedule", "multifamily",
                 "storage", "expense", "other_income", "capital", "vacancy", "credit_loss", "inflation",
                 "loan", "valuation"]
        profiles: list[ImportedAssumptionProfile] = []
        for kind in order:
            for b in self.bound:
                if b.kind != kind:
                    continue
                if kind == "property":
                    self._properties(b)
                elif kind == "classification":
                    self._classifications(b)
                elif kind == "area":
                    self._areas(b)
                elif kind == "market":
                    self._market_profiles(b)
                elif kind == "lease":
                    self._leases(b)
                elif kind == "rent_schedule":
                    self._rent_schedules(b)
                elif kind == "multifamily":
                    self._unit_mix(b, "multifamily")
                elif kind == "storage":
                    self._unit_mix(b, "self_storage")
                elif kind == "expense":
                    self._expenses(b)
                elif kind == "other_income":
                    self._other_income(b)
                elif kind == "capital":
                    self._capital(b)
                elif kind == "vacancy":
                    self._rates(b, "vacancy")
                elif kind == "credit_loss":
                    self._rates(b, "credit_loss")
                elif kind == "inflation":
                    self._inflation(b)
                elif kind == "loan":
                    self._loans(b)
                elif kind == "valuation":
                    self._valuation(b)
        for b in self.bound:
            if b.kind == "assumption_profiles":
                self._assumption_profiles(b, profiles)
            elif b.kind == "loan_tape":
                self._loan_tape(b, loans)

        for b in self.bound:
            if b.kind is None and normalize(b.sheet.name) not in REFERENCE_SHEETS:
                self.warnings.append(f"Sheet '{b.sheet.name}' not recognized; ignored")

        props = []
        for acc in self.props.values():
            self._finalize(acc)
            if not acc.prop.total_area or acc.prop.total_area <= 0:
                self.errors.append(f"Property '{acc.prop.name}': no area found (add AreaMeasures or suite areas)")
                continue
            props.append(acc.prop)
        if not props and not profiles and not loans:
            self.errors.append("No properties, loans or assumption profiles found in workbook")
        payload = ImportPayload(properties=props, assumption_profiles=profiles, loans=loans)
        return payload, [sheet_report(b) for b in self.bound]
