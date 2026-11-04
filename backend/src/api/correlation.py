"""OpenTelemetry-compatible correlation ID propagation (FR-086).

`workflowId` is the correlation ID shared across every hop of one logical
operation: FastAPI (here), the Durable Functions orchestrator
(functions/activities/activities.py), and the Container Apps Job it dispatches
(jobs/common/telemetry.py). Whichever FastAPI code path is acting on behalf of
a specific workflow binds that workflow's ID onto `workflow_correlation()` for
the duration of the call, so every log record emitted in between - and, once
`configure_monitoring()` has wired the Azure Monitor OpenTelemetry exporter,
every trace/log line shipped to Application Insights - carries the same
`workflowId` the other two hops stamp onto their own logs.
"""

from __future__ import annotations

import contextvars
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_workflow_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "workflow_id", default=None
)

_LOGGER = logging.getLogger(__name__)


class WorkflowIdLogFilter(logging.Filter):
    """Attaches the active `workflowId` (if any) to every `LogRecord` as
    `record.workflowId`, so it appears as `customDimensions.workflowId` once
    Application Insights ingests it (FR-086)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.workflowId = _workflow_id.get()
        return True


def current_workflow_id() -> str | None:
    return _workflow_id.get()


@contextmanager
def workflow_correlation(workflow_id: str | None) -> Iterator[None]:
    """Binds `workflow_id` as the active correlation ID for the duration of
    the `with` block; restores whatever was previously bound afterwards
    (nesting-safe)."""
    token = _workflow_id.set(workflow_id)
    try:
        yield
    finally:
        _workflow_id.reset(token)


def configure_monitoring(app: Any = None) -> None:
    """Attaches `WorkflowIdLogFilter` to the root logger (always safe/local),
    then - only when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set - wires
    the Azure Monitor OpenTelemetry distro so traces/logs/metrics ship to
    Application Insights (FR-086). A no-op in local dev/tests where the
    connection string is absent; never raises, since telemetry export must
    never block the app from starting.
    """
    logging.getLogger().addFilter(WorkflowIdLogFilter())

    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor()

        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
    except Exception:  # pragma: no cover - best-effort telemetry wiring only
        _LOGGER.warning("Failed to configure Azure Monitor OpenTelemetry export", exc_info=True)
