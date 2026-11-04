from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.correlation import workflow_correlation
from src.api.errors import ApiError, with_request_id
from src.api.internal_auth import InternalCaller, require_internal_identity
from src.domain.enums import WorkflowStatus, WorkflowType
from src.domain.environment_lock import EnvironmentLockedError, EnvironmentNotFoundError
from src.domain.hf_credentials import (
    assert_hf_token_not_persisted,
    assert_no_interactive_prompt_payload,
)
from src.domain.orchestration_workflow import OrchestrationWorkflow
from src.domain.orchestration_workflow_service import (
    OrchestrationWorkflowService,
    WorkflowNotFoundError,
    WorkflowNotRunningError,
)
from src.domain.workflow_reconciliation import WorkflowReconciliationService
from src.persistence.db import get_db_session

router = APIRouter(prefix="/internal/workflows", tags=["internal-orchestration"])
LOGGER = logging.getLogger(__name__)

_TERMINAL_STATUSES = {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}


class WorkflowCreateRequest(BaseModel):
    environmentId: str
    operationId: str
    workflowType: WorkflowType
    phase: str = "accepted"


class WorkflowProgressRequest(BaseModel):
    phase: str | None = None
    dispatchedJobRef: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class WorkflowCompleteRequest(BaseModel):
    status: WorkflowStatus
    phase: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _guard_callback_payload(payload: dict[str, Any]) -> None:
    """Reject a PATCH/complete callback payload carrying an HF credential or
    interactive prompt/response body with 400 (FR-082/FR-084, contracts/api.md)."""
    try:
        assert_hf_token_not_persisted(payload)
        assert_no_interactive_prompt_payload(payload)
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            code="callback_payload_rejected",
            message=str(exc),
            details={},
        ) from exc


def _serialize(workflow: OrchestrationWorkflow) -> dict[str, Any]:
    return {
        "workflowId": workflow.workflowId,
        "environmentId": workflow.environmentId,
        "operationId": workflow.operationId,
        "workflowType": workflow.workflowType.value,
        "dispatchedJobRef": workflow.dispatchedJobRef,
        "phase": workflow.phase,
        "status": workflow.status.value,
        "cancellationRequested": workflow.cancellationRequested,
        "diagnostics": dict(workflow.diagnostics or {}),
        "startedAt": workflow.startedAt.isoformat(),
        "endedAt": workflow.endedAt.isoformat() if workflow.endedAt else None,
    }


@router.post("", status_code=201)
def create_workflow(
    payload: WorkflowCreateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    _caller: InternalCaller = Depends(require_internal_identity),
) -> dict[str, Any]:
    service = OrchestrationWorkflowService()
    try:
        workflow = service.create_workflow(
            session,
            environment_id=payload.environmentId,
            operation_id=payload.operationId,
            workflow_type=payload.workflowType,
            phase=payload.phase,
        )
    except EnvironmentNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=str(exc),
            details={"environmentId": payload.environmentId},
        ) from exc
    except EnvironmentLockedError as exc:
        raise ApiError(
            status_code=409,
            code="environment_locked",
            message=str(exc),
            details={"environmentId": payload.environmentId},
        ) from exc

    session.commit()
    with workflow_correlation(workflow.workflowId):
        LOGGER.info("Created workflow type=%s phase=%s", payload.workflowType.value, workflow.phase)
    return with_request_id(_serialize(workflow), getattr(request.state, "request_id", None))


@router.patch("/{workflow_id}")
def report_progress(
    workflow_id: str,
    payload: WorkflowProgressRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    _caller: InternalCaller = Depends(require_internal_identity),
) -> dict[str, Any]:
    _guard_callback_payload(payload.model_dump())
    with workflow_correlation(workflow_id):
        service = OrchestrationWorkflowService()
        try:
            workflow = service.record_progress(
                session,
                workflow_id=workflow_id,
                phase=payload.phase,
                dispatched_job_ref=payload.dispatchedJobRef,
                diagnostics=payload.diagnostics,
            )
        except WorkflowNotFoundError as exc:
            raise ApiError(
                status_code=404,
                code="workflow_not_found",
                message=str(exc),
                details={"workflowId": workflow_id},
            ) from exc
        except WorkflowNotRunningError as exc:
            raise ApiError(
                status_code=409,
                code="workflow_not_running",
                message=str(exc),
                details={"workflowId": workflow_id},
            ) from exc

        session.commit()
        LOGGER.info("Recorded workflow progress phase=%s", payload.phase)
    return with_request_id(_serialize(workflow), getattr(request.state, "request_id", None))


@router.post("/{workflow_id}/complete")
def complete_workflow(
    workflow_id: str,
    payload: WorkflowCompleteRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    _caller: InternalCaller = Depends(require_internal_identity),
) -> dict[str, Any]:
    _guard_callback_payload(payload.model_dump())
    if payload.status not in _TERMINAL_STATUSES:
        raise ApiError(
            status_code=400,
            code="invalid_terminal_status",
            message="'status' must be one of: completed, failed, cancelled.",
            details={"status": payload.status.value},
        )

    with workflow_correlation(workflow_id):
        service = OrchestrationWorkflowService()
        try:
            workflow = service.complete_workflow(
                session,
                workflow_id=workflow_id,
                status=payload.status,
                phase=payload.phase,
                diagnostics=payload.diagnostics,
            )
        except WorkflowNotFoundError as exc:
            raise ApiError(
                status_code=404,
                code="workflow_not_found",
                message=str(exc),
                details={"workflowId": workflow_id},
            ) from exc
        except WorkflowNotRunningError as exc:
            raise ApiError(
                status_code=409,
                code="workflow_not_running",
                message=str(exc),
                details={"workflowId": workflow_id},
            ) from exc

        # Translates this workflow's now-terminal outcome into the DemoEnvironment/
        # DeploymentRevision state change it implies (T140/T144) - in the same
        # transaction as the workflow's own terminal-state write above, so an
        # environment/revision only ever resolves via this callback, never by a
        # client polling Terraform or the job directly.
        WorkflowReconciliationService().reconcile(session, workflow=workflow)

        session.commit()
        LOGGER.info("Completed workflow status=%s", payload.status.value)
    return with_request_id(_serialize(workflow), getattr(request.state, "request_id", None))


@router.post("/{workflow_id}/cancel-ack")
def acknowledge_cancellation(
    workflow_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
    _caller: InternalCaller = Depends(require_internal_identity),
) -> dict[str, Any]:
    with workflow_correlation(workflow_id):
        service = OrchestrationWorkflowService()
        try:
            workflow = service.acknowledge_cancellation(session, workflow_id=workflow_id)
        except WorkflowNotFoundError as exc:
            raise ApiError(
                status_code=404,
                code="workflow_not_found",
                message=str(exc),
                details={"workflowId": workflow_id},
            ) from exc
        LOGGER.info("Acknowledged workflow cancellation")

    session.commit()
    return with_request_id(_serialize(workflow), getattr(request.state, "request_id", None))
