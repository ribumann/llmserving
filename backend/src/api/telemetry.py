from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from sqlalchemy.exc import SQLAlchemyError

from src.api.errors import get_request_id
from src.domain.operation_event import OperationEvent

LOGGER = logging.getLogger(__name__)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(slots=True)
class OperationTelemetry:
    session_factory: Any | None = None

    def emit(
        self,
        *,
        operation_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        environment_id: str | None = None,
    ) -> None:
        if self.session_factory is None:
            LOGGER.debug("Skipping telemetry event with no configured session factory")
            return

        event = OperationEvent(
            eventId=str(uuid4()),
            operationId=operation_id,
            requestId=request_id or get_request_id(),
            environmentId=environment_id,
            eventType=event_type,
            payload=payload or {},
        )
        try:
            with self.session_factory() as session:
                session.add(event)
                session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            LOGGER.warning("Failed to persist operation event: %s", exc)


def install_telemetry_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def capture_request_events(request: Request, call_next):
        telemetry: OperationTelemetry | None = getattr(request.app.state, "telemetry", None)
        operation_id = request.headers.get("X-Operation-ID") or getattr(
            request.state, "request_id", uuid4().hex
        )
        request.state.operation_id = operation_id

        if telemetry is not None and request.method in MUTATING_METHODS:
            telemetry.emit(
                operation_id=operation_id,
                event_type="http.request.started",
                payload={"method": request.method, "path": request.url.path},
                request_id=getattr(request.state, "request_id", None),
            )

        response = await call_next(request)

        if telemetry is not None and request.method in MUTATING_METHODS:
            telemetry.emit(
                operation_id=operation_id,
                event_type="http.request.completed",
                payload={
                    "method": request.method,
                    "path": request.url.path,
                    "statusCode": response.status_code,
                },
                request_id=getattr(request.state, "request_id", None),
            )

        return response
