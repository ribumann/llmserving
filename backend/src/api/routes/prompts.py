from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.errors import ApiError, with_request_id
from src.api.routes.environments import _provider
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import EnvironmentLockService, EnvironmentNotFoundError
from src.persistence.db import get_db_session
from src.providers.azure.adapter import AzureProviderAdapter

router = APIRouter(tags=["prompts"])


class PromptRequest(BaseModel):
    prompt: str
    parameters: dict[str, object] = Field(default_factory=dict)


@router.post("/environments/{environment_id}/prompts")
def submit_prompt(
    environment_id: str,
    payload: PromptRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    environment = session.get(DemoEnvironment, environment_id)
    if environment is None:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=f"Environment '{environment_id}' was not found.",
            details={"environmentId": environment_id},
        )

    try:
        lock_state = EnvironmentLockService().current(session, environment_id=environment_id)
    except EnvironmentNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=str(exc),
            details={"environmentId": environment_id},
        ) from exc
    if lock_state.acquired:
        raise ApiError(
            status_code=409,
            code="environment_busy",
            message=f"Environment '{environment_id}' is busy with another operation.",
            details={"environmentId": environment_id, "operationId": lock_state.operation_id},
        )

    active_revision_id = environment.activeDeploymentRevisionId
    active_revision = (
        session.get(DeploymentRevision, active_revision_id) if active_revision_id else None
    )
    if (
        active_revision is None
        or active_revision.environmentId != environment_id
        or active_revision.lifecycleState != DeploymentRevisionState.READY
    ):
        raise ApiError(
            status_code=409,
            code="no_ready_deployment",
            message="The environment has no active ready deployment.",
            details={"environmentId": environment_id},
        )

    engine_adapter = provider.get_engine_adapter(active_revision.engineId)
    result = engine_adapter.submitPromptWithParameters(
        active_revision.deploymentRevisionId,
        payload.prompt,
        payload.parameters,
    )
    return with_request_id(
        {
            "deploymentRevisionId": active_revision.deploymentRevisionId,
            "responseText": result.responseText,
            "timing": result.timing,
            "activeRevision": {
                "deploymentRevisionId": active_revision.deploymentRevisionId,
                "modelConfigId": active_revision.modelConfigId,
                "inferenceConfigId": active_revision.inferenceConfigId,
            },
        },
        getattr(request.state, "request_id", None),
    )
