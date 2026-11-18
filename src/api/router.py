from fastapi import APIRouter

from src.api.expenses import router as expenses_router
from src.api.imports import router as imports_router
from src.api.loans import router as loans_router
from src.api.leases import router as leases_router
from src.api.market_assumptions import router as market_router
from src.api.portfolios import router as portfolios_router
from src.api.properties import router as properties_router
from src.api.suites import router as suites_router
from src.api.tenants import router as tenants_router
from src.api.capital import router as capital_router
from src.api.other_income import router as other_income_router
from src.api.recovery_structures import router as recovery_structures_router
from src.api.recovery_pools import router as recovery_pools_router
from src.api.simulations import router as simulations_router
from src.api.valuations import router as valuations_router
from src.api.comparables import router as comparables_router
from src.api.documents import router as documents_router
from src.api.copilot import router as copilot_router
from src.api.reconstructions import router as reconstructions_router
from src.api.search import router as search_router
from src.api.cbsas import router as cbsas_router
from src.api.help import router as help_router
from src.api.valuation_model import router as valuation_model_router

api_router = APIRouter()

api_router.include_router(properties_router)
api_router.include_router(cbsas_router)
api_router.include_router(suites_router)
api_router.include_router(tenants_router)
api_router.include_router(leases_router)
api_router.include_router(market_router)
api_router.include_router(expenses_router)
api_router.include_router(capital_router)
api_router.include_router(other_income_router)
api_router.include_router(recovery_structures_router)
api_router.include_router(recovery_pools_router)
api_router.include_router(valuations_router)
api_router.include_router(portfolios_router)
api_router.include_router(imports_router)
api_router.include_router(loans_router)
api_router.include_router(simulations_router)
api_router.include_router(comparables_router)
api_router.include_router(documents_router)
api_router.include_router(copilot_router)
api_router.include_router(reconstructions_router)
api_router.include_router(search_router)
api_router.include_router(help_router)
api_router.include_router(valuation_model_router)
