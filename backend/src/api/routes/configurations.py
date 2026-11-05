from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.api.errors import ApiError, with_request_id
from src.api.routes.environments import _user
from src.domain.catalog import ModelCatalogEntry
from src.domain.common import generate_uuid
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import ProviderType
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import EnvironmentLockedError, EnvironmentLockService
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.inference_engine import InferenceEngine
from src.domain.model_configuration import ModelConfiguration
from src.persistence.db import get_db_session

router = APIRouter(tags=["configurations"])

# Engines that only run against the local Ollama runtime. Any engine not listed
# here is assumed to require the Azure/vLLM provider. This keeps a mismatched
# frontend request (or a stale client) from creating an inference configuration
# that will only fail later, mid-deployment, with a confusing 500.
_LOCAL_ONLY_ENGINE_IDS = {"ollama"}


def _validate_engine_provider_compatibility(environment: DemoEnvironment, engine_id: str) -> None:
    is_local_engine = engine_id in _LOCAL_ONLY_ENGINE_IDS
    is_local_environment = environment.provider == ProviderType.LOCAL
    if is_local_engine != is_local_environment:
        raise ApiError(
            status_code=400,
            code="engine_provider_mismatch",
            message=(
                f"Engine '{engine_id}' is not compatible with this environment's "
                f"provider ('{environment.provider.value}')."
            ),
            details={"engineId": engine_id, "provider": environment.provider.value},
        )


class ModelConfigurationCreateRequest(BaseModel):
    catalogEntryId: str
    resolvedCheckpointRef: str
    modelSettings: dict[str, object] = Field(default_factory=dict)


class InferenceConfigurationCreateRequest(BaseModel):
    engineId: str
    servingSettings: dict[str, object] = Field(default_factory=dict)
    generationSettings: dict[str, object] = Field(default_factory=dict)


def _serialize_model_configuration(configuration: ModelConfiguration) -> dict[str, object]:
    return {
        "modelConfigId": configuration.modelConfigId,
        "catalogEntryId": configuration.catalogEntryId,
        "resolvedCheckpointRef": configuration.resolvedCheckpointRef,
        "modelSettings": dict(configuration.modelSettings or {}),
        "version": configuration.version,
        "createdAt": configuration.createdAt.isoformat(),
    }


def _serialize_inference_configuration(configuration: InferenceConfiguration) -> dict[str, object]:
    return {
        "inferenceConfigId": configuration.inferenceConfigId,
        "engineId": configuration.engineId,
        "servingSettings": dict(configuration.servingSettings or {}),
        "generationSettings": dict(configuration.generationSettings or {}),
        "version": configuration.version,
        "createdAt": configuration.createdAt.isoformat(),
    }


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


@router.post("/environments/{environment_id}/model-configurations", status_code=201)
def create_model_configuration(
    environment_id: str,
    payload: ModelConfigurationCreateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    _require_environment(session, environment_id)
    catalog_entry = session.get(ModelCatalogEntry, payload.catalogEntryId)
    if catalog_entry is None:
        raise ApiError(
            status_code=404,
            code="catalog_entry_not_found",
            message=f"Catalog entry '{payload.catalogEntryId}' was not found.",
            details={"catalogEntryId": payload.catalogEntryId},
        )

    next_version = session.scalar(
        select(func.max(ModelConfiguration.version)).where(
            ModelConfiguration.environmentId == environment_id,
            ModelConfiguration.catalogEntryId == payload.catalogEntryId,
        )
    )
    user = _user(request)
    configuration = ModelConfiguration(
        modelConfigId=generate_uuid(),
        environmentId=environment_id,
        catalogEntryId=payload.catalogEntryId,
        resolvedCheckpointRef=payload.resolvedCheckpointRef,
        modelSettings=dict(payload.modelSettings),
        version=int(next_version or 0) + 1,
        createdBy=user.email,
    )
    session.add(configuration)
    session.commit()
    return with_request_id(
        _serialize_model_configuration(configuration),
        getattr(request.state, "request_id", None),
    )


@router.get("/environments/{environment_id}/model-configurations")
def list_model_configurations(
    environment_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    _require_environment(session, environment_id)
    configurations = session.scalars(
        select(ModelConfiguration)
        .where(ModelConfiguration.environmentId == environment_id)
        .order_by(desc(ModelConfiguration.version), desc(ModelConfiguration.createdAt))
    ).all()
    return with_request_id(
        {"items": [_serialize_model_configuration(item) for item in configurations]},
        getattr(request.state, "request_id", None),
    )


@router.post("/environments/{environment_id}/inference-configurations", status_code=201)
def create_inference_configuration(
    environment_id: str,
    payload: InferenceConfigurationCreateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    environment = _require_environment(session, environment_id)
    engine = session.get(InferenceEngine, payload.engineId)
    if engine is None:
        raise ApiError(
            status_code=404,
            code="engine_not_found",
            message=f"Engine '{payload.engineId}' was not found.",
            details={"engineId": payload.engineId},
        )
    _validate_engine_provider_compatibility(environment, payload.engineId)

    next_version = session.scalar(
        select(func.max(InferenceConfiguration.version)).where(
            InferenceConfiguration.environmentId == environment_id,
            InferenceConfiguration.engineId == payload.engineId,
        )
    )
    user = _user(request)
    configuration = InferenceConfiguration(
        inferenceConfigId=generate_uuid(),
        environmentId=environment_id,
        engineId=payload.engineId,
        servingSettings=dict(payload.servingSettings),
        generationSettings=dict(payload.generationSettings),
        version=int(next_version or 0) + 1,
        createdBy=user.email,
    )
    session.add(configuration)
    session.commit()
    return with_request_id(
        _serialize_inference_configuration(configuration),
        getattr(request.state, "request_id", None),
    )


@router.get("/environments/{environment_id}/inference-configurations")
def list_inference_configurations(
    environment_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    _require_environment(session, environment_id)
    configurations = session.scalars(
        select(InferenceConfiguration)
        .where(InferenceConfiguration.environmentId == environment_id)
        .order_by(desc(InferenceConfiguration.version), desc(InferenceConfiguration.createdAt))
    ).all()
    return with_request_id(
        {"items": [_serialize_inference_configuration(item) for item in configurations]},
        getattr(request.state, "request_id", None),
    )


def _delete_owned_configuration(
    *,
    environment_id: str,
    configuration_id: str,
    model: type[ModelConfiguration] | type[InferenceConfiguration],
    request: Request,
    session: Session,
) -> Response:
    _require_environment(session, environment_id)
    operation_id = f"delete-configuration-{generate_uuid()}"
    locks = EnvironmentLockService()
    try:
        locks.acquire(session, environment_id=environment_id, operation_id=operation_id)
    except EnvironmentLockedError as exc:
        raise ApiError(
            status_code=409,
            code="environment_busy",
            message="Configuration cleanup requires an idle environment.",
            details={"environmentId": environment_id, "operationId": exc.active_operation_id},
        ) from exc

    configuration = session.get(model, configuration_id)
    if configuration is None or configuration.environmentId != environment_id:
        raise ApiError(
            status_code=404,
            code="configuration_not_found",
            message="The configuration was not found in this environment.",
            details={"environmentId": environment_id, "configurationId": configuration_id},
        )
    if configuration.createdBy != _user(request).email:
        raise ApiError(
            status_code=403,
            code="configuration_not_owned",
            message="Only the operator who created this configuration can delete it.",
            details={"configurationId": configuration_id},
        )
    reference = (
        DeploymentRevision.modelConfigId
        if model is ModelConfiguration
        else DeploymentRevision.inferenceConfigId
    )
    revision_id = session.scalar(
        select(DeploymentRevision.deploymentRevisionId)
        .where(reference == configuration_id)
        .limit(1)
    )
    if revision_id is not None:
        raise ApiError(
            status_code=409,
            code="configuration_in_use",
            message="Configurations referenced by any deployment revision must be retained.",
            details={"configurationId": configuration_id, "deploymentRevisionId": revision_id},
        )
    session.delete(configuration)
    locks.release(session, environment_id=environment_id, operation_id=operation_id)
    session.commit()
    return Response(status_code=204)


@router.delete(
    "/environments/{environment_id}/model-configurations/{configuration_id}", status_code=204
)
def delete_model_configuration(
    environment_id: str,
    configuration_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    return _delete_owned_configuration(
        environment_id=environment_id,
        configuration_id=configuration_id,
        model=ModelConfiguration,
        request=request,
        session=session,
    )


@router.delete(
    "/environments/{environment_id}/inference-configurations/{configuration_id}", status_code=204
)
def delete_inference_configuration(
    environment_id: str,
    configuration_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    return _delete_owned_configuration(
        environment_id=environment_id,
        configuration_id=configuration_id,
        model=InferenceConfiguration,
        request=request,
        session=session,
    )
