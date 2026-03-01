from fastapi import APIRouter

from src.api.expenses import router as expenses_router
from src.api.leases import router as leases_router
from src.api.market_assumptions import router as market_router
from src.api.properties import router as properties_router
from src.api.suites import router as suites_router
from src.api.tenants import router as tenants_router
from src.api.capital import router as capital_router
from src.api.other_income import router as other_income_router
from src.api.recovery_structures import router as recovery_structures_router
from src.api.valuations import router as valuations_router

api_router = APIRouter()

api_router.include_router(properties_router)
api_router.include_router(suites_router)
api_router.include_router(tenants_router)
api_router.include_router(leases_router)
api_router.include_router(market_router)
api_router.include_router(expenses_router)
api_router.include_router(capital_router)
api_router.include_router(other_income_router)
api_router.include_router(recovery_structures_router)
api_router.include_router(valuations_router)
