from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from src.providers.base import (
    DeploymentHandle,
    EnvironmentStateView,
    ProviderAdapter,
    ProvisioningHandle,
    RegionRecommendation,
    TeardownHandle,
    TeardownPreview,
)


class NoOpProviderAdapter:
    def previewEnvironment(
        self, profileId: str, regionOverride: str | None = None
    ) -> RegionRecommendation:
        return RegionRecommendation(
            recommendedRegion=regionOverride or "eastus2",
            evidence=[f"profile={profileId}"],
            evaluatedAt=datetime.now(UTC),
            uncertaintyNote="Capacity remains best-effort until deployment time.",
            regionOverrideValidated=regionOverride is not None,
        )

    def provisionEnvironment(self, profileId: str, region: str) -> ProvisioningHandle:
        return ProvisioningHandle(
            operationId=f"prov-{profileId}-{region}",
            phase="accepted",
            state="provisioning",
        )

    def getEnvironmentState(self, environmentId: str) -> EnvironmentStateView:
        return EnvironmentStateView(
            environmentId=environmentId,
            lifecycleState="ready",
            activeRevisionId=None,
            providerState={"environmentId": environmentId},
            context={"cost": "unknown"},
        )

    def deployRevision(
        self, environmentId: str, modelConfig: dict, inferenceConfig: dict, engineId: str
    ) -> DeploymentHandle:
        return DeploymentHandle(
            operationId=f"deploy-{environmentId}",
            deploymentRevisionId="revision-1",
            phase="accepted",
            state="deploying",
            diagnostics=[engineId, str(bool(modelConfig)), str(bool(inferenceConfig))],
        )

    def teardownPreview(self, environmentId: str) -> TeardownPreview:
        return TeardownPreview(
            environmentId=environmentId,
            previewToken="preview-token",
            resources=[{"type": "vm", "name": "demo-vm"}],
            consequences=["Experiment history is retained separately."],
        )

    def teardownEnvironment(self, environmentId: str, previewToken: str) -> TeardownHandle:
        return TeardownHandle(
            operationId=f"teardown-{environmentId}",
            phase="accepted",
            state="tearing_down",
            resourceOutcomes=[{"resource": previewToken, "status": "removed"}],
        )


def test_noop_provider_adapter_satisfies_contract() -> None:
    adapter = NoOpProviderAdapter()
    assert isinstance(adapter, ProviderAdapter)

    preview = adapter.previewEnvironment("azure-single-gpu-3b")
    assert preview.recommendedRegion == "eastus2"
    assert preview.evidence

    state = adapter.getEnvironmentState("env-123")
    assert asdict(state)["lifecycleState"] == "ready"

    teardown = adapter.teardownEnvironment("env-123", "preview-token")
    assert teardown.state == "tearing_down"
