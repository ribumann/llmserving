from __future__ import annotations

import pytest
from src.domain.enums import WorkflowStatus, WorkflowType
from src.domain.environment_lock import EnvironmentLockedError, EnvironmentNotFoundError
from src.domain.orchestration_workflow_service import (
    OrchestrationWorkflowService,
    WorkflowNotFoundError,
    WorkflowNotRunningError,
)
from tests.support.demo_backend import MemorySession


@pytest.fixture
def session() -> MemorySession:
    memory_session = MemorySession()
    memory_session.seed_defaults()
    return memory_session


def test_create_workflow_acquires_lock_and_persists_running_workflow(
    session: MemorySession,
) -> None:
    service = OrchestrationWorkflowService()

    workflow = service.create_workflow(
        session,
        environment_id="env-demo",
        operation_id="op-1",
        workflow_type=WorkflowType.PROVISION,
    )

    assert workflow.status == WorkflowStatus.RUNNING
    assert workflow.phase == "accepted"
    assert session.environments["env-demo"].activeOperationId == "op-1"
    assert session.orchestration_workflows[workflow.workflowId] is workflow


def test_create_workflow_rejects_unknown_environment(session: MemorySession) -> None:
    service = OrchestrationWorkflowService()

    with pytest.raises(EnvironmentNotFoundError):
        service.create_workflow(
            session,
            environment_id="env-missing",
            operation_id="op-1",
            workflow_type=WorkflowType.PROVISION,
        )


def test_create_workflow_rejects_when_lock_already_held_by_another_operation(
    session: MemorySession,
) -> None:
    service = OrchestrationWorkflowService()
    service.create_workflow(
        session, environment_id="env-demo", operation_id="op-1", workflow_type=WorkflowType.DEPLOY
    )

    with pytest.raises(EnvironmentLockedError):
        service.create_workflow(
            session,
            environment_id="env-demo",
            operation_id="op-2",
            workflow_type=WorkflowType.DEPLOY,
        )


def test_record_progress_updates_phase_and_merges_diagnostics(session: MemorySession) -> None:
    service = OrchestrationWorkflowService()
    workflow = service.create_workflow(
        session, environment_id="env-demo", operation_id="op-1", workflow_type=WorkflowType.DEPLOY
    )

    service.record_progress(session, workflow_id=workflow.workflowId, diagnostics={"step": 1})
    updated = service.record_progress(
        session,
        workflow_id=workflow.workflowId,
        phase="pulling-image",
        dispatched_job_ref="job-exec-123",
        diagnostics={"step": 2},
    )

    assert updated.phase == "pulling-image"
    assert updated.dispatchedJobRef == "job-exec-123"
    # Diagnostics merge across calls rather than replacing wholesale.
    assert updated.diagnostics == {"step": 2}


def test_record_progress_rejects_unknown_workflow(session: MemorySession) -> None:
    service = OrchestrationWorkflowService()

    with pytest.raises(WorkflowNotFoundError):
        service.record_progress(session, workflow_id="unknown", phase="x")


def test_record_progress_rejects_already_terminal_workflow(session: MemorySession) -> None:
    service = OrchestrationWorkflowService()
    workflow = service.create_workflow(
        session,
        environment_id="env-demo",
        operation_id="op-1",
        workflow_type=WorkflowType.TEARDOWN,
    )
    service.complete_workflow(
        session, workflow_id=workflow.workflowId, status=WorkflowStatus.COMPLETED
    )

    with pytest.raises(WorkflowNotRunningError):
        service.record_progress(session, workflow_id=workflow.workflowId, phase="too-late")


@pytest.mark.parametrize(
    "status", [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
)
def test_complete_workflow_releases_the_environment_lock(
    session: MemorySession, status: WorkflowStatus
) -> None:
    service = OrchestrationWorkflowService()
    workflow = service.create_workflow(
        session, environment_id="env-demo", operation_id="op-1", workflow_type=WorkflowType.EXPORT
    )

    completed = service.complete_workflow(session, workflow_id=workflow.workflowId, status=status)

    assert completed.status == status
    assert completed.endedAt is not None
    assert session.environments["env-demo"].activeOperationId is None


@pytest.mark.parametrize("owner", ["new-operation", None])
@pytest.mark.parametrize(
    "status", [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
)
def test_stale_completion_preserves_lock_and_workflow(
    session: MemorySession, owner: str | None, status: WorkflowStatus
) -> None:
    service = OrchestrationWorkflowService()
    workflow = service.create_workflow(
        session,
        environment_id="env-demo",
        operation_id="old-operation",
        workflow_type=WorkflowType.PROVISION,
    )
    session.environments["env-demo"].activeOperationId = owner

    with pytest.raises(EnvironmentLockedError):
        service.complete_workflow(
            session,
            workflow_id=workflow.workflowId,
            status=status,
            phase="late-completion",
            diagnostics={"late": True},
        )

    assert session.environments["env-demo"].activeOperationId == owner
    assert workflow.status == WorkflowStatus.RUNNING
    assert workflow.phase == "accepted"
    assert workflow.diagnostics == {}
    assert workflow.endedAt is None


def test_complete_workflow_rejects_already_terminal_workflow(session: MemorySession) -> None:
    service = OrchestrationWorkflowService()
    workflow = service.create_workflow(
        session,
        environment_id="env-demo",
        operation_id="op-1",
        workflow_type=WorkflowType.EVALUATE_GOLDEN,
    )
    service.complete_workflow(
        session, workflow_id=workflow.workflowId, status=WorkflowStatus.COMPLETED
    )

    with pytest.raises(WorkflowNotRunningError):
        service.complete_workflow(
            session, workflow_id=workflow.workflowId, status=WorkflowStatus.FAILED
        )


def test_acknowledge_cancellation_is_idempotent_even_after_completion(
    session: MemorySession,
) -> None:
    service = OrchestrationWorkflowService()
    workflow = service.create_workflow(
        session,
        environment_id="env-demo",
        operation_id="op-1",
        workflow_type=WorkflowType.PERFORMANCE_TEST,
    )
    service.complete_workflow(
        session, workflow_id=workflow.workflowId, status=WorkflowStatus.CANCELLED
    )

    first = service.acknowledge_cancellation(session, workflow_id=workflow.workflowId)
    second = service.acknowledge_cancellation(session, workflow_id=workflow.workflowId)

    assert first.status == WorkflowStatus.CANCELLED
    assert second.status == WorkflowStatus.CANCELLED


def test_request_cancellation_sets_flag_once_and_ignores_terminal_workflows(
    session: MemorySession,
) -> None:
    service = OrchestrationWorkflowService()
    workflow = service.create_workflow(
        session, environment_id="env-demo", operation_id="op-1", workflow_type=WorkflowType.DEPLOY
    )

    updated = service.request_cancellation(session, workflow_id=workflow.workflowId)
    assert updated.cancellationRequested is True

    service.complete_workflow(
        session, workflow_id=workflow.workflowId, status=WorkflowStatus.CANCELLED
    )
    after_terminal = service.request_cancellation(session, workflow_id=workflow.workflowId)
    assert after_terminal.cancellationRequested is True
