"""Azure Functions v2 Python programming model entry point for the
Orchestration Workflow Durable Functions app (T134/T135).

Registers:
- `http_start`: HTTP starter FastAPI's `AzureProviderAdapter` (T140) calls to
  begin a new Orchestration Workflow.
- `generic_orchestrator_v2`: the monitor for new instances of every workflow
  type; `generic_orchestrator` remains registered for legacy history replay.
- One `activity_trigger` per function in `activities.activities`.
- `raise_cancel_event`: HTTP endpoint FastAPI's cancel handler calls to
  deliver the `cancel` external event this orchestrator waits on.

This file intentionally contains no business logic itself - see
`orchestration_lib/` (pure decision logic), `orchestrators/` (the generator),
and `activities/` (side-effecting activity implementations).
"""

from __future__ import annotations

import logging

import azure.durable_functions as df
import azure.functions as func
from activities.activities import (
    acknowledge_cancellation,
    dispatch_job,
    finalize_workflow,
    poll_job_status,
    report_terminal_failure,
    stop_job,
)
from orchestration_lib.workflow_jobs import resolve_job_name
from orchestrators.generic_orchestrator import generic_orchestrator, generic_orchestrator_v2

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="orchestrations")
@app.durable_client_input(client_name="client")
async def http_start(
    req: func.HttpRequest, client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    """Starts a new Orchestration Workflow instance.

    Expects a JSON body `{"workflowId", "workflowType", "jobInput"?,
    "preDispatchedExecutionName"?}` - see orchestration_lib/orchestration_logic
    .py's `OrchestrationInput` docstring for what the last two fields mean and
    why `deploy` always sets `preDispatchedExecutionName` instead of
    `jobInput`.

    Resolves `jobName` here (a plain HTTP-triggered function, not the
    orchestrator itself) since only non-orchestrator code may safely read env
    vars/do I/O under Durable Functions' replay-determinism rules.
    """
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Request body must be JSON.", status_code=400)

    workflow_id = body.get("workflowId")
    workflow_type = body.get("workflowType")
    if not workflow_id or not workflow_type:
        return func.HttpResponse(
            "Request body must include 'workflowId' and 'workflowType'.", status_code=400
        )

    try:
        job_name = resolve_job_name(workflow_type)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as 400
        return func.HttpResponse(str(exc), status_code=400)

    orchestration_input = {
        "workflowId": workflow_id,
        "workflowType": workflow_type,
        "jobName": job_name,
        "jobInput": body.get("jobInput") or {},
        "preDispatchedExecutionName": body.get("preDispatchedExecutionName"),
    }
    instance_id = await client.start_new(
        "generic_orchestrator_v2", client_input=orchestration_input
    )
    # workflowId (FR-086) is the correlation ID shared with FastAPI
    # (backend/src/api/correlation.py) and the dispatched job
    # (jobs/common/telemetry.py) - stamped via `extra` so Azure Functions'
    # built-in Application Insights integration (host.json) surfaces it as
    # `customDimensions.workflowId`.
    logging.info(
        "Started orchestration %s for workflow %s",
        instance_id,
        workflow_id,
        extra={"workflowId": workflow_id},
    )
    return client.create_check_status_response(req, instance_id)


@app.route(route="orchestrations/{instance_id}/cancel", methods=["POST"])
@app.durable_client_input(client_name="client")
async def raise_cancel_event(
    req: func.HttpRequest, client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    """Delivers the `cancel` external event this orchestration waits on
    (contracts/api.md's cancel endpoint relays here)."""
    instance_id = req.route_params["instance_id"]
    await client.raise_event(instance_id, "cancel")
    return func.HttpResponse(status_code=202)


app.orchestration_trigger(context_name="context")(generic_orchestrator)
app.orchestration_trigger(context_name="context")(generic_orchestrator_v2)
app.activity_trigger(input_name="job_input")(dispatch_job)
app.activity_trigger(input_name="job_input")(poll_job_status)
app.activity_trigger(input_name="job_input")(stop_job)
app.activity_trigger(input_name="job_input")(acknowledge_cancellation)
app.activity_trigger(input_name="job_input")(report_terminal_failure)
app.activity_trigger(input_name="job_input")(finalize_workflow)
