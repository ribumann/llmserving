from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.enums import ModelSizeClass, ProviderType
from src.domain.profile import CloudDeploymentProfile
from src.persistence.db import get_db_session
from src.providers.azure.preview import PreviewEvaluation
from src.providers.base import EnvironmentStateView, ProvisioningHandle, RegionRecommendation


class NoopPersistenceSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def add(self, _obj) -> None:
        return None

    def commit(self) -> None:
        return None


class FlowProvider:
    def __init__(self) -> None:
        self.preview_calls: list[tuple[str, str | None]] = []
        self.last_environment_id: str | None = None

    def preview_with_details(self, *, profileId: str, regionOverride: str | None = None):
        self.preview_calls.append((profileId, regionOverride))
        now = datetime(2026, 8, 19, tzinfo=UTC)
        return PreviewEvaluation(
            recommendation=RegionRecommendation(
                recommendedRegion=regionOverride or "eastus2",
                evidence=["quota ok", "sku ok"],
                evaluatedAt=now,
                uncertaintyNote="Capacity is best-effort.",
                regionOverrideValidated=regionOverride is not None,
            ),
            checks=[],
        )

    def bind_provisioning_context(self, **kwargs) -> None:
        self.last_environment_id = kwargs["environment_id"]

    def start_provisioning(self, **kwargs) -> ProvisioningHandle:
        self.last_environment_id = kwargs["environment_id"]
        return ProvisioningHandle(operationId="op-789", phase="accepted", state="provisioning")

    def getEnvironmentState(self, environmentId: str) -> EnvironmentStateView:
        return EnvironmentStateView(
            environmentId=environmentId,
            lifecycleState="ready",
            activeRevisionId=None,
            providerState={"resourceGroupName": "rg-demo"},
            context={"resourceState": "running"},
        )


class FlowSession:
    def __init__(self, profile: CloudDeploymentProfile) -> None:
        self.profile = profile

    def get(self, model, identifier):
        if model is CloudDeploymentProfile and identifier == self.profile.profileId:
            return self.profile
        return None

    def add(self, _obj) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


@pytest.mark.integration
def test_provision_flow_revalidates_override(monkeypatch) -> None:
    app = create_app()
    provider = FlowProvider()
    app.state.provider_adapter = provider
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None
    profile = CloudDeploymentProfile(
        profileId="azure-single-gpu-3b",
        provider=ProviderType.AZURE,
        modelSizeClass=ModelSizeClass.THREE_B,
        eligibleRegions=["eastus2", "westus3"],
        vmSku="Standard_NC16as_T4_v3",
        capacityAssumptions={"gpuCount": 1},
        configurableInputs={
            "profileSizeClass": "small",
            "bootstrapModelRepo": "Qwen/Qwen3-4B",
            "allowedSshSourceCidr": "203.0.113.0/24",
            "allowedApiSourceCidr": "203.0.113.0/24",
        },
        knownLimitations=["Capacity is best-effort."],
        version=1,
    )

    def override_db():
        yield FlowSession(profile)

    app.dependency_overrides[get_db_session] = override_db
    monkeypatch.setattr(
        "src.api.routes.environments.EnvironmentLockService.acquire",
        lambda self, session, environment_id, operation_id: None,
    )
    client = TestClient(app)

    create_response = client.post(
        "/environments",
        headers={"X-Demo-User": "presenter@example.com"},
        json={"profileId": "azure-single-gpu-3b", "region": "westus3"},
    )

    assert create_response.status_code == 202
    assert provider.preview_calls == [("azure-single-gpu-3b", "westus3")]

    environment_id = create_response.json()["environmentId"]
    get_response = client.get(
        f"/environments/{environment_id}",
        headers={"X-Demo-User": "presenter@example.com"},
    )

    assert get_response.status_code == 200
    assert get_response.json()["lifecycleState"] == "ready"
