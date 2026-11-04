from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import DemoEnvironmentState
from src.domain.environment import DemoEnvironment
from src.domain.inference_configuration import InferenceConfiguration
from src.domain.model_configuration import ModelConfiguration
from src.providers.base import EnvironmentStateView


class AzureEnvironmentStateService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        compute_client: ComputeManagementClient | None = None,
        credential: Any | None = None,
        terraform_binary: str = "terraform",
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._compute_client = compute_client
        self._credential = credential
        self._terraform_binary = terraform_binary

    @property
    def compute_client(self) -> ComputeManagementClient:
        if self._compute_client is None:
            credential = self._credential or DefaultAzureCredential()
            self._compute_client = ComputeManagementClient(
                credential, self._settings.azure_subscription_id or ""
            )
        return self._compute_client

    def getEnvironmentState(self, environmentId: str) -> EnvironmentStateView:
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environmentId)
            if environment is None:
                raise LookupError(f"Environment '{environmentId}' was not found.")

            provider_state = dict(environment.providerState or {})
            vm_status = self._resolve_vm_status(provider_state)
            outputs = self._resolve_outputs(provider_state)
            provider_state.update(outputs)

            lifecycle_state = environment.lifecycleState.value
            if (
                vm_status == "not_found"
                and environment.lifecycleState == DemoEnvironmentState.READY
            ):
                lifecycle_state = DemoEnvironmentState.NOT_PROVISIONED.value

            context = {
                "provider": "azure",
                "profileId": environment.profileId,
                "region": environment.region,
                "resourceState": vm_status,
                "resourceGroupName": provider_state.get("resourceGroupName"),
                "vmName": provider_state.get("vmName"),
                "vmSize": provider_state.get("vmSize"),
                "publicIpAddress": provider_state.get("publicIpAddress"),
                "inferenceApiUrl": provider_state.get("inferenceApiUrl"),
                "privateIpAddress": provider_state.get("privateIpAddress"),
                "vllmEndpoint": provider_state.get("vllmEndpoint"),
                "capacityContext": environment.regionRecommendation or {},
                "operation": provider_state.get("currentOperation"),
                "activeDeploymentConfiguration": self._resolve_active_configuration(
                    session, environment.activeDeploymentRevisionId
                ),
            }

            return EnvironmentStateView(
                environmentId=environment.environmentId,
                lifecycleState=lifecycle_state,
                activeRevisionId=environment.activeDeploymentRevisionId,
                providerState=provider_state,
                context=context,
            )

    def _resolve_active_configuration(
        self, session: Session, active_revision_id: str | None
    ) -> dict[str, Any] | None:
        """Resolve the active deployment's model/engine/settings so operators
        viewing an environment can see what is actually deployed instead of
        just a lifecycle state and a raw revision id."""
        if not active_revision_id:
            return None

        revision = session.get(DeploymentRevision, active_revision_id)
        if revision is None:
            return None

        model_configuration = session.get(ModelConfiguration, revision.modelConfigId)
        inference_configuration = session.get(
            InferenceConfiguration, revision.inferenceConfigId
        )
        return {
            "deploymentRevisionId": revision.deploymentRevisionId,
            "lifecycleState": revision.lifecycleState.value,
            "engineId": revision.engineId,
            "catalogEntryId": getattr(model_configuration, "catalogEntryId", None),
            "resolvedCheckpointRef": getattr(
                model_configuration, "resolvedCheckpointRef", None
            ),
            "modelSettings": dict(getattr(model_configuration, "modelSettings", {}) or {}),
            "servingSettings": dict(
                getattr(inference_configuration, "servingSettings", {}) or {}
            ),
            "generationSettings": dict(
                getattr(inference_configuration, "generationSettings", {}) or {}
            ),
        }

    def _resolve_vm_status(self, provider_state: dict[str, Any]) -> str:
        resource_group_name = provider_state.get("resourceGroupName")
        vm_name = provider_state.get("vmName")
        if not resource_group_name or not vm_name or not self._settings.azure_subscription_id:
            return "unknown"

        try:
            instance_view = self.compute_client.virtual_machines.instance_view(
                resource_group_name, vm_name
            )
        except Exception:
            return "not_found"

        statuses = list(getattr(instance_view, "statuses", []) or [])
        for status in statuses:
            code = str(getattr(status, "code", "")).lower()
            if code.endswith("/running"):
                return "running"
            if code.endswith("/stopped"):
                return "stopped"
            if code.endswith("/deallocated"):
                return "deallocated"
        return "unknown"

    def _resolve_outputs(self, provider_state: dict[str, Any]) -> dict[str, Any]:
        terraform = provider_state.get("terraform") or {}
        working_directory = terraform.get("workingDirectory")
        if not working_directory:
            return {}

        cwd = Path(working_directory)
        if not cwd.exists():
            return {}

        result = subprocess.run(
            [self._terraform_binary, "output", "-json"],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}

        parsed = json.loads(result.stdout)
        return {
            key: value["value"] if isinstance(value, dict) and "value" in value else value
            for key, value in parsed.items()
        }
