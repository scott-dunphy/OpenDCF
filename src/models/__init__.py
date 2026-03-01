# Import all models here so SQLAlchemy registers them all before
# relationship configuration — prevents forward reference failures.
from src.models.base import Base, TimestampMixin, UUIDPrimaryKey  # noqa: F401
from src.models.property import Property, Suite  # noqa: F401
from src.models.lease import Tenant, Lease, RentStep, FreeRentPeriod, LeaseExpenseRecovery  # noqa: F401
from src.models.market import MarketLeasingProfile  # noqa: F401
from src.models.expense import PropertyExpense  # noqa: F401
from src.models.valuation import Valuation  # noqa: F401
from src.models.recovery_structure import RecoveryStructure, RecoveryStructureItem  # noqa: F401
from src.models.capital import PropertyCapitalProject  # noqa: F401
from src.models.other_income import PropertyOtherIncome  # noqa: F401
