from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from src.api.app import create_app
from src.api.routes import environments
from src.domain.profile import CloudDeploymentProfile
from src.persistence.db import get_db_session
from src.providers.azure.preflight import (
    AzureCapacityPreflight,
    CapacityPreflightResult,
    QuotaCheckResult,
    SkuAvailabilityResult,
)
from src.providers.azure.preview import AzurePreviewService, PreviewEvaluation
from src.providers.base import RegionRecommendation


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
    def preview_with_details(self, *, profileId: str, regionOverride: str | None = None):
        checked_at = datetime(2026, 8, 19, tzinfo=UTC)
        return PreviewEvaluation(
            recommendation=RegionRecommendation(
                recommendedRegion=regionOverride or "eastus2",
                evidence=[f"profile={profileId}"],
                evaluatedAt=checked_at,
                uncertaintyNote="Capacity is best-effort.",
                regionOverrideValidated=regionOverride is not None,
            ),
            checks=[
                CapacityPreflightResult(
                    region=regionOverride or "eastus2",
                    vmSize="Standard_NC16as_T4_v3",
                    available=True,
                    currentUsage=0,
                    limit=16,
                    checkedAt=checked_at,
                    quota=QuotaCheckResult(
                        region="eastus2",
                        vmSize="Standard_NC16as_T4_v3",
                        quotaName="Standard NC Family vCPUs",
                        currentUsage=0,
                        limit=16,
                        available=True,
                        checkedAt=checked_at,
                        evidence=["quota ok"],
                    ),
                    sku=SkuAvailabilityResult(
                        region="eastus2",
                        vmSize="Standard_NC16as_T4_v3",
                        available=True,
                        checkedAt=checked_at,
                        evidence=["sku ok"],
                    ),
                    evidence=["quota ok", "sku ok"],
                    uncertaintyReasons=[],
                )
            ],
        )


def test_preview_environment_returns_contract_shape() -> None:
    app = create_app()
    app.state.provider_adapter = FakeProvider()
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None
    client = TestClient(app)

    response = client.post(
        "/environments/preview",
        headers={"X-Demo-User": "presenter@example.com"},
        json={"profileId": "azure-single-gpu-3b"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["profileId"] == "azure-single-gpu-3b"
    assert body["recommendedRegion"] == "eastus2"
    assert body["assessments"][0]["region"] == "eastus2"
    assert body["assessments"][0]["quotaStatus"] == "sufficient"
    assert body["assessments"][0]["capacityStatus"] == "unknown"
    assert body["assessments"][0]["compatibilityStatus"] == "compatible"


@pytest.mark.parametrize("route", ["/environments/preview", "/environments"])
@pytest.mark.parametrize("explicit_region", [False, True])
@pytest.mark.parametrize("operation", ["sku", "quota"])
@pytest.mark.parametrize("kind", [401, 403, "authentication"])
def test_denied_preflight_blocks_preview_and_creation_without_side_effects(
    route, explicit_region, operation, kind, monkeypatch, caplog
) -> None:
    private = "PRIVATE SDK credential and tenant detail"
    if kind == "authentication":
        error = ClientAuthenticationError(message=private)
    else:
        error = HttpResponseError(message=private)
        error.status_code = kind
    usage_reader = Mock(return_value=[])
    sku_reader = Mock(
        return_value=[
            SimpleNamespace(
                name="Standard_NC16as_T4_v3",
                locations=["eastus2"],
                restrictions=[],
                capabilities=[SimpleNamespace(name="vCPUs", value="16")],
                family="standardNCT4Family",
            )
        ]
    )
    (sku_reader if operation == "sku" else usage_reader).side_effect = error
    preflight = AzureCapacityPreflight(
        subscription_id="test",
        compute_client=SimpleNamespace(
            usage=SimpleNamespace(list=usage_reader),
            resource_skus=SimpleNamespace(list=sku_reader),
        ),
    )
    preview = AzurePreviewService(preflight=preflight)
    profile = CloudDeploymentProfile(
        profileId="azure", configurableInputs={}, eligibleRegions=["eastus2", "westus3"]
    )

    class DeniedProvider:
        start_provisioning = Mock()

        def preview_with_details(self, *, profileId, regionOverride=None):
            return preview.preview_environment(profile=profile, region_override=regionOverride)

    provider = DeniedProvider()
    route_session = Mock(spec=Session)
    keygen = Mock()
    monkeypatch.setattr(environments, "_generate_admin_ssh_keypair", keygen)
    app = create_app()
    app.state.provider_adapter = provider
    app.state.session_factory = lambda: NoopPersistenceSession()
    app.state.telemetry = None
    app.dependency_overrides[get_db_session] = lambda: route_session
    payload = {"profileId": "azure"}
    if explicit_region:
        payload["regionOverride" if route.endswith("/preview") else "region"] = "eastus2"
    response = TestClient(app).post(
        route, headers={"X-Demo-User": "presenter@example.com"}, json=payload
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "azure_preflight_authorization_failed"
    assert response.json()["error"]["details"] == {"operation": operation}
    assert response.json()["requestId"]
    assert private not in response.text
    assert private not in caplog.text
    for method in ("get", "add", "flush", "commit"):
        getattr(route_session, method).assert_not_called()
    provider.start_provisioning.assert_not_called()
    keygen.assert_not_called()
    sku_reader.assert_called_once()
    assert usage_reader.call_count == (0 if operation == "sku" else 1)
