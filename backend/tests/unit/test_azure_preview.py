from __future__ import annotations

from datetime import UTC, datetime

from src.domain.enums import ModelSizeClass, ProviderType
from src.domain.profile import CloudDeploymentProfile
from src.providers.azure.preflight import (
    CapacityPreflightResult,
    QuotaCheckResult,
    SkuAvailabilityResult,
)
from src.providers.azure.preview import AzurePreviewService


class FakePreflight:
    def evaluate_region(self, *, region: str, vm_size: str):
        checked_at = datetime(2026, 8, 19, tzinfo=UTC)
        available = region == "southcentralus"
        return CapacityPreflightResult(
            region=region,
            vmSize=vm_size,
            available=available,
            currentUsage=0 if available else 16,
            limit=16,
            checkedAt=checked_at,
            quota=QuotaCheckResult(
                region=region,
                vmSize=vm_size,
                quotaName="quota",
                currentUsage=0 if available else 16,
                limit=16,
                available=available,
                checkedAt=checked_at,
                evidence=["quota"],
            ),
            sku=SkuAvailabilityResult(
                region=region,
                vmSize=vm_size,
                available=available,
                checkedAt=checked_at,
                evidence=["sku"],
            ),
            evidence=[f"{region}:{available}"],
            uncertaintyReasons=[],
        )


def test_preview_picks_first_available_fallback_region() -> None:
    profile = CloudDeploymentProfile(
        profileId="azure-single-gpu-3b",
        provider=ProviderType.AZURE,
        modelSizeClass=ModelSizeClass.THREE_B,
        eligibleRegions=["eastus2", "southcentralus", "westus3"],
        vmSku="Standard_NC16as_T4_v3",
        capacityAssumptions={},
        configurableInputs={},
        knownLimitations=[],
        version=1,
    )

    evaluation = AzurePreviewService(preflight=FakePreflight()).preview_environment(profile=profile)

    assert evaluation.recommendation.recommendedRegion == "southcentralus"
    assert evaluation.checks[1].available is True
