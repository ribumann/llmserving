from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

LOGGER = logging.getLogger(__name__)
_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="")


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def get_request_id() -> str:
    return _REQUEST_ID.get() or uuid4().hex


def with_request_id(payload: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
    return {"requestId": request_id or get_request_id(), **payload}


def _error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "requestId": request_id,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
        },
    )


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context_and_error_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        token = _REQUEST_ID.set(request_id)

        try:
            response = await call_next(request)
        except ApiError as exc:
            response = _error_response(
                request_id=request_id,
                status_code=exc.status_code,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )
        except HTTPException as exc:
            response = _error_response(
                request_id=request_id,
                status_code=exc.status_code,
                code="http_error",
                message=str(exc.detail),
                details={},
            )
        except Exception as exc:  # pragma: no cover
            LOGGER.exception(
                "Unhandled request failure method=%s path=%s request_id=%s",
                request.method,
                request.url.path,
                request_id,
                exc_info=exc,
                extra={
                    "request_method": request.method,
                    "request_path": request.url.path,
                    "request_id": request_id,
                },
            )
            response = _error_response(
                request_id=request_id,
                status_code=500,
                code="internal_server_error",
                message="The server encountered an unexpected error.",
                details={},
            )
        finally:
            _REQUEST_ID.reset(token)

        response.headers["X-Request-ID"] = request_id
        return response
