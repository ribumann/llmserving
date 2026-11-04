from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from src.api.app import create_app
from src.providers.azure.preflight import (
    CapacityPreflightResult,
    QuotaCheckResult,
    SkuAvailabilityResult,
)
from src.providers.azure.preview import PreviewEvaluation
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
    assert body["assessments"][0]["capacityStatus"] == "available"
    assert body["assessments"][0]["compatibilityStatus"] == "compatible"
