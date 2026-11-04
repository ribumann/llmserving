"""Translates a just-completed Orchestration Workflow's terminal outcome into
domain-entity state transitions (T140/T144).

`OrchestrationWorkflowService`'s own docstring explicitly defers this: it only
owns workflow-lifecycle bookkeeping and the single-writer lock, never
`DemoEnvironment.lifecycleState`/`DeploymentRevision.lifecycleState` - "that
per-workflow-type state machine is wired into the Azure ProviderAdapter
rewrite". This module is that piece: wired from
`internal_workflows.py`'s POST /complete route in the same DB transaction as
the workflow's own terminal-state write, so a workflow's completion and its
domain-entity state change land atomically together (T144's acceptance
criterion: an environment/revision resolves to its terminal state "only via a
callback, never by polling Terraform directly").
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    DemoEnvironmentState,
    DeploymentRevisionState,
    WorkflowStatus,
    WorkflowType,
)
from src.domain.environment import DemoEnvironment
from src.domain.orchestration_workflow import OrchestrationWorkflow

# The key each of provision.py/deploy.py's start_*() helpers must record into a
# newly-created workflow's diagnostics (via OrchestrationWorkflowService
# .record_progress) so a later `deploy`/`teardown` completion can find the
# DeploymentRevision it belongs to - OrchestrationWorkflow itself carries no
# such column (data-model.md: "carries no domain state itself").
DEPLOYMENT_REVISION_ID_KEY = "deploymentRevisionId"


def _terraform_outputs(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Unwraps `terraform output -json`'s `{"key": {"value": ...}}` shape
    (jobs/terraform_runner/entrypoint.py's completed-workflow diagnostics)."""
    raw = dict(diagnostics.get("outputs") or {})
    outputs: dict[str, Any] = {}
    for key, value in raw.items():
        outputs[key] = value["value"] if isinstance(value, dict) and "value" in value else value
    return outputs


def _failure_diagnostics(diagnostics: dict[str, Any]) -> list[str]:
    """Builds a user-facing diagnostics list from a failed terraform_runner
    job's raw error/stdout/stderr (jobs/terraform_runner/entrypoint.py's
    failed-workflow diagnostics), preserving the old in-process provisioner's
    "Suggested fallback regions" guidance for Azure's AllocationFailed error -
    the region/fallbackRegions values recorded into the workflow's diagnostics
    at dispatch time (AzureProvisioner._start_workflow)."""
    error = str(diagnostics.get("error") or "The operation failed.")
    combined = "\n".join(str(diagnostics.get(key) or "") for key in ("error", "stdout", "stderr"))
    messages = [error]
    if "AllocationFailed" in combined:
        region = diagnostics.get("region")
        fallback_regions = [
            candidate
            for candidate in list(diagnostics.get("fallbackRegions") or [])
            if candidate != region
        ]
        if fallback_regions:
            messages.append(f"Suggested fallback regions: {', '.join(fallback_regions)}.")
    return messages


def _record_operation_diagnostics(
    environment: DemoEnvironment, *, operation_id: str, phase: str, diagnostics: list[str]
) -> None:
    provider_state = dict(environment.providerState or {})
    provider_state["currentOperation"] = {
        **dict(provider_state.get("currentOperation") or {}),
        "operationId": operation_id,
        "phase": phase,
        "diagnostics": diagnostics,
    }
    environment.providerState = provider_state


class WorkflowReconciliationService:
    """Applies a completed workflow's outcome to the `DemoEnvironment`/
    `DeploymentRevision` it was running against. One handler per `WorkflowType`
    that has a domain-entity state to update; workflow types with none
    (evaluate-golden/evaluate-benchmark/performance-test/export - their
    callback result has no environment/revision lifecycle implication) are
    intentionally left unhandled here."""

    def reconcile(self, session: Session, *, workflow: OrchestrationWorkflow) -> None:
        handler = {
            WorkflowType.PROVISION: self._reconcile_provision,
            WorkflowType.TEARDOWN: self._reconcile_teardown,
            WorkflowType.DEPLOY: self._reconcile_deploy,
        }.get(workflow.workflowType)
        if handler is not None:
            handler(session, workflow)

    def _reconcile_provision(self, session: Session, workflow: OrchestrationWorkflow) -> None:
        environment = session.get(DemoEnvironment, workflow.environmentId)
        if environment is None:
            return

        diagnostics = dict(workflow.diagnostics or {})
        if workflow.status == WorkflowStatus.COMPLETED:
            outputs = _terraform_outputs(diagnostics)
            provider_state = dict(environment.providerState or {})
            provider_state.update(
                {
                    "resourceGroupName": outputs.get("resource_group_name"),
                    "vmName": outputs.get("vm_name"),
                    "privateIpAddress": outputs.get("private_ip_address"),
                    "vllmEndpoint": outputs.get("vllm_endpoint"),
                    # Same value as vllmEndpoint, under the key name the vLLM engine
                    # adapter/prompt client/evaluation code actually reads
                    # (providers/local/adapter.py uses this same "inferenceApiUrl"
                    # convention for the Ollama provider). Without this, prompts,
                    # performance runs, and engine-level health checks against Azure
                    # deployments all fail with "no inference API URL" even though
                    # the deployment itself is healthy.
                    "inferenceApiUrl": outputs.get("vllm_endpoint"),
                }
            )
            environment.providerState = provider_state
            environment.lifecycleState = DemoEnvironmentState.READY
        else:
            environment.lifecycleState = DemoEnvironmentState.PROVISIONING_FAILED
            _record_operation_diagnostics(
                environment,
                operation_id=workflow.operationId,
                phase="failed",
                diagnostics=_failure_diagnostics(diagnostics),
            )

        session.add(environment)
        session.flush()

    def _reconcile_teardown(self, session: Session, workflow: OrchestrationWorkflow) -> None:
        environment = session.get(DemoEnvironment, workflow.environmentId)
        if environment is None:
            return

        if workflow.status == WorkflowStatus.COMPLETED:
            environment.lifecycleState = DemoEnvironmentState.TORN_DOWN
            environment.activeDeploymentRevisionId = None
        else:
            environment.lifecycleState = DemoEnvironmentState.TEARDOWN_FAILED
            _record_operation_diagnostics(
                environment,
                operation_id=workflow.operationId,
                phase="failed",
                diagnostics=_failure_diagnostics(dict(workflow.diagnostics or {})),
            )

        session.add(environment)
        session.flush()

    def _reconcile_deploy(self, session: Session, workflow: OrchestrationWorkflow) -> None:
        deployment_revision_id = dict(workflow.diagnostics or {}).get(DEPLOYMENT_REVISION_ID_KEY)
        if not deployment_revision_id:
            return
        revision = session.get(DeploymentRevision, deployment_revision_id)
        environment = session.get(DemoEnvironment, workflow.environmentId)
        if revision is None:
            return

        if workflow.status == WorkflowStatus.COMPLETED:
            outcome_diagnostics = dict(workflow.diagnostics or {})
            revision.lifecycleState = DeploymentRevisionState.READY
            revision.health = {
                "status": "healthy",
                "vllmBaseUrl": outcome_diagnostics.get("vllmBaseUrl"),
                "diagnostics": [],
            }
            if environment is not None:
                statement = select(DeploymentRevision).where(
                    DeploymentRevision.environmentId == workflow.environmentId,
                    DeploymentRevision.lifecycleState == DeploymentRevisionState.READY,
                    DeploymentRevision.deploymentRevisionId != deployment_revision_id,
                )
                for previous in session.scalars(statement).all():
                    previous.lifecycleState = DeploymentRevisionState.SUPERSEDED
                    session.add(previous)
                environment.activeDeploymentRevisionId = deployment_revision_id
        else:
            revision.lifecycleState = DeploymentRevisionState.DEPLOYMENT_FAILED
            revision.health = {
                "status": "unhealthy",
                "diagnostics": [str(dict(workflow.diagnostics or {}).get("error", "unknown"))],
            }

        session.add(revision)
        if environment is not None:
            session.add(environment)
        session.flush()
