# Import all models here so SQLAlchemy registers them all before
# relationship configuration — prevents forward reference failures.
from src.models.base import Base, TimestampMixin, UUIDPrimaryKey  # noqa: F401
from src.models.property import Property, Suite  # noqa: F401
from src.models.lease import Tenant, Lease, RentStep, FreeRentPeriod, LeaseExpenseRecovery  # noqa: F401
from src.models.market import MarketLeasingProfile  # noqa: F401
from src.models.expense import PropertyExpense  # noqa: F401
from src.models.valuation import Valuation, ValuationSnapshot  # noqa: F401
from src.models.recovery_structure import RecoveryStructure, RecoveryStructureItem  # noqa: F401
from src.models.recovery_pool import RecoveryPool  # noqa: F401
from src.models.capital import PropertyCapitalProject  # noqa: F401
from src.models.other_income import PropertyOtherIncome  # noqa: F401
from src.models.portfolio import AssumptionProfile, AssumptionSettings, ImportJob, Portfolio, PortfolioRun, PortfolioScenario  # noqa: F401
from src.models.loan import CollateralSimulation, LoanRiskRun, MortgageLoan, RiskParameterSet  # noqa: F401
from src.models.audit import AuditLog, RiskParameterSetVersion  # noqa: F401
from src.models.comparable import ComparableSale, ComparableSelection  # noqa: F401

import src.services.audit  # noqa: F401,E402 - registers the audit flush hook
import src.services.input_tracking  # noqa: F401,E402 - registers the input staleness hook
import src.services.valuation_lock  # noqa: F401,E402 - registers the frozen-valuation guard
from src.models.document import (
    AiModelAction,
    AppraisalReconstruction,
    ExtractedFact,
    SourceDocument,
    ValuationDocument,
)

__all__ = [
    "AiModelAction", "AppraisalReconstruction", "ExtractedFact",
    "SourceDocument", "ValuationDocument",
]
