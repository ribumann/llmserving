"""Pure decision logic for the generic Durable Functions orchestrator
(orchestrators/generic_orchestrator.py), split out so it is fully
unit-testable without a running Durable Functions host - no Azurite/Functions
Core Tools are available in this environment to integration-test the
generator against a live task hub.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# How often the orchestrator polls the dispatched Container Apps Job's
# execution status while it isn't yet terminal.
POLL_INTERVAL_SECONDS = 15

# Container Apps Jobs' `replica_timeout_in_seconds` is 3600 (infra/control/
# main.tf) with `replica_retry_limit = 0` (no auto-retry, FR-055/FR-089); this
# gives the orchestrator a comfortable margin over that before it gives up and
# reports the workflow as lost via the crash-safety-net `report_terminal_failure`
# activity. The job itself should always report its own terminal result to the
# internal callback API well before this fires - this is a last resort for a
# job whose container was killed outright (OOM-killed, node preemption) before
# it could call back itself.
ORCHESTRATION_TIMEOUT_SECONDS = 4200

_TERMINAL_JOB_STATUSES = {"Succeeded", "Failed", "Stopped", "Degraded"}


@dataclass
class OrchestrationInput:
    """The payload FastAPI's `AzureProviderAdapter` (T140) starts the
    orchestration with via the HTTP starter (function_app.py's `http_start`),
    carrying the `workflowId` correlation ID (FR-086) FastAPI already created
    via the internal callback API.

    `job_name` is resolved by `http_start` itself - a plain (non-orchestrator)
    Azure Function that may freely read env vars/do I/O - rather than inside
    this orchestrator, keeping the orchestrator's own code path free of env
    lookups (Durable Functions orchestrator code must be deterministic/replay
    -safe; plain trigger functions have no such constraint).

    `pre_dispatched_execution_name`, when set, means the caller (FastAPI)
    already started this job execution itself and this orchestrator's job is
    only to monitor it, never to dispatch it. This is the ONLY path used for
    the `deploy` workflow type: research.md's "Secret handling" decision and
    contracts/provider-interface.md are explicit that a Hugging Face gated-
    checkpoint credential must never reach Durable Functions workflow
    inputs/history (nor Key Vault, nor anywhere durable) - it may only ever
    exist in the Container Apps Job process's own memory. Since every
    orchestrator `call_activity` input/output is persisted to the Durable
    Task Hub's storage for replay, the only way to honor that rule while
    still letting Durable Functions monitor the run is for FastAPI to call
    the Container Apps Jobs "start" API directly (it already holds
    subscription-level Contributor RBAC, infra/control/main.tf) with the real
    credential as a one-off env override, and hand this orchestrator nothing
    but the resulting (non-secret) execution name to watch.
    """

    workflow_id: str
    workflow_type: str
    job_name: str
    job_input: dict[str, Any] = field(default_factory=dict)
    pre_dispatched_execution_name: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> OrchestrationInput:
        raw = raw or {}
        workflow_id = raw.get("workflowId")
        workflow_type = raw.get("workflowType")
        job_name = raw.get("jobName")
        if not workflow_id or not workflow_type or not job_name:
            raise ValueError(
                "Orchestration input must include non-empty 'workflowId', "
                "'workflowType', and 'jobName'."
            )
        return cls(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            job_name=job_name,
            job_input=dict(raw.get("jobInput") or {}),
            pre_dispatched_execution_name=raw.get("preDispatchedExecutionName"),
        )


def build_dispatch_job_input(orchestration_input: OrchestrationInput) -> dict[str, Any]:
    """Input for the `dispatch_job` activity: which Container Apps Job to
    start and the per-invocation env var overrides (WORKFLOW_ID/
    JOB_INPUT_JSON - see jobs/common/callback_client.py) it needs.

    Only ever used when `pre_dispatched_execution_name` is unset, i.e. never
    for the credential-carrying `deploy` workflow type (see
    `OrchestrationInput`'s docstring) - `job_input` here is therefore never
    sensitive, so it is safe for it to be JSON-encoded straight into this
    activity's input and persisted in Durable Functions history like any
    other orchestration state.
    """
    return {
        "jobName": orchestration_input.job_name,
        "envOverrides": {
            "WORKFLOW_ID": orchestration_input.workflow_id,
            "JOB_INPUT_JSON": json.dumps(orchestration_input.job_input),
        },
    }


def is_terminal_job_status(status: str) -> bool:
    return status in _TERMINAL_JOB_STATUSES


def job_status_to_workflow_outcome(status: str) -> str:
    """Maps a terminal Container Apps Job execution status to the
    Orchestration Workflow's own terminal `status` used for the
    crash-safety-net `report_terminal_failure` activity (contracts/api.md:
    completed/failed/cancelled). Only ever invoked for a job that reached a
    terminal *infrastructure* status (Succeeded/Failed/Stopped/Degraded)
    without itself having already called `/complete` - i.e. this is the
    "job crashed silently" path, so anything other than a clean Succeeded is
    treated as failed rather than guessed at more granularly.
    """
    if status == "Succeeded":
        return "completed"
    return "failed"
