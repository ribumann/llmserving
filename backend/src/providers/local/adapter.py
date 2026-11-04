from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session, sessionmaker
from src.config import Settings
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DemoEnvironmentState, DeploymentRevisionState, ProviderType
from src.domain.environment import DemoEnvironment
from src.domain.environment_lock import EnvironmentLockService
from src.domain.profile import CloudDeploymentProfile
from src.engines.ollama.adapter import OllamaEngineAdapter
from src.providers.azure.preflight import (
    CapacityPreflightResult,
    QuotaCheckResult,
    SkuAvailabilityResult,
)
from src.providers.azure.preview import PreviewEvaluation
from src.providers.base import (
    DeploymentHandle,
    EnvironmentStateView,
    ProviderAdapter,
    ProvisioningHandle,
    RegionRecommendation,
    TeardownHandle,
    TeardownPreview,
)
from src.providers.local.errors import (
    checkpoint_pull_failed_message,
    ollama_unreachable_message,
)

LOCAL_REGION = "local"
LOCAL_VM_SKU = "local-machine"


class LocalProviderAdapter(ProviderAdapter):
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        telemetry: Any | None = None,
        http_client: httpx.Client | None = None,
        engine_adapter: OllamaEngineAdapter | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._telemetry = telemetry
        self._http_client = http_client or httpx.Client(timeout=30.0)
        self._engine_adapter = engine_adapter or OllamaEngineAdapter(
            settings=settings,
            http_client=self._http_client,
            session_factory=session_factory,
        )
        self._environment_lock_service = EnvironmentLockService()

    def previewEnvironment(
        self, profileId: str, regionOverride: str | None = None
    ) -> RegionRecommendation:
        return self.preview_with_details(
            profileId=profileId, regionOverride=regionOverride
        ).recommendation

    def preview_with_details(
        self,
        *,
        profileId: str,
        regionOverride: str | None = None,
        configurableInputs: Mapping[str, object] | None = None,
    ) -> PreviewEvaluation:
        profile = self._load_profile(profileId)
        region = regionOverride or LOCAL_REGION
        checked_at = datetime.now(UTC)
        evidence = [
            f"Profile {profile.profileId} targets the local Ollama runtime.",
            "Local provisioning skips Azure quota and regional capacity checks.",
        ]
        check = CapacityPreflightResult(
            region=region,
            vmSize=LOCAL_VM_SKU,
            available=True,
            currentUsage=None,
            limit=None,
            checkedAt=checked_at,
            quota=QuotaCheckResult(
                region=region,
                vmSize=LOCAL_VM_SKU,
                quotaName=None,
                currentUsage=None,
                limit=None,
                available=True,
                checkedAt=checked_at,
                evidence=["Local runtime does not depend on Azure quota."],
            ),
            sku=SkuAvailabilityResult(
                region=region,
                vmSize=LOCAL_VM_SKU,
                available=True,
                checkedAt=checked_at,
                evidence=["Local runtime uses presenter-managed CPU/GPU capacity."],
            ),
            evidence=evidence,
            uncertaintyReasons=[],
        )
        return PreviewEvaluation(
            recommendation=RegionRecommendation(
                recommendedRegion=region,
                evidence=evidence,
                evaluatedAt=checked_at,
                uncertaintyNote=(
                    "This path uses local hardware only. Ensure Ollama is installed and running "
                    "before provisioning."
                ),
                regionOverrideValidated=regionOverride is not None,
            ),
            checks=[check],
        )

    def provisionEnvironment(self, profileId: str, region: str) -> ProvisioningHandle:
        _ = region
        message = self._probe_runtime()
        return ProvisioningHandle(
            operationId=f"prov-{profileId}",
            phase="accepted" if message is None else "failed",
            state=(
                DemoEnvironmentState.PROVISIONING.value
                if message is None
                else DemoEnvironmentState.PROVISIONING_FAILED.value
            ),
            diagnostics=[] if message is None else [message],
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
        _ = (profile, region, terraform_variables)
        message = self._probe_runtime()
        if message is None:
            self._mark_environment_ready(
                environment_id=environment_id,
                operation_id=operation_id,
                actor_email=actor_email,
            )
            return ProvisioningHandle(
                operationId=operation_id,
                phase="accepted",
                state=DemoEnvironmentState.PROVISIONING.value,
                diagnostics=[],
            )

        self._mark_environment_failed(
            environment_id=environment_id,
            operation_id=operation_id,
            actor_email=actor_email,
            diagnostics=[message],
        )
        return ProvisioningHandle(
            operationId=operation_id,
            phase="failed",
            state=DemoEnvironmentState.PROVISIONING_FAILED.value,
            diagnostics=[message],
        )

    def getEnvironmentState(self, environmentId: str) -> EnvironmentStateView:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environmentId)
            if environment is None:
                raise LookupError(f"Environment '{environmentId}' was not found.")

            provider_state = dict(environment.providerState or {})
            diagnostics = list(
                dict(provider_state.get("currentOperation") or {}).get("diagnostics") or []
            )
            runtime_message = self._probe_runtime()
            if runtime_message is None and environment.lifecycleState in {
                DemoEnvironmentState.PROVISIONING,
                DemoEnvironmentState.PROVISIONING_FAILED,
            }:
                environment.lifecycleState = DemoEnvironmentState.READY
                environment.activeOperationId = None
                provider_state = self._provider_state(
                    base_state=provider_state,
                    phase="completed",
                    state=DemoEnvironmentState.READY.value,
                    operation_id=str(
                        dict(provider_state.get("currentOperation") or {}).get("operationId")
                        or f"prov-{environmentId}"
                    ),
                    diagnostics=[],
                )
                environment.providerState = provider_state
                session.add(environment)
                session.commit()
            elif runtime_message is not None:
                diagnostics = [runtime_message]

            provider_state = dict(environment.providerState or {})
            context = {
                "provider": "local",
                "profileId": environment.profileId,
                "region": environment.region,
                "baseUrl": self._settings.ollama_base_url,
                "runtime": "ollama",
                "runtimeReachable": runtime_message is None,
                "diagnostics": diagnostics,
                "operation": provider_state.get("currentOperation"),
            }
            return EnvironmentStateView(
                environmentId=environment.environmentId,
                lifecycleState=environment.lifecycleState.value,
                activeRevisionId=environment.activeDeploymentRevisionId,
                providerState=provider_state,
                context=context,
            )

    def deployRevision(
        self,
        environmentId: str,
        modelConfig: Mapping[str, Any],
        inferenceConfig: Mapping[str, Any],
        engineId: str,
    ) -> DeploymentHandle:
        return self.start_deployment(
            environment_id=environmentId,
            deployment_revision_id=str(modelConfig.get("deploymentRevisionId") or "pending"),
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
        hugging_face_token=None,
    ) -> DeploymentHandle:
        _ = (inference_config, target_environment, hugging_face_token)
        if engine_id != "ollama":
            raise LookupError(f"Engine '{engine_id}' is not supported.")

        checkpoint = str(model_config.get("resolvedCheckpointRef") or "").strip()
        if not checkpoint:
            raise RuntimeError("A resolved Ollama model tag is required for local deployment.")

        runtime_message = self._probe_runtime()
        if runtime_message is not None:
            self._mark_revision_failed(
                environment_id=environment_id,
                deployment_revision_id=deployment_revision_id,
                operation_id=operation_id,
                actor_email=actor_email,
                diagnostics=[runtime_message],
            )
            return DeploymentHandle(
                operationId=operation_id,
                deploymentRevisionId=deployment_revision_id,
                phase="failed",
                state=DeploymentRevisionState.DEPLOYMENT_FAILED.value,
                diagnostics=[runtime_message],
            )

        self._mark_revision_deploying(
            environment_id=environment_id,
            deployment_revision_id=deployment_revision_id,
            operation_id=operation_id,
            actor_email=actor_email,
        )

        if checkpoint not in self._list_model_tags():
            try:
                response = self._http_client.post(
                    f"{self._settings.ollama_base_url.rstrip('/')}/api/pull",
                    json={"model": checkpoint, "stream": False},
                )
                response.raise_for_status()
                body = response.json()
                if body.get("error"):
                    raise RuntimeError(str(body["error"]))
            except Exception as exc:
                message = checkpoint_pull_failed_message(checkpoint, str(exc))
                self._mark_revision_failed(
                    environment_id=environment_id,
                    deployment_revision_id=deployment_revision_id,
                    operation_id=operation_id,
                    actor_email=actor_email,
                    diagnostics=[message],
                )
                return DeploymentHandle(
                    operationId=operation_id,
                    deploymentRevisionId=deployment_revision_id,
                    phase="failed",
                    state=DeploymentRevisionState.DEPLOYMENT_FAILED.value,
                    diagnostics=[message],
                )

        self._mark_revision_ready(
            environment_id=environment_id,
            deployment_revision_id=deployment_revision_id,
            operation_id=operation_id,
            actor_email=actor_email,
            checkpoint=checkpoint,
        )
        return DeploymentHandle(
            operationId=operation_id,
            deploymentRevisionId=deployment_revision_id,
            phase="accepted",
            state=DeploymentRevisionState.DEPLOYING.value,
            diagnostics=[],
        )

    def get_engine_adapter(self, engine_id: str) -> OllamaEngineAdapter:
        if engine_id != "ollama":
            raise LookupError(f"Engine '{engine_id}' is not supported.")
        return self._engine_adapter

    def teardownPreview(self, environmentId: str) -> TeardownPreview:
        return TeardownPreview(
            environmentId=environmentId,
            previewToken=f"local-preview-{environmentId}",
            resources=[],
            consequences=[
                "No cloud resources are used locally; teardown only marks the local "
                "environment as removed."
            ],
        )

    def teardownEnvironment(self, environmentId: str, previewToken: str) -> TeardownHandle:
        _ = previewToken
        operation_id = f"teardown-{environmentId}"
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environmentId)
            if environment is None:
                raise LookupError(f"Environment '{environmentId}' was not found.")
            environment.lifecycleState = DemoEnvironmentState.TORN_DOWN
            environment.activeOperationId = None
            environment.providerState = self._provider_state(
                base_state=dict(environment.providerState or {}),
                phase="completed",
                state=DemoEnvironmentState.TORN_DOWN.value,
                operation_id=operation_id,
                diagnostics=["Local teardown completed. No cloud resources were in use."],
            )
            session.add(environment)
            session.commit()
        return TeardownHandle(
            operationId=operation_id,
            phase="completed",
            state=DemoEnvironmentState.TORN_DOWN.value,
            diagnostics=["Local teardown completed. No cloud resources were in use."],
        )

    def _load_profile(self, profile_id: str) -> CloudDeploymentProfile:
        with self._session_factory() as session:
            profile = session.get(CloudDeploymentProfile, profile_id)
            if profile is None:
                raise LookupError(f"Profile '{profile_id}' was not found.")
            return profile

    def _probe_runtime(self) -> str | None:
        base_url = self._settings.ollama_base_url.rstrip("/")
        try:
            response = self._http_client.get(base_url)
            response.raise_for_status()
        except httpx.HTTPError:
            return ollama_unreachable_message(base_url)
        return None

    def _list_model_tags(self) -> set[str]:
        response = self._http_client.get(f"{self._settings.ollama_base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
        payload = response.json()
        return {str(model.get("name") or "") for model in payload.get("models") or []}

    def _provider_state(
        self,
        *,
        base_state: dict[str, Any],
        phase: str,
        state: str,
        operation_id: str,
        diagnostics: list[str],
    ) -> dict[str, Any]:
        return {
            **base_state,
            "runtime": "ollama",
            "baseUrl": self._settings.ollama_base_url.rstrip("/"),
            "inferenceApiUrl": self._settings.ollama_base_url.rstrip("/"),
            "resources": [
                {
                    "name": "Ollama runtime",
                    "type": "local-runtime",
                    "state": "ready" if state == DemoEnvironmentState.READY.value else state,
                    "summary": f"Ollama at {self._settings.ollama_base_url.rstrip('/')}",
                }
            ],
            "currentOperation": {
                "operationId": operation_id,
                "phase": phase,
                "state": state,
                "updatedAt": datetime.now(UTC).isoformat(),
                "diagnostics": diagnostics,
            },
        }

    def _mark_environment_ready(
        self, *, environment_id: str, operation_id: str, actor_email: str
    ) -> None:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environment_id)
            if environment is None:
                raise LookupError(f"Environment '{environment_id}' was not found.")
            environment.provider = ProviderType.LOCAL
            environment.lifecycleState = DemoEnvironmentState.READY
            environment.activeOperationId = None
            environment.lastModifiedBy = actor_email
            environment.providerState = self._provider_state(
                base_state=dict(environment.providerState or {}),
                phase="completed",
                state=DemoEnvironmentState.READY.value,
                operation_id=operation_id,
                diagnostics=[],
            )
            session.add(environment)
            try:
                self._environment_lock_service.release(
                    session,
                    environment_id=environment_id,
                    operation_id=operation_id,
                )
            except Exception:
                environment.activeOperationId = None
            session.commit()

    def _mark_environment_failed(
        self,
        *,
        environment_id: str,
        operation_id: str,
        actor_email: str,
        diagnostics: list[str],
    ) -> None:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environment_id)
            if environment is None:
                raise LookupError(f"Environment '{environment_id}' was not found.")
            environment.provider = ProviderType.LOCAL
            environment.lifecycleState = DemoEnvironmentState.PROVISIONING_FAILED
            environment.activeOperationId = None
            environment.lastModifiedBy = actor_email
            environment.providerState = self._provider_state(
                base_state=dict(environment.providerState or {}),
                phase="failed",
                state=DemoEnvironmentState.PROVISIONING_FAILED.value,
                operation_id=operation_id,
                diagnostics=diagnostics,
            )
            session.add(environment)
            session.commit()

    def _mark_revision_deploying(
        self,
        *,
        environment_id: str,
        deployment_revision_id: str,
        operation_id: str,
        actor_email: str,
    ) -> None:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environment_id)
            revision = session.get(DeploymentRevision, deployment_revision_id)
            if environment is None or revision is None:
                raise LookupError("The deployment revision or environment was not found.")
            environment.provider = ProviderType.LOCAL
            revision.lifecycleState = DeploymentRevisionState.DEPLOYING
            revision.health = {"status": "unknown", "diagnostics": []}
            environment.providerState = self._provider_state(
                base_state=dict(environment.providerState or {}),
                phase="deploying",
                state=DeploymentRevisionState.DEPLOYING.value,
                operation_id=operation_id,
                diagnostics=[],
            )
            environment.lastModifiedBy = actor_email
            session.add(revision)
            session.add(environment)
            session.commit()

    def _mark_revision_ready(
        self,
        *,
        environment_id: str,
        deployment_revision_id: str,
        operation_id: str,
        actor_email: str,
        checkpoint: str,
    ) -> None:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environment_id)
            revision = session.get(DeploymentRevision, deployment_revision_id)
            if environment is None or revision is None:
                raise LookupError("The deployment revision or environment was not found.")
            environment.provider = ProviderType.LOCAL
            revision.lifecycleState = DeploymentRevisionState.READY
            revision.activePeriod = {"startedAt": datetime.now(UTC).isoformat(), "endedAt": None}
            revision.health = {
                "status": "healthy",
                "diagnostics": [],
                "runtime": "ollama",
                "modelTag": checkpoint,
            }
            environment.activeDeploymentRevisionId = deployment_revision_id
            environment.activeOperationId = None
            environment.lastModifiedBy = actor_email
            environment.providerState = self._provider_state(
                base_state=dict(environment.providerState or {}),
                phase="completed",
                state=DeploymentRevisionState.READY.value,
                operation_id=operation_id,
                diagnostics=[],
            )
            session.add(revision)
            session.add(environment)
            try:
                self._environment_lock_service.release(
                    session,
                    environment_id=environment_id,
                    operation_id=operation_id,
                )
            except Exception:
                environment.activeOperationId = None
            session.commit()

    def _mark_revision_failed(
        self,
        *,
        environment_id: str,
        deployment_revision_id: str,
        operation_id: str,
        actor_email: str,
        diagnostics: list[str],
    ) -> None:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environment_id)
            revision = session.get(DeploymentRevision, deployment_revision_id)
            if environment is None or revision is None:
                raise LookupError("The deployment revision or environment was not found.")
            environment.provider = ProviderType.LOCAL
            revision.lifecycleState = DeploymentRevisionState.DEPLOYMENT_FAILED
            revision.activePeriod = {
                "startedAt": None,
                "endedAt": datetime.now(UTC).isoformat(),
            }
            revision.health = {"status": "unhealthy", "diagnostics": diagnostics}
            environment.activeOperationId = None
            environment.lastModifiedBy = actor_email
            environment.providerState = self._provider_state(
                base_state=dict(environment.providerState or {}),
                phase="failed",
                state=DeploymentRevisionState.DEPLOYMENT_FAILED.value,
                operation_id=operation_id,
                diagnostics=diagnostics,
            )
            session.add(revision)
            session.add(environment)
            session.commit()
