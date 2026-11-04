from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from sqlalchemy.exc import SQLAlchemyError

from src.domain.audit_log import AuditLogEntry

LOGGER = logging.getLogger(__name__)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _build_audit_entry(request: Request, status_code: int) -> AuditLogEntry | None:
    user = getattr(request.state, "user", None)
    if user is None:
        return None

    details: dict[str, Any] = {
        "client": request.client.host if request.client else None,
        "query": dict(request.query_params),
    }
    return AuditLogEntry(
        auditLogId=str(uuid4()),
        requestId=getattr(request.state, "request_id", uuid4().hex),
        actorId=user.subject,
        actorEmail=user.email,
        method=request.method,
        path=request.url.path,
        statusCode=status_code,
        details=details,
    )


def install_audit_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def audit_mutating_requests(request: Request, call_next):
        response = await call_next(request)
        if request.method not in MUTATING_METHODS:
            return response

        session_factory = getattr(request.app.state, "session_factory", None)
        entry = _build_audit_entry(request, response.status_code)
        if session_factory is None or entry is None:
            return response

        try:
            with session_factory() as session:
                session.add(entry)
                session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            LOGGER.warning("Failed to persist audit log entry: %s", exc)

        return response
