"""Durable Functions activity implementations (T134/T135).

Each activity is a thin, side-effecting wrapper around `orchestration_lib` -
kept here rather than in `orchestration_lib` itself so that module can stay
pure/host-independent and fully unit-testable without the `azure.functions`
runtime present.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from orchestration_lib.callback_client import (
    CallbackClientError,
    WorkflowAlreadyTerminal,
    WorkflowCallbackClient,
)
from orchestration_lib.container_jobs import (
    dispatch_job as _dispatch_job,
)
from orchestration_lib.container_jobs import (
    get_job_execution_status,
    stop_job_execution,
)

LOGGER = logging.getLogger(__name__)


def _resource_group() -> str:
    return os.environ["CONTAINER_APPS_RESOURCE_GROUP"]


# NOTE: activity_trigger input parameters are annotated as plain `dict` (not
# `dict[str, Any]`) because azure_functions_worker's binding validator
# (validate_function_params) requires `isinstance(annotation, type)`, which is
# False for a subscripted generic like `dict[str, Any]` - it raises
# FunctionLoadError: "binding job_input has invalid non-type annotation" at
# worker startup otherwise. Discovered when first deploying this app for real
# (no local Functions host was available to catch it earlier - see
# orchestrators/generic_orchestrator.py's module docstring).
def dispatch_job(job_input: dict) -> dict[str, Any]:
    """Activity: start a new execution of `job_input["jobName"]` with the env
    var overrides in `job_input["envOverrides"]` (WORKFLOW_ID/JOB_INPUT_JSON).

    Never called for the credential-carrying `deploy` workflow type - see
    orchestration_lib/orchestration_logic.py's `OrchestrationInput` docstring.
    """
    workflow_id = job_input["envOverrides"]["WORKFLOW_ID"]
    result = _dispatch_job(
        _resource_group(),
        job_input["jobName"],
        job_input["envOverrides"],
    )
    # workflowId (FR-086) is the correlation ID shared with FastAPI
    # (backend/src/api/correlation.py) and the dispatched job itself
    # (jobs/common/telemetry.py) - stamped via `extra` so Azure Functions'
    # built-in Application Insights integration surfaces it as
    # `customDimensions.workflowId`.
    LOGGER.info(
        "Dispatched job %s executionName=%s",
        job_input["jobName"],
        result.execution_name,
        extra={"workflowId": workflow_id},
    )
    return {"executionName": result.execution_name}


def poll_job_status(job_input: dict) -> str:
    """Activity: return the current status of a previously dispatched job
    execution (Running/Processing/Succeeded/Failed/Stopped/Degraded/Unknown/
    NotFound)."""
    return get_job_execution_status(
        _resource_group(), job_input["jobName"], job_input["executionName"]
    )


def stop_job(job_input: dict) -> None:
    """Activity: stop a running job execution in response to a cancellation
    request (contracts/api.md's cancel endpoint, relayed to this orchestration
    via the `cancel` external event)."""
    stop_job_execution(_resource_group(), job_input["jobName"], job_input["executionName"])
    LOGGER.info(
        "Stopped job %s executionName=%s",
        job_input["jobName"],
        job_input["executionName"],
        extra={"workflowId": job_input.get("workflowId")},
    )


def acknowledge_cancellation(job_input: dict) -> None:
    """Activity: POST /internal/workflows/{workflowId}/cancel-ack, confirming
    the job execution has been stopped."""
    with WorkflowCallbackClient() as client:
        client.acknowledge_cancellation(job_input["workflowId"])
    LOGGER.info("Acknowledged cancellation", extra={"workflowId": job_input["workflowId"]})


def report_terminal_failure(job_input: dict) -> None:
    """Activity: crash-safety-net only - reports the workflow as failed to
    FastAPI's internal callback API when this orchestration itself gives up
    (e.g. the overall orchestration timeout elapsed) without the job ever
    having reported its own terminal outcome. Mirrors the last-resort
    exception handler every jobs/*/entrypoint.py already implements for its
    own process."""
    with WorkflowCallbackClient() as client:
        client.complete_workflow(
            job_input["workflowId"],
            status="failed",
            diagnostics={"reason": job_input.get("reason", "unknown")},
        )
    LOGGER.warning(
        "Reported terminal failure reason=%s",
        job_input.get("reason", "unknown"),
        extra={"workflowId": job_input["workflowId"]},
    )


def finalize_workflow(job_input: dict) -> dict[str, str]:
    """Version-two safety net: preserve a worker's authoritative terminal outcome."""
    workflow_id = job_input["workflowId"]
    status = job_input["status"]
    if status not in {"failed", "cancelled"}:
        raise ValueError("Monitor finalization may only fail or cancel a running workflow.")
    diagnostics = {"reason": job_input["reason"]}
    if "jobStatus" in job_input:
        diagnostics["jobStatus"] = job_input["jobStatus"]
    with WorkflowCallbackClient() as client:
        try:
            result = client.complete_workflow(workflow_id, status=status, diagnostics=diagnostics)
        except WorkflowAlreadyTerminal as exc:
            if exc.workflow_id != workflow_id:
                raise
            LOGGER.info(
                "Preserved terminal workflow status=%s",
                exc.status,
                extra={"workflowId": workflow_id},
            )
            return {"status": exc.status}
    if result.get("workflowId") != workflow_id or result.get("status") != status:
        raise CallbackClientError("Finalization callback returned an unexpected workflow outcome.")
    LOGGER.warning(
        "Finalized workflow status=%s reason=%s",
        status,
        diagnostics["reason"],
        extra={"workflowId": workflow_id},
    )
    return {"status": status}
