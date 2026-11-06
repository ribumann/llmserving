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


class FakeProvider:
    def __init__(self) -> None:
        self.bound_contexts = []
        self.preview_inputs = None

    def preview_with_details(
        self, *, profileId: str, regionOverride: str | None = None, configurableInputs=None
    ):
        self.preview_inputs = configurableInputs
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

    def start_provisioning(self, **kwargs) -> ProvisioningHandle:
        self.bound_contexts.append(kwargs)
        return ProvisioningHandle(
            operationId="op-123",
            phase="accepted",
            state="provisioning",
            diagnostics=[],
        )

    def getEnvironmentState(self, environmentId: str) -> EnvironmentStateView:
        return EnvironmentStateView(
            environmentId=environmentId,
            lifecycleState="ready",
            activeRevisionId=None,
            providerState={"resourceGroupName": "rg-demo"},
            context={"resourceState": "running"},
        )


class FakeSession:
    def __init__(self, profile: CloudDeploymentProfile) -> None:
        self.profile = profile
        self.added = []
        self.flushed = False
        self.committed = False

    def get(self, model, identifier):
        if model is CloudDeploymentProfile and identifier == self.profile.profileId:
            return self.profile
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flushed = True

    def commit(self) -> None:
        self.committed = True


@pytest.mark.parametrize(
    "overrides,expected_sku",
    [
        ({}, "Standard_NC16as_T4_v3"),
        ({"vmSizeOverride": None}, "Standard_NC16as_T4_v3"),
        (
            {"vmSizeOverride": "Standard_NC4as_T4_v3", "vmPriority": "Regular"},
            "Standard_NC4as_T4_v3",
        ),
        ({"vmSizeOverride": "Standard_NC24ads_A100_v4"}, "Standard_NC24ads_A100_v4"),
        ({"profileSizeClass": "large"}, "Standard_NC80adis_H100_v5"),
    ],
)
def test_create_environment_returns_accepted_and_binds_context(
    monkeypatch, overrides, expected_sku
) -> None:
    app = create_app()
    app.state.provider_adapter = FakeProvider()
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
    session = FakeSession(profile)

    def override_db():
        yield session

    app.dependency_overrides[get_db_session] = override_db
    monkeypatch.setattr(
        "src.api.routes.environments.EnvironmentLockService.acquire",
        lambda self, session, environment_id, operation_id: None,
    )
    client = TestClient(app)

    response = client.post(
        "/environments",
        headers={"X-Demo-User": "presenter@example.com"},
        json={
            "profileId": "azure-single-gpu-3b",
            "region": "italynorth",
            "configurableInputs": overrides,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["operationId"] == "op-123"
    assert body["region"] == "italynorth"
    assert session.flushed is True
    assert session.committed is True
    assert app.state.provider_adapter.bound_contexts[0]["region"] == "italynorth"
    terraform_variables = app.state.provider_adapter.bound_contexts[0]["terraform_variables"]
    assert terraform_variables["environment_id"]
    assert terraform_variables["admin_ssh_public_key"].startswith("ssh-rsa ")
    assert terraform_variables["vm_size"] == expected_sku
    assert terraform_variables["expected_region"] == "italynorth"
    assert terraform_variables["vm_priority"] == overrides.get("vmPriority", "Spot")
    assert app.state.provider_adapter.preview_inputs == (overrides or None)


def test_get_environment_returns_provider_state() -> None:
    app = create_app()
    app.state.provider_adapter = FakeProvider()
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None
    client = TestClient(app)

    response = client.get(
        "/environments/env-123",
        headers={"X-Demo-User": "presenter@example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["environmentId"] == "env-123"
    assert body["context"]["resourceState"] == "running"
