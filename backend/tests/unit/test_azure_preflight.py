from __future__ import annotations

from types import SimpleNamespace

from src.providers.azure.preflight import AzureCapacityPreflight


def test_preflight_reports_quota_and_sku_availability() -> None:
    usage = SimpleNamespace(
        name=SimpleNamespace(
            value="standardNCT4Family",
            localized_value="Standard NC T4 Family vCPUs",
        ),
        current_value=2,
        limit=16,
    )
    sku = SimpleNamespace(
        name="Standard_NC16as_T4_v3",
        locations=["eastus2"],
        restrictions=[],
        location_info=[SimpleNamespace(zones=["1", "2"])],
    )
    compute_client = SimpleNamespace(
        usage=SimpleNamespace(list=lambda location: [usage]),
        resource_skus=SimpleNamespace(list=lambda filter=None: [sku]),
    )

    result = AzureCapacityPreflight(
        subscription_id="sub-123",
        compute_client=compute_client,
    ).evaluate_region(region="eastus2", vm_size="Standard_NC16as_T4_v3")

    assert result.available is True
    assert result.currentUsage == 2
    assert result.limit == 16
    assert result.sku.zones == ["1", "2"]
