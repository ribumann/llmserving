from fastapi import APIRouter, Request

from src.api.errors import with_request_id

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
