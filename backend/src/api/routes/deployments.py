from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.errors import ApiError, with_request_id
from src.api.routes.environments import _provider, _user
from src.domain.catalog import ModelCatalogEntry
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DeploymentRevisionState
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import (
    EnvironmentLockedError,
    EnvironmentLockService,
    EnvironmentNotFoundError,
)
from src.domain.hf_credentials import accept_hf_token, assert_hf_token_not_persisted
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.persistence.db import get_db_session
from src.providers.azure.adapter import AzureProviderAdapter

router = APIRouter(tags=["deployments"])


class DeploymentCreateRequest(BaseModel):
    modelConfigId: str
    inferenceConfigId: str
    huggingFaceToken: str | None = None


def _require_environment(session: Session, environment_id: str) -> DemoEnvironment:
    environment = session.get(DemoEnvironment, environment_id)
    if environment is None:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=f"Environment '{environment_id}' was not found.",
            details={"environmentId": environment_id},
        )
    return environment


def _serialize_deployment(
    revision: DeploymentRevision,
    health: dict[str, object],
    *,
    model_configuration: ModelConfiguration | None = None,
    inference_configuration: InferenceConfiguration | None = None,
) -> dict[str, object]:
    return {
        "deploymentRevisionId": revision.deploymentRevisionId,
        "environmentId": revision.environmentId,
        "modelConfigId": revision.modelConfigId,
        "inferenceConfigId": revision.inferenceConfigId,
        "engineId": revision.engineId,
        "lifecycleState": revision.lifecycleState.value,
        "activePeriod": {
            "startedAt": dict(revision.activePeriod or {}).get("startedAt"),
            "endedAt": dict(revision.activePeriod or {}).get("endedAt"),
        },
        "health": {
            "status": str(health.get("status") or "unknown"),
            "diagnostics": list(health.get("diagnostics") or []),
        },
        "createdAt": revision.createdAt.isoformat(),
        # Resolved model/engine/settings values so operators don't have to
        # cross-reference bare config ids to understand what is deployed.
        "configuration": {
            "catalogEntryId": getattr(model_configuration, "catalogEntryId", None),
            "resolvedCheckpointRef": getattr(model_configuration, "resolvedCheckpointRef", None),
            "modelSettings": dict(getattr(model_configuration, "modelSettings", {}) or {}),
            "servingSettings": dict(getattr(inference_configuration, "servingSettings", {}) or {}),
            "generationSettings": dict(
                getattr(inference_configuration, "generationSettings", {}) or {}
            ),
        },
    }


@router.post("/environments/{environment_id}/deployments", status_code=202)
def create_deployment(
    environment_id: str,
    payload: DeploymentCreateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    environment = _require_environment(session, environment_id)
    operation_id = getattr(request.state, "operation_id", None) or f"deploy-{environment_id}"
    try:
        EnvironmentLockService().acquire(
            session, environment_id=environment_id, operation_id=operation_id
        )
    except EnvironmentNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=str(exc),
            details={"environmentId": environment_id},
        ) from exc
    except EnvironmentLockedError as exc:
        raise ApiError(
            status_code=409,
            code="environment_locked",
            message=str(exc),
            details={"environmentId": environment_id},
        ) from exc

    # Read configuration rows only after the shared writer lock: cleanup may
    # have deleted an unreferenced row while this request waited for the lock.
    model_configuration = session.get(ModelConfiguration, payload.modelConfigId)
    if model_configuration is None or model_configuration.environmentId != environment_id:
        raise ApiError(
            status_code=404,
            code="model_configuration_not_found",
            message=f"Model configuration '{payload.modelConfigId}' was not found.",
            details={"modelConfigId": payload.modelConfigId},
        )

    inference_configuration = session.get(InferenceConfiguration, payload.inferenceConfigId)
    if inference_configuration is None or inference_configuration.environmentId != environment_id:
        raise ApiError(
            status_code=404,
            code="inference_configuration_not_found",
            message=f"Inference configuration '{payload.inferenceConfigId}' was not found.",
            details={"inferenceConfigId": payload.inferenceConfigId},
        )

    catalog_entry = session.get(ModelCatalogEntry, model_configuration.catalogEntryId)
    if catalog_entry is None:
        raise ApiError(
            status_code=404,
            code="catalog_entry_not_found",
            message=f"Catalog entry '{model_configuration.catalogEntryId}' was not found.",
            details={"catalogEntryId": model_configuration.catalogEntryId},
        )

    hf_token = accept_hf_token(payload.huggingFaceToken)
    if catalog_entry.isGated and hf_token is None:
        raise ApiError(
            status_code=400,
            code="hf_token_required",
            message="This checkpoint requires a Hugging Face token for deployment.",
            details={"catalogEntryId": catalog_entry.catalogEntryId},
        )

    next_id = session.scalar(
        select(func.count())
        .select_from(DeploymentRevision)
        .where(DeploymentRevision.environmentId == environment_id)
    )
    deployment_revision_id = f"{environment_id}-deployment-{int(next_id or 0) + 1}"
    user = _user(request)
    revision = DeploymentRevision(
        deploymentRevisionId=deployment_revision_id,
        environmentId=environment_id,
        modelConfigId=model_configuration.modelConfigId,
        inferenceConfigId=inference_configuration.inferenceConfigId,
        engineId=inference_configuration.engineId,
        lifecycleState=DeploymentRevisionState.PENDING,
        activePeriod={"startedAt": None, "endedAt": None},
        health={"status": "unknown", "diagnostics": []},
        createdBy=user.email,
    )
    session.add(revision)
    environment.providerState = {
        **dict(environment.providerState or {}),
        "currentOperation": {
            "operationId": operation_id,
            "phase": "accepted",
            "state": DeploymentRevisionState.DEPLOYING.value,
            "updatedAt": datetime.now(UTC).isoformat(),
            "diagnostics": [],
        },
    }
    session.add(environment)
    session.commit()
    assert_hf_token_not_persisted(environment.providerState)
    assert_hf_token_not_persisted(revision.health)

    try:
        handle = provider.start_deployment(
            environment_id=environment_id,
            deployment_revision_id=deployment_revision_id,
            operation_id=operation_id,
            actor_email=user.email,
            model_config={
                "modelConfigId": model_configuration.modelConfigId,
                "catalogEntryId": model_configuration.catalogEntryId,
                "huggingFaceRepoId": catalog_entry.huggingFaceRepoId,
                "resolvedCheckpointRef": model_configuration.resolvedCheckpointRef,
                "modelSettings": dict(model_configuration.modelSettings or {}),
            },
            inference_config={
                "inferenceConfigId": inference_configuration.inferenceConfigId,
                "engineId": inference_configuration.engineId,
                "servingSettings": dict(inference_configuration.servingSettings or {}),
                "generationSettings": dict(inference_configuration.generationSettings or {}),
            },
            engine_id=inference_configuration.engineId,
            target_environment={
                "environmentId": environment.environmentId,
                "providerState": dict(environment.providerState or {}),
                "baseUrl": dict(environment.providerState or {}).get("inferenceApiUrl"),
            },
            hugging_face_token=hf_token,
        )
    except Exception as exc:
        with request.app.state.session_factory() as retry_session:
            failed_revision = retry_session.get(DeploymentRevision, deployment_revision_id)
            failed_environment = retry_session.get(DemoEnvironment, environment_id)
            if failed_revision is not None:
                failed_revision.lifecycleState = DeploymentRevisionState.DEPLOYMENT_FAILED
                failed_revision.health = {"status": "unhealthy", "diagnostics": [str(exc)]}
                retry_session.add(failed_revision)
            if failed_environment is not None:
                failed_environment.activeOperationId = None
                retry_session.add(failed_environment)
            retry_session.commit()
        raise ApiError(
            status_code=500,
            code="deployment_start_failed",
            message="The deployment revision was created, but orchestration could not start.",
            details={
                "environmentId": environment_id,
                "deploymentRevisionId": deployment_revision_id,
            },
        ) from exc

    return with_request_id(
        {
            "operationId": handle.operationId,
            "deploymentRevisionId": handle.deploymentRevisionId,
            "phase": handle.phase,
            "lifecycleState": handle.state,
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/environments/{environment_id}/deployments/{revision_id}")
def get_deployment(
    environment_id: str,
    revision_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    _require_environment(session, environment_id)
    revision = session.get(DeploymentRevision, revision_id)
    if revision is None or revision.environmentId != environment_id:
        raise ApiError(
            status_code=404,
            code="deployment_revision_not_found",
            message=f"Deployment revision '{revision_id}' was not found.",
            details={"deploymentRevisionId": revision_id, "environmentId": environment_id},
        )

    health = dict(revision.health or {})
    try:
        health_status = provider.get_engine_adapter(revision.engineId).getHealth(revision_id)
    except Exception:
        health_status = None
    if health_status is not None:
        health = dict(health_status.details)
        revision.health = health
        session.add(revision)
        session.commit()

    return with_request_id(
        _serialize_deployment(
            revision,
            health,
            model_configuration=session.get(ModelConfiguration, revision.modelConfigId),
            inference_configuration=session.get(InferenceConfiguration, revision.inferenceConfigId),
        ),
        getattr(request.state, "request_id", None),
    )
