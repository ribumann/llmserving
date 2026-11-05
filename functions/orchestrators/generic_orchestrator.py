"""Generic Durable Functions orchestrator (T134/T135): monitors exactly one
Container Apps Job execution per Orchestration Workflow to completion while
remaining responsive to an external "cancel" event, dispatching that
execution itself unless the caller (FastAPI) already dispatched it directly
(the `deploy` workflow type - see `orchestration_lib.orchestration_logic
.OrchestrationInput`'s docstring for why).

The job itself is the authoritative reporter of progress/terminal result to
FastAPI's internal callback API (contracts/api.md) - this orchestrator's
`report_terminal_failure` activity is only a crash-safety net for the case
where the job's container is killed/crashes before it can call back itself
(e.g. OOM-killed, node preemption), mirroring the same last-resort exception
handler every jobs/*/entrypoint.py already implements for its own process.

NOTE: this generator could not be exercised against a live Durable Functions
host in this environment (no Azurite/Functions Core Tools available here) -
verify with `func start` + Azurite before first real deployment. Its
decision logic (orchestration_lib/orchestration_logic.py) is fully
unit-tested instead, and this generator's own control flow is unit-tested by
manually driving it with a fake context in tests/test_generic_orchestrator.py.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from typing import Any

from orchestration_lib.orchestration_logic import (
    ORCHESTRATION_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    OrchestrationInput,
    build_dispatch_job_input,
    is_terminal_job_status,
    job_status_to_workflow_outcome,
)


def generic_orchestrator(context: Any) -> Generator[Any, Any, dict[str, Any]]:
    # Keep the original activity sequence for existing Durable history replay.
    return (yield from _orchestrate(context, finalize=False))


def generic_orchestrator_v2(context: Any) -> Generator[Any, Any, dict[str, Any]]:
    return (yield from _orchestrate(context, finalize=True))


def _orchestrate(context: Any, *, finalize: bool) -> Generator[Any, Any, dict[str, Any]]:
    orchestration_input = OrchestrationInput.from_raw(context.get_input())

    if orchestration_input.pre_dispatched_execution_name:
        execution_name = orchestration_input.pre_dispatched_execution_name
    else:
        dispatch_result = yield context.call_activity(
            "dispatch_job", build_dispatch_job_input(orchestration_input)
        )
        execution_name = dispatch_result["executionName"]

    context.set_custom_status(
        {
            "phase": "dispatched",
            "jobName": orchestration_input.job_name,
            "executionName": execution_name,
        }
    )

    overall_deadline = context.current_utc_datetime + timedelta(
        seconds=ORCHESTRATION_TIMEOUT_SECONDS
    )
    cancel_task = context.wait_for_external_event("cancel")

    while True:
        if context.current_utc_datetime >= overall_deadline:
            if finalize:
                yield context.call_activity(
                    "stop_job",
                    {
                        "jobName": orchestration_input.job_name,
                        "executionName": execution_name,
                        "workflowId": orchestration_input.workflow_id,
                    },
                )
                outcome = yield context.call_activity(
                    "finalize_workflow",
                    {
                        "workflowId": orchestration_input.workflow_id,
                        "status": "failed",
                        "reason": "orchestration_timeout",
                    },
                )
                return {"status": outcome["status"], "reason": "orchestration_timeout"}
            yield context.call_activity(
                "report_terminal_failure",
                {"workflowId": orchestration_input.workflow_id, "reason": "orchestration_timeout"},
            )
            return {"status": "failed", "reason": "orchestration_timeout"}

        timer_task = context.create_timer(
            context.current_utc_datetime + timedelta(seconds=POLL_INTERVAL_SECONDS)
        )
        status_task = context.call_activity(
            "poll_job_status",
            {"jobName": orchestration_input.job_name, "executionName": execution_name},
        )

        winner = yield context.task_any([cancel_task, timer_task, status_task])

        if winner is cancel_task:
            if not timer_task.is_completed:
                timer_task.cancel()
            yield context.call_activity(
                "stop_job",
                {
                    "jobName": orchestration_input.job_name,
                    "executionName": execution_name,
                    "workflowId": orchestration_input.workflow_id,
                },
            )
            if finalize:
                outcome = yield context.call_activity(
                    "finalize_workflow",
                    {
                        "workflowId": orchestration_input.workflow_id,
                        "status": "cancelled",
                        "reason": "cancellation_requested",
                    },
                )
            yield context.call_activity(
                "acknowledge_cancellation", {"workflowId": orchestration_input.workflow_id}
            )
            return {"status": outcome["status"] if finalize else "cancelled"}

        if winner is status_task:
            if not timer_task.is_completed:
                timer_task.cancel()
            status = status_task.result
            if is_terminal_job_status(status):
                if finalize:
                    outcome = yield context.call_activity(
                        "finalize_workflow",
                        {
                            "workflowId": orchestration_input.workflow_id,
                            "status": "failed",
                            "reason": "job_terminal_without_callback",
                            "jobStatus": status,
                        },
                    )
                    return {"status": outcome["status"]}
                return {"status": job_status_to_workflow_outcome(status)}
            continue

        # timer_task won: the poll_job_status activity call hasn't completed
        # yet - just loop around and try again.
        continue
