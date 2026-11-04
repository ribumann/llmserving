from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.auth import AuthenticatedUser
from src.api.errors import ApiError, with_request_id
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DemoEnvironmentState, ProviderType
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import (
    EnvironmentLockedError,
    EnvironmentLockError,
    EnvironmentLockService,
    EnvironmentNotFoundError,
)
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.domain.profile import CloudDeploymentProfile
from src.persistence.db import get_db_session
from src.providers.azure.adapter import AzureProviderAdapter

router = APIRouter(tags=["environments"])


class EnvironmentPreviewRequest(BaseModel):
    profileId: str
    regionOverride: str | None = None


class EnvironmentCreateRequest(BaseModel):
    profileId: str
    region: str | None = None
    configurableInputs: dict[str, object] = Field(default_factory=dict)


class TeardownRequest(BaseModel):
    previewToken: str


def _enum_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value


def _provider(request: Request) -> AzureProviderAdapter:
    provider = getattr(request.app.state, "provider_adapter", None)
    if provider is None:
        raise ApiError(
            status_code=503,
            code="provider_unavailable",
            message="The Azure provider adapter is not configured.",
            details={},
        )
    return provider


def _user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise ApiError(
            status_code=401,
            code="authentication_required",
            message="Organization SSO authentication is required.",
            details={},
        )
    return user


def _serialize_environment(environment: DemoEnvironment) -> dict[str, object]:
    return {
        "environmentId": environment.environmentId,
        "profileId": environment.profileId,
        "provider": _enum_value(environment.provider),
        "region": environment.region,
        "regionRecommendation": environment.regionRecommendation,
        "lifecycleState": _enum_value(environment.lifecycleState),
        "activeDeploymentRevisionId": environment.activeDeploymentRevisionId,
        "providerState": environment.providerState,
        "createdBy": environment.createdBy,
        "lastModifiedBy": environment.lastModifiedBy,
        "createdAt": environment.createdAt.isoformat(),
        "updatedAt": environment.updatedAt.isoformat(),
    }


def _generate_admin_ssh_keypair() -> tuple[str, str]:
    """Generate a fresh RSA admin SSH keypair for a demo VM.

    Returns (public_key_openssh, private_key_pem). Each environment gets its own
    keypair rather than sharing a hardcoded placeholder, so the resulting VM is
    actually reachable over SSH/Bastion without any manual key exchange.

    Azure's `admin_ssh_key` only accepts RSA keys (ed25519 is rejected with
    "Only RSA SSH keys are supported by Azure"), so RSA-3072 is used here.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_openssh = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode("ascii")
    )
    return public_openssh, private_pem


def _terraform_variables(
    *,
    environment_id: str,
    profile: CloudDeploymentProfile,
    settings: object,
    inputs: dict[str, object],
) -> dict[str, object]:
    """Build infra/demo's actual Terraform variable set (T140).

    No CIDR allowlist, Hugging Face token/model repo, or SSH-private-key
    persistence variables exist in this schema: the demo GPU VM has no public
    IP and no SSH/Bastion path at all (FR-079, infra/demo/variables.tf), and
    vLLM is started later via the separate `deploy` workflow rather than
    during provisioning.
    """
    defaults = dict(profile.configurableInputs or {})
    defaults.update(inputs)
    settings_obj = settings

    admin_ssh_public_key = defaults.get("adminSshPublicKey")
    if not admin_ssh_public_key:
        # No key supplied by the caller: generate a fresh, valid keypair so Azure's
        # admin_ssh_key resource validates successfully during apply (a hardcoded
        # placeholder string is not valid SSH key data). The private half is
        # discarded immediately - there is no SSH/Bastion path to use it with, so
        # persisting it would only be a needless secret to manage.
        admin_ssh_public_key, _admin_ssh_private_key_pem = _generate_admin_ssh_keypair()

    return {
        "subscription_id": getattr(settings_obj, "azure_subscription_id", "") or "",
        "environment_id": environment_id,
        "name_prefix": defaults.get("namePrefix", "llm"),
        "profile_size_class": defaults.get("profileSizeClass", "small"),
        "vm_size": defaults.get("vmSizeOverride"),
        "admin_username": defaults.get("adminUsername", "azureuser"),
        "admin_ssh_public_key": admin_ssh_public_key,
        "vllm_image": defaults.get("vllmImage", getattr(settings_obj, "vllm_image", "")),
        "tags": defaults.get(
            "tags",
            {
                "owner": "azure-llm-serving-demo",
                "profileId": profile.profileId,
            },
        ),
    }


@router.post("/environments/preview")
def preview_environment(
    payload: EnvironmentPreviewRequest,
    request: Request,
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    try:
        evaluation = provider.preview_with_details(
            profileId=payload.profileId,
            regionOverride=payload.regionOverride,
        )
    except LookupError as exc:
        raise ApiError(
            status_code=404,
            code="profile_not_found",
            message=str(exc),
            details={"profileId": payload.profileId},
        ) from exc

    recommendation = evaluation.recommendation
    checked_at = recommendation.evaluatedAt.isoformat()

    def _status(available: bool | None, positive: str, negative: str) -> str:
        if available is True:
            return positive
        if available is False:
            return negative
        return "unknown"

    return with_request_id(
        {
            "profileId": payload.profileId,
            "recommendedRegion": recommendation.recommendedRegion,
            "advisoryMessage": recommendation.uncertaintyNote,
            "assessments": [
                {
                    "region": check.region,
                    "quotaStatus": _status(check.available, "sufficient", "insufficient"),
                    "capacityStatus": _status(check.available, "available", "constrained"),
                    "compatibilityStatus": _status(check.available, "compatible", "incompatible"),
                    "checkedAt": checked_at,
                    "evidence": check.evidence,
                    "uncertainty": (
                        " ".join(check.uncertaintyReasons) if check.uncertaintyReasons else None
                    ),
                }
                for check in evaluation.checks
            ],
        },
        getattr(request.state, "request_id", None),
    )


@router.post("/environments", status_code=202)
def create_environment(
    payload: EnvironmentCreateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    try:
        evaluation = provider.preview_with_details(
            profileId=payload.profileId,
            regionOverride=payload.region,
        )
    except LookupError as exc:
        raise ApiError(
            status_code=404,
            code="profile_not_found",
            message=str(exc),
            details={"profileId": payload.profileId},
        ) from exc

    profile = session.get(CloudDeploymentProfile, payload.profileId)
    if profile is None:
        raise ApiError(
            status_code=404,
            code="profile_not_found",
            message=f"Profile '{payload.profileId}' was not found.",
            details={"profileId": payload.profileId},
        )

    selected_region = payload.region or evaluation.recommendation.recommendedRegion
    operation_id = getattr(request.state, "operation_id", None) or uuid4().hex
    user = _user(request)
    environment_id = uuid4().hex[:12]

    terraform_variables: dict[str, object] = (
        {}
        if profile.provider == ProviderType.LOCAL
        else _terraform_variables(
            environment_id=environment_id,
            profile=profile,
            settings=request.app.state.settings,
            inputs=payload.configurableInputs,
        )
    )

    environment = DemoEnvironment(
        environmentId=environment_id,
        profileId=profile.profileId,
        provider=profile.provider,
        region=selected_region,
        regionRecommendation={
            "recommendedRegion": evaluation.recommendation.recommendedRegion,
            "evidence": evaluation.recommendation.evidence,
            "evaluatedAt": evaluation.recommendation.evaluatedAt.isoformat(),
            "uncertaintyNote": evaluation.recommendation.uncertaintyNote,
            "regionOverrideValidated": evaluation.recommendation.regionOverrideValidated,
        },
        lifecycleState=DemoEnvironmentState.PROVISIONING,
        activeDeploymentRevisionId=None,
        providerState={
            "currentOperation": {
                "operationId": operation_id,
                "phase": "accepted",
                "state": DemoEnvironmentState.PROVISIONING.value,
                "updatedAt": datetime.now(UTC).isoformat(),
                "diagnostics": [],
            }
        },
        createdBy=user.email,
        lastModifiedBy=user.email,
    )
    session.add(environment)
    session.flush()

    try:
        EnvironmentLockService().acquire(
            session, environment_id=environment_id, operation_id=operation_id
        )
    except EnvironmentLockError as exc:
        raise ApiError(
            status_code=409,
            code="environment_locked",
            message=str(exc),
            details={"environmentId": environment_id},
        ) from exc

    session.commit()

    try:
        handle = provider.start_provisioning(
            environment_id=environment_id,
            operation_id=operation_id,
            actor_email=user.email,
            profile=profile,
            region=selected_region,
            terraform_variables=terraform_variables,
        )
    except Exception as exc:
        with request.app.state.session_factory() as retry_session:
            stored_environment = retry_session.get(DemoEnvironment, environment_id)
            if stored_environment is not None:
                stored_environment.lifecycleState = DemoEnvironmentState.PROVISIONING_FAILED
                stored_environment.providerState = {
                    **(stored_environment.providerState or {}),
                    "currentOperation": {
                        "operationId": operation_id,
                        "phase": "failed",
                        "state": DemoEnvironmentState.PROVISIONING_FAILED.value,
                        "updatedAt": datetime.now(UTC).isoformat(),
                        "diagnostics": [str(exc)],
                    },
                }
                stored_environment.activeOperationId = None
                retry_session.add(stored_environment)
                retry_session.commit()
        raise ApiError(
            status_code=500,
            code="provisioning_start_failed",
            message=(
                "The environment record was created, but Terraform orchestration "
                "could not start."
            ),
            details={"environmentId": environment_id},
        ) from exc

    return with_request_id(
        {
            "environmentId": environment_id,
            "operationId": handle.operationId,
            "phase": handle.phase,
            "state": handle.state,
            "diagnostics": handle.diagnostics,
            "region": selected_region,
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/environments")
def list_environments(
    request: Request,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    stmt = select(DemoEnvironment).order_by(DemoEnvironment.updatedAt.desc())
    environments = session.execute(stmt).scalars().all()

    # Resolve active deployment configuration for every environment in one
    # query (instead of per-environment lookups) so operators can see what
    # model/engine is deployed without opening each environment individually.
    active_revision_ids = [
        environment.activeDeploymentRevisionId
        for environment in environments
        if environment.activeDeploymentRevisionId
    ]
    configuration_by_revision: dict[str, dict[str, object]] = {}
    if active_revision_ids:
        rows = session.execute(
            select(DeploymentRevision, ModelConfiguration, InferenceConfiguration)
            .join(
                ModelConfiguration,
                ModelConfiguration.modelConfigId == DeploymentRevision.modelConfigId,
            )
            .join(
                InferenceConfiguration,
                InferenceConfiguration.inferenceConfigId == DeploymentRevision.inferenceConfigId,
            )
            .where(DeploymentRevision.deploymentRevisionId.in_(active_revision_ids))
        ).all()
        for revision, model_configuration, inference_configuration in rows:
            configuration_by_revision[revision.deploymentRevisionId] = {
                "deploymentRevisionId": revision.deploymentRevisionId,
                "lifecycleState": _enum_value(revision.lifecycleState),
                "engineId": revision.engineId,
                "catalogEntryId": model_configuration.catalogEntryId,
                "resolvedCheckpointRef": model_configuration.resolvedCheckpointRef,
                "modelSettings": dict(model_configuration.modelSettings or {}),
                "servingSettings": dict(inference_configuration.servingSettings or {}),
                "generationSettings": dict(inference_configuration.generationSettings or {}),
            }

    return with_request_id(
        {
            "environments": [
                {
                    "environmentId": environment.environmentId,
                    "profileId": environment.profileId,
                    "provider": _enum_value(environment.provider),
                    "region": environment.region,
                    "lifecycleState": _enum_value(environment.lifecycleState),
                    "activeOperationId": environment.activeOperationId,
                    "activeDeploymentRevisionId": environment.activeDeploymentRevisionId,
                    "activeDeploymentConfiguration": configuration_by_revision.get(
                        environment.activeDeploymentRevisionId or ""
                    ),
                    "createdAt": (
                        environment.createdAt.isoformat() if environment.createdAt else None
                    ),
                    "updatedAt": (
                        environment.updatedAt.isoformat() if environment.updatedAt else None
                    ),
                }
                for environment in environments
            ]
        },
        getattr(request.state, "request_id", None),
    )


@router.get("/environments/{environment_id}")
def get_environment(
    environment_id: str,
    request: Request,
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    try:
        state = provider.getEnvironmentState(environment_id)
    except LookupError as exc:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=str(exc),
            details={"environmentId": environment_id},
        ) from exc

    payload = asdict(state)
    return with_request_id(payload, getattr(request.state, "request_id", None))


@router.post("/environments/{environment_id}/teardown/preview")
def preview_teardown(
    environment_id: str,
    request: Request,
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    try:
        preview = provider.teardownPreview(environment_id)
    except LookupError as exc:
        raise ApiError(
            status_code=404,
            code="environment_not_found",
            message=str(exc),
            details={"environmentId": environment_id},
        ) from exc

    return with_request_id(
        {
            "environmentId": preview.environmentId,
            "previewToken": preview.previewToken,
            "resources": list(preview.resources),
            "consequences": list(preview.consequences),
        },
        getattr(request.state, "request_id", None),
    )


@router.post("/environments/{environment_id}/teardown", status_code=202)
def teardown_environment(
    environment_id: str,
    payload: TeardownRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    provider: AzureProviderAdapter = Depends(_provider),
) -> dict[str, object]:
    # Deliberately NOT `request.state.operation_id` (a per-request correlation id):
    # both AzureProviderAdapter.teardownEnvironment and LocalProviderAdapter.
    # teardownEnvironment hardcode this exact "teardown-{environmentId}" operation id
    # internally (see providers/azure/adapter.py, providers/local/adapter.py), and the
    # Azure path re-acquires the single-writer lock with that id from a background
    # thread (provision.py's _run_teardown -> _start_workflow -> create_workflow). The
    # lock acquired here MUST match that id exactly, or the re-acquire is treated as a
    # conflicting operation and teardown fails with a spurious "already locked" error.
    operation_id = f"teardown-{environment_id}"

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

    session.commit()

    try:
        handle = provider.teardownEnvironment(environment_id, payload.previewToken)
    except Exception as exc:
        # Mirrors create_environment's synchronous-dispatch-failure handling above:
        # the async teardown itself reports its own terminal state via the workflow
        # callback (see azure/provision.py's _fail_dispatch), so this only covers a
        # failure to even start dispatching (e.g. no persisted terraform variables to
        # reuse - TeardownVariablesMissingError), releasing the lock so a retry isn't
        # permanently blocked.
        with request.app.state.session_factory() as retry_session:
            stored_environment = retry_session.get(DemoEnvironment, environment_id)
            if stored_environment is not None:
                stored_environment.lifecycleState = DemoEnvironmentState.TEARDOWN_FAILED
                stored_environment.providerState = {
                    **(stored_environment.providerState or {}),
                    "currentOperation": {
                        "operationId": operation_id,
                        "phase": "failed",
                        "state": DemoEnvironmentState.TEARDOWN_FAILED.value,
                        "updatedAt": datetime.now(UTC).isoformat(),
                        "diagnostics": [str(exc)],
                    },
                }
                stored_environment.activeOperationId = None
                retry_session.add(stored_environment)
                retry_session.commit()
        raise ApiError(
            status_code=500,
            code="teardown_start_failed",
            message="The teardown could not be started.",
            details={"environmentId": environment_id},
        ) from exc

    return with_request_id(
        {
            "environmentId": environment_id,
            "operationId": handle.operationId,
            "phase": handle.phase,
            "state": handle.state,
            "diagnostics": handle.diagnostics,
        },
        getattr(request.state, "request_id", None),
    )
