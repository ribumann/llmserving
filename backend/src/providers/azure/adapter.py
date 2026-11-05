from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings
from src.domain.environment import DemoEnvironment
from src.domain.hf_credentials import HfAccessToken, forwarded_hf_token
from src.domain.profile import CloudDeploymentProfile
from src.engines.vllm.adapter import VllmEngineAdapter
from src.providers.azure.deploy import AzureDeployer, DeploymentContext
from src.providers.azure.preflight import AzureCapacityPreflight
from src.providers.azure.preview import (
    AzurePreviewService,
    PreviewEvaluation,
    resolve_vm_size,
)
from src.providers.azure.provision import AzureProvisioner, ProvisioningContext
from src.providers.azure.state import AzureEnvironmentStateService
from src.providers.base import (
    DeploymentHandle,
    EnvironmentStateView,
    ProviderAdapter,
    ProvisioningHandle,
    RegionRecommendation,
    TeardownHandle,
    TeardownPreview,
)


class AzureProviderAdapter(ProviderAdapter):
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        telemetry: Any | None = None,
        preview_service: AzurePreviewService | None = None,
        provisioner: AzureProvisioner | None = None,
        deployer: AzureDeployer | None = None,
        state_service: AzureEnvironmentStateService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._telemetry = telemetry
        preflight = AzureCapacityPreflight(
            subscription_id=settings.azure_subscription_id or ""
        )
        self._preview_service = preview_service or AzurePreviewService(
            preflight=preflight
        )
        self._provisioner = provisioner or AzureProvisioner(
            session_factory=session_factory,
            settings=settings,
            telemetry=telemetry,
        )
        self._engine_adapter = VllmEngineAdapter(
            session_factory=session_factory,
            timeout_seconds=settings.vllm_prompt_timeout_seconds,
        )
        self._deployer = deployer or AzureDeployer(
            session_factory=session_factory,
            settings=settings,
            telemetry=telemetry,
        )
        self._state_service = state_service or AzureEnvironmentStateService(
            session_factory=session_factory,
            settings=settings,
        )

    def bind_provisioning_context(
        self,
        *,
        environment_id: str,
        operation_id: str,
        actor_email: str,
        profile: CloudDeploymentProfile,
        region: str,
        terraform_variables: dict[str, Any],
    ) -> None:
        self._provisioner.bind_context(
            self._build_context(
                environment_id=environment_id,
                operation_id=operation_id,
                actor_email=actor_email,
                profile=profile,
                region=region,
                terraform_variables=terraform_variables,
            )
        )

    def start_provisioning(
        self,
        *,
        environment_id: str,
        operation_id: str,
        actor_email: str,
        profile: CloudDeploymentProfile,
        region: str,
        terraform_variables: dict[str, Any],
    ) -> ProvisioningHandle:
        """Build and submit a provisioning context atomically (no shared-dict race)."""
        context = self._build_context(
            environment_id=environment_id,
            operation_id=operation_id,
            actor_email=actor_email,
            profile=profile,
            region=region,
            terraform_variables=terraform_variables,
        )
        return self._provisioner.submit(context)

    def _build_context(
        self,
        *,
        environment_id: str,
        operation_id: str,
        actor_email: str,
        profile: CloudDeploymentProfile,
        region: str,
        terraform_variables: dict[str, Any],
    ) -> ProvisioningContext:
        # bootstrapModelRepo is informational only: infra/demo no longer takes a
        # Hugging Face model repo as a Terraform variable at all (vLLM is started
        # later via the separate `deploy` workflow, not during provisioning), so
        # this is read straight from the profile's configurable defaults rather
        # than from terraform_variables.
        bootstrap_model_repo = str(
            dict(profile.configurableInputs or {}).get(
                "bootstrapModelRepo", "Qwen/Qwen3-4B"
            )
        )
        return ProvisioningContext(
            environmentId=environment_id,
            operationId=operation_id,
            actorEmail=actor_email,
            region=region,
            profileId=profile.profileId,
            profileSizeClass=profile.modelSizeClass.value,
            vmSize=resolve_vm_size(
                profile, {"vmSizeOverride": terraform_variables.get("vm_size")}
            ),
            bootstrapModelRepo=bootstrap_model_repo,
            terraformVariables=terraform_variables,
            fallbackRegions=list(profile.eligibleRegions),
        )

    def previewEnvironment(
        self, profileId: str, regionOverride: str | None = None
    ) -> RegionRecommendation:
        evaluation = self.preview_with_details(
            profileId=profileId, regionOverride=regionOverride
        )
        return evaluation.recommendation

    def preview_with_details(
        self,
        *,
        profileId: str,
        regionOverride: str | None = None,
        configurableInputs: Mapping[str, object] | None = None,
    ) -> PreviewEvaluation:
        profile = self._load_profile(profileId)
        return self._preview_service.preview_environment(
            profile=profile,
            region_override=regionOverride,
            configurable_inputs=configurableInputs,
        )

    def provisionEnvironment(self, profileId: str, region: str) -> ProvisioningHandle:
        return self._provisioner.provisionEnvironment(profileId, region)

    def getEnvironmentState(self, environmentId: str) -> EnvironmentStateView:
        return self._state_service.getEnvironmentState(environmentId)

    def deployRevision(
        self,
        environmentId: str,
        modelConfig: Mapping[str, Any],
        inferenceConfig: Mapping[str, Any],
        engineId: str,
    ) -> DeploymentHandle:
        return self.start_deployment(
            environment_id=environmentId,
            deployment_revision_id=str(
                modelConfig.get("deploymentRevisionId") or "pending"
            ),
            operation_id=f"deploy-{environmentId}",
            actor_email="system",
            model_config=dict(modelConfig),
            inference_config=dict(inferenceConfig),
            engine_id=engineId,
            target_environment={},
        )

    def start_deployment(
        self,
        *,
        environment_id: str,
        deployment_revision_id: str,
        operation_id: str,
        actor_email: str,
        model_config: Mapping[str, Any],
        inference_config: Mapping[str, Any],
        engine_id: str,
        target_environment: Mapping[str, Any],
        hugging_face_token: HfAccessToken | None = None,
    ) -> DeploymentHandle:
        with forwarded_hf_token(hugging_face_token) as hf_token_value:
            return self._deployer.submit(
                DeploymentContext(
                    environmentId=environment_id,
                    deploymentRevisionId=deployment_revision_id,
                    operationId=operation_id,
                    actorEmail=actor_email,
                    engineId=engine_id,
                    modelConfig=dict(model_config),
                    inferenceConfig=dict(inference_config),
                    targetEnvironment=dict(target_environment),
                    hfToken=hf_token_value or "",
                )
            )

    def get_engine_adapter(self, engine_id: str) -> VllmEngineAdapter:
        if engine_id != "vllm":
            raise LookupError(f"Engine '{engine_id}' is not supported.")
        return self._engine_adapter

    def teardownPreview(self, environmentId: str) -> TeardownPreview:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environmentId)
            if environment is None:
                raise LookupError(f"Environment '{environmentId}' was not found.")
            provider_state = dict(environment.providerState or {})

        resources: list[dict[str, Any]] = []
        resource_group_name = provider_state.get("resourceGroupName")
        variables = (provider_state.get("terraform") or {}).get("variables") or {}
        retained_group = variables.get("existing_resource_group_name") is not None
        if resource_group_name and not retained_group:
            resources.append({"type": "resourceGroup", "name": resource_group_name})
        vm_name = provider_state.get("vmName")
        if vm_name:
            resources.append({"type": "virtualMachine", "name": vm_name})

        return TeardownPreview(
            environmentId=environmentId,
            previewToken=f"teardown-{environmentId}",
            resources=resources,
            consequences=[
                (
                    "Terraform destroy removes only this environment's state-owned resources. "
                    "The retained resource group, other environments and its existing role grants "
                    "are not deleted. This action cannot be undone."
                    if retained_group
                    else "Terraform destroy will remove every resource in this environment's "
                    "resource group, including the GPU VM and any deployed model state. "
                    "This action cannot be undone."
                )
            ],
        )

    def teardownEnvironment(
        self, environmentId: str, previewToken: str
    ) -> TeardownHandle:
        _ = previewToken  # not independently validated; mirrors providers/local/adapter.py
        return self._provisioner.start_teardown(
            environment_id=environmentId,
            operation_id=f"teardown-{environmentId}",
            actor_email="system",
        )

    def _load_profile(self, profile_id: str) -> CloudDeploymentProfile:
        with self._session_factory() as session:
            profile = session.get(CloudDeploymentProfile, profile_id)
            if profile is None:
                raise LookupError(f"Profile '{profile_id}' was not found.")
            return profile
