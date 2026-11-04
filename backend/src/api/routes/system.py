import asyncio
import logging

from fastapi import APIRouter, Request

from src.api.errors import ApiError, with_request_id

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/healthz")
def healthz(request: Request) -> dict[str, str]:
    return with_request_id(
        {
            "status": "ok",
            "service": "azure-llm-serving-demo-backend",
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, object]:
    try:
        ready = await asyncio.wait_for(
            asyncio.to_thread(request.app.state.database_readiness.check),
            timeout=request.app.state.settings.database_readiness_timeout_seconds,
        )
    except TimeoutError:
        LOGGER.warning("Database readiness exceeded its response deadline.")
        ready = False
    if not ready:
        raise ApiError(
            status_code=503,
            code="database_not_ready",
            message=(
                "The database is unavailable or has not responded within the readiness deadline."
            ),
            details={"database": "unavailable"},
        )
    return with_request_id(
        {"status": "ready", "database": "ready"},
        getattr(request.state, "request_id", None),
    )
