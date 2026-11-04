from __future__ import annotations

from types import SimpleNamespace

import pytest
from src.providers.azure.preflight import AzureCapacityPreflight


def test_preflight_reports_quota_and_sku_availability() -> None:
    usage = SimpleNamespace(
        name=SimpleNamespace(
            value="standardNCT4Family",
            localized_value="Standard NC T4 Family vCPUs",
        ),
        current_value=2,
        limit=32,
    )
    sku = SimpleNamespace(
        name="Standard_NC16as_T4_v3",
        locations=["eastus2"],
        restrictions=[],
        location_info=[SimpleNamespace(zones=["1", "2"])],
        capabilities=[SimpleNamespace(name="vCPUs", value="16")],
        family="standardNCT4Family",
    )
    compute_client = SimpleNamespace(
        usage=SimpleNamespace(
            list=lambda location: [
                usage,
                SimpleNamespace(name=SimpleNamespace(value="cores"), current_value=0, limit=100),
            ]
        ),
        resource_skus=SimpleNamespace(list=lambda filter=None: [sku]),
    )

    result = AzureCapacityPreflight(
        subscription_id="sub-123",
        compute_client=compute_client,
    ).evaluate_region(region="eastus2", vm_size="Standard_NC16as_T4_v3", priority="Regular")

    assert result.available is True
    assert result.currentUsage == 2
    assert result.limit == 32
    assert result.quota.requestedVcpus == 16
    assert result.sku.zones == ["1", "2"]


def evaluate(
    *,
    usage=0,
    limit=16,
    vcpus="16",
    priority="Spot",
    regional_usage=0,
    regional_limit=100,
    include_regional=True,
    family="standardNCT4Family",
    include_spot=True,
):
    entries = [
        SimpleNamespace(
            name=SimpleNamespace(value="standardNCT4Family"), current_value=usage, limit=limit
        )
    ]
    if include_spot:
        entries.append(
            SimpleNamespace(
                name=SimpleNamespace(value="lowPriorityCores"), current_value=usage, limit=limit
            )
        )
    if include_regional:
        entries.append(
            SimpleNamespace(
                name=SimpleNamespace(value="cores"),
                current_value=regional_usage,
                limit=regional_limit,
            )
        )
    sku = SimpleNamespace(
        name="Standard_NC16as_T4_v3",
        locations=["eastus2"],
        restrictions=[],
        capabilities=[SimpleNamespace(name="vCPUs", value=vcpus)],
        family=family,
    )
    client = SimpleNamespace(
        usage=SimpleNamespace(list=lambda location: entries),
        resource_skus=SimpleNamespace(list=lambda filter=None: [sku]),
    )
    return AzureCapacityPreflight(subscription_id="test", compute_client=client).evaluate_region(
        region="eastus2", vm_size="Standard_NC16as_T4_v3", priority=priority
    )


@pytest.mark.parametrize(
    "usage,limit,available", [(0, 16, True), (1, 16, False), (2, 32, True), (16, 16, False)]
)
def test_spot_quota_requires_entire_requested_sku(usage, limit, available) -> None:
    result = evaluate(usage=usage, limit=limit)
    assert result.available is available
    assert result.quota.requestedVcpus == 16
    assert "lowPriorityCores" in result.quota.quotaName


def test_spot_does_not_substitute_regular_family_quota() -> None:
    assert evaluate(include_spot=False).available is None


@pytest.mark.parametrize("vcpus", [None, "invalid", "16.5", "0", "-1", 16.5, True])
def test_missing_or_invalid_sku_size_cannot_confirm_quota(vcpus) -> None:
    assert evaluate(vcpus=vcpus, limit=100).available is None


def test_regular_requires_total_regional_headroom_too() -> None:
    result = evaluate(priority="Regular", regional_usage=90, regional_limit=100)
    assert result.available is False
    assert any("Total regional" in evidence for evidence in result.quota.evidence)


def test_missing_regional_quota_is_unknown_not_sufficient() -> None:
    assert evaluate(priority="Regular", include_regional=False).available is None


def test_sku_family_metadata_is_authoritative() -> None:
    assert evaluate(priority="Regular", family="standardDifferentFamily").available is None


def test_unknown_priority_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported VM priority"):
        evaluate(priority="Deferred")


def test_integer_sku_capability_is_supported() -> None:
    assert evaluate(vcpus=16).available is True


def test_usage_matching_never_selects_an_unrelated_family() -> None:
    unrelated = SimpleNamespace(name=SimpleNamespace(value="standardUnrelatedFamily"))
    assert AzureCapacityPreflight._match_usage([unrelated], ("t4",)) is None
