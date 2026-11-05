from __future__ import annotations

from datetime import UTC, datetime

import pytest
from src.domain.enums import ModelSizeClass, ProviderType
from src.domain.profile import CloudDeploymentProfile
from src.providers.azure.preflight import (
    AzurePreflightAuthorizationError,
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


@pytest.mark.parametrize(
    "defaults,inputs,expected",
    [
        ({}, {}, "Standard_NC16as_T4_v3"),
        ({}, {"profileSizeClass": "medium"}, "Standard_NC24ads_A100_v4"),
        ({"profileSizeClass": "large"}, {}, "Standard_NC80adis_H100_v5"),
        ({"profileSizeClass": "large"}, {"profileSizeClass": "small"}, "Standard_NC16as_T4_v3"),
        ({"vmSizeOverride": "Standard_NC24ads_A100_v4"}, {}, "Standard_NC24ads_A100_v4"),
        (
            {"vmSizeOverride": "Standard_NC24ads_A100_v4"},
            {"vmSizeOverride": "Standard_NC80adis_H100_v5"},
            "Standard_NC80adis_H100_v5",
        ),
        (
            {"vmSizeOverride": "Standard_NC24ads_A100_v4"},
            {"vmSizeOverride": None},
            "Standard_NC16as_T4_v3",
        ),
    ],
)
def test_preflight_checks_effective_requested_sku(defaults, inputs, expected) -> None:
    profile = CloudDeploymentProfile(
        profileId="azure",
        provider=ProviderType.AZURE,
        modelSizeClass=ModelSizeClass.THREE_B,
        eligibleRegions=["eastus2"],
        vmSku="Standard_NC16as_T4_v3",
        capacityAssumptions={},
        configurableInputs=defaults,
        knownLimitations=[],
        version=1,
    )
    result = AzurePreviewService(preflight=FakePreflight()).preview_environment(
        profile=profile, configurable_inputs=inputs
    )
    assert result.checks[0].vmSize == expected


@pytest.mark.parametrize("size", ["", " ", 16, False])
def test_invalid_override_does_not_fall_back_to_another_sku(size) -> None:
    from src.providers.azure.preview import resolve_vm_size

    profile = CloudDeploymentProfile(vmSku="Standard_NC16as_T4_v3", configurableInputs={})
    with pytest.raises(ValueError, match="vmSizeOverride"):
        resolve_vm_size(profile, {"vmSizeOverride": size})


def test_size_class_mapping_matches_existing_terraform() -> None:
    from pathlib import Path

    from src.providers.azure.preview import VM_SIZE_BY_CLASS

    terraform = (Path(__file__).resolve().parents[3] / "infra/demo/main.tf").read_text()
    for size_class, sku in VM_SIZE_BY_CLASS.items():
        assert f'{size_class}  = "{sku}"' in terraform or f'{size_class} = "{sku}"' in terraform


@pytest.mark.parametrize("size_class", ["unknown", None, [], 16])
def test_invalid_size_class_is_explicit(size_class) -> None:
    from src.providers.azure.preview import InvalidVmSizeError, resolve_vm_size

    profile = CloudDeploymentProfile(configurableInputs={})
    with pytest.raises(InvalidVmSizeError, match="profileSizeClass"):
        resolve_vm_size(profile, {"profileSizeClass": size_class})


@pytest.mark.parametrize("override", [None, "westus3"])
def test_authorization_denial_cannot_be_a_fallback_or_override(override) -> None:
    attempted = []

    class DeniedPreflight(FakePreflight):
        def evaluate_region(self, *, region: str, vm_size: str):
            attempted.append(region)
            if region == "westus3":
                raise AzurePreflightAuthorizationError(operation="sku")
            return super().evaluate_region(region=region, vm_size=vm_size)

    profile = CloudDeploymentProfile(
        profileId="azure",
        configurableInputs={},
        eligibleRegions=["southcentralus", "westus3", "westeurope"],
    )
    with pytest.raises(AzurePreflightAuthorizationError):
        AzurePreviewService(preflight=DeniedPreflight()).preview_environment(
            profile=profile, region_override=override
        )
    # Even an earlier successful region cannot turn denied reads into a recommendation.
    assert attempted == (["westus3"] if override else ["southcentralus", "westus3"])
