"""OpenTelemetry-compatible correlation ID propagation for Container Apps Jobs
(FR-086).

Every worker is a short-lived, standalone process (T136) - there is no long-
running app to attach middleware to, so this module is invoked once near the
top of each `entrypoint.py`'s `main()`, right after `WORKFLOW_ID` is read from
the environment. It (1) attaches a logging filter that stamps this
invocation's `workflowId` onto every log record this process emits, and (2) -
only when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set (always true in the
deployed job template, infra/control/main.tf) - configures the Azure Monitor
OpenTelemetry distro so those log records (and any trace spans) ship to
Application Insights as `customDimensions.workflowId`, the same correlation ID
FastAPI (backend/src/api/correlation.py) and the Durable Functions
orchestrator (functions/activities/activities.py) stamp onto their own logs.
"""

from __future__ import annotations

import logging
import os


class _WorkflowIdFilter(logging.Filter):
    def __init__(self, workflow_id: str) -> None:
        super().__init__()
        self._workflow_id = workflow_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.workflowId = self._workflow_id
        return True


def configure_job_telemetry(workflow_id: str, *, logger_name: str = "job") -> logging.Logger:
    """Call once near the top of each entrypoint's `main()`. Returns a logger
    that stamps `workflowId` onto every record it emits; safe (never raises)
    when `APPLICATIONINSIGHTS_CONNECTION_STRING` is unset (local dev/tests) or
    when the exporter fails to initialize - telemetry export must never block
    a job from doing its actual work."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(logger_name)
    logger.addFilter(_WorkflowIdFilter(workflow_id))

    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor()
        except Exception:  # pragma: no cover - best-effort telemetry wiring only
            logger.warning("Failed to configure Azure Monitor OpenTelemetry export", exc_info=True)

    return logger
