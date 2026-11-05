from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.domain.common import generate_uuid, utcnow
from src.domain.enums import WorkflowStatus, WorkflowType
from src.domain.environment_lock import EnvironmentLockService
from src.domain.orchestration_workflow import OrchestrationWorkflow

_TERMINAL_STATUSES = frozenset(
    {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
)


class OrchestrationWorkflowError(Exception):
    """Base error for Orchestration Workflow lifecycle operations."""


class WorkflowNotFoundError(OrchestrationWorkflowError):
    def __init__(self, workflow_id: str) -> None:
        super().__init__(f"Orchestration workflow '{workflow_id}' was not found.")
        self.workflow_id = workflow_id


class WorkflowNotRunningError(OrchestrationWorkflowError):
    """Raised when a callback targets a workflow FastAPI is no longer tracking as
    non-terminal (contracts/api.md: "FastAPI rejects a callback whose workflowId does
    not match a workflow it created and is still tracking as non-terminal")."""

    def __init__(self, workflow_id: str, status: WorkflowStatus) -> None:
        super().__init__(
            f"Orchestration workflow '{workflow_id}' is already '{status.value}' "
            "and can no longer accept progress/completion callbacks."
        )
        self.workflow_id = workflow_id
        self.status = status


class OrchestrationWorkflowService:
    """Create and progress `Orchestration Workflow` records (data-model.md).

    This service only owns workflow-lifecycle bookkeeping and the single-writer lock
    it is tied to (FR-052/FR-055/FR-077). It intentionally does not write any
    workflow-type-specific domain record (e.g. DemoEnvironment.lifecycleState,
    DeploymentRevision.lifecycleState) - that per-workflow-type state machine is
    wired into the Azure ProviderAdapter rewrite (contracts/provider-interface.md
    Azure Implementation Notes), which is the caller that knows how to translate a
    workflow's terminal outcome into the right domain entity's state transition.
    """

    def create_workflow(
        self,
        session: Session,
        *,
        environment_id: str,
        operation_id: str,
        workflow_type: WorkflowType,
        phase: str = "accepted",
    ) -> OrchestrationWorkflow:
        # Acquiring the lock first enforces data-model.md's validation rule: a
        # workflow MUST NOT be created unless the environment's single-writer lock
        # has already been acquired for the same operationId. Raises
        # EnvironmentNotFoundError/EnvironmentLockedError, left to the caller (the
        # API route) to translate into the appropriate HTTP status.
        EnvironmentLockService().acquire(
            session, environment_id=environment_id, operation_id=operation_id
        )
        workflow = OrchestrationWorkflow(
            workflowId=generate_uuid(),
            environmentId=environment_id,
            operationId=operation_id,
            workflowType=workflow_type,
            phase=phase,
            status=WorkflowStatus.RUNNING,
            cancellationRequested=False,
            diagnostics={},
            startedAt=utcnow(),
        )
        session.add(workflow)
        session.flush()
        return workflow

    def get_workflow(self, session: Session, *, workflow_id: str) -> OrchestrationWorkflow:
        workflow = session.get(OrchestrationWorkflow, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        return workflow

    def record_progress(
        self,
        session: Session,
        *,
        workflow_id: str,
        phase: str | None = None,
        dispatched_job_ref: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> OrchestrationWorkflow:
        workflow = self.get_workflow(session, workflow_id=workflow_id)
        if workflow.status in _TERMINAL_STATUSES:
            raise WorkflowNotRunningError(workflow_id, workflow.status)

        if phase is not None:
            workflow.phase = phase
        if dispatched_job_ref is not None:
            workflow.dispatchedJobRef = dispatched_job_ref
        if diagnostics is not None:
            workflow.diagnostics = {**dict(workflow.diagnostics or {}), **diagnostics}
        session.add(workflow)
        session.flush()
        return workflow

    def complete_workflow(
        self,
        session: Session,
        *,
        workflow_id: str,
        status: WorkflowStatus,
        phase: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> OrchestrationWorkflow:
        workflow = self.get_workflow(session, workflow_id=workflow_id)
        if workflow.status in _TERMINAL_STATUSES:
            raise WorkflowNotRunningError(workflow_id, workflow.status)

        # Check ownership under the environment row lock before changing the workflow.
        # The release and terminal write remain atomic until the caller commits.
        EnvironmentLockService().release(
            session,
            environment_id=workflow.environmentId,
            operation_id=workflow.operationId,
        )
        workflow.status = status
        if phase is not None:
            workflow.phase = phase
        if diagnostics is not None:
            workflow.diagnostics = {**dict(workflow.diagnostics or {}), **diagnostics}
        workflow.endedAt = utcnow()
        session.add(workflow)
        session.flush()

        return workflow

    def acknowledge_cancellation(
        self, session: Session, *, workflow_id: str
    ) -> OrchestrationWorkflow:
        # Idempotent by design (contracts/api.md: "repeat acknowledgements are
        # no-ops") - unlike record_progress/complete_workflow, this does not reject
        # an already-terminal workflow, since an ack may legitimately arrive after
        # the workflow has already completed.
        workflow = self.get_workflow(session, workflow_id=workflow_id)
        session.flush()
        return workflow

    def request_cancellation(self, session: Session, *, workflow_id: str) -> OrchestrationWorkflow:
        """Mark cancellation as requested (FR-054), for propagation to the
        dispatched job. Idempotent: calling this repeatedly is a no-op."""
        workflow = self.get_workflow(session, workflow_id=workflow_id)
        if workflow.status not in _TERMINAL_STATUSES:
            workflow.cancellationRequested = True
            session.add(workflow)
            session.flush()
        return workflow
