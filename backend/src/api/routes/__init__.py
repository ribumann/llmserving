from fastapi import APIRouter

from src.api.internal_workflows import router as internal_workflows_router
from src.api.routes.catalog import router as catalog_router
from src.api.routes.comparisons import router as comparisons_router
from src.api.routes.configurations import router as configurations_router
from src.api.routes.deployments import router as deployments_router
from src.api.routes.environments import router as environments_router
from src.api.routes.prompts import router as prompts_router
from src.api.routes.public import router as public_router
from src.api.routes.runs import router as runs_router
from src.api.routes.system import router as system_router


def create_router() -> APIRouter:
    router = APIRouter()
    router.include_router(system_router)
    router.include_router(catalog_router)
    router.include_router(environments_router)
    router.include_router(configurations_router)
    router.include_router(deployments_router)
    router.include_router(prompts_router)
    router.include_router(runs_router)
    router.include_router(comparisons_router)
    router.include_router(public_router)
    router.include_router(internal_workflows_router)
    return router
