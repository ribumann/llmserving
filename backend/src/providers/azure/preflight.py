from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient


@dataclass(slots=True, frozen=True)
class QuotaCheckResult:
    region: str
    vmSize: str
    quotaName: str | None
    currentUsage: int | None
    limit: int | None
    available: bool | None
    checkedAt: datetime
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SkuAvailabilityResult:
    region: str
    vmSize: str
    available: bool | None
    checkedAt: datetime
    restrictions: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class CapacityPreflightResult:
    region: str
    vmSize: str
    available: bool | None
    currentUsage: int | None
    limit: int | None
    checkedAt: datetime
    quota: QuotaCheckResult
    sku: SkuAvailabilityResult
    evidence: list[str] = field(default_factory=list)
    uncertaintyReasons: list[str] = field(default_factory=list)


SKU_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "standard_nc16as_t4_v3": ("t4", "ncast4", "nct4", "ncas t4 v3"),
    "standard_nc24ads_a100_v4": ("a100", "nca100", "ncadsa100", "a100 v4"),
    "standard_nc80adis_h100_v5": ("h100", "nch100", "ncadish100", "h100 v5"),
}


class AzureCapacityPreflight:
    def __init__(
        self,
        *,
        subscription_id: str,
        credential: Any | None = None,
        compute_client: ComputeManagementClient | None = None,
    ) -> None:
        self._subscription_id = subscription_id
        self._credential = credential
        self._compute_client = compute_client

    @property
    def compute_client(self) -> ComputeManagementClient:
        if self._compute_client is None:
            credential = self._credential or DefaultAzureCredential()
            self._compute_client = ComputeManagementClient(credential, self._subscription_id)
        return self._compute_client

    def evaluate_region(self, *, region: str, vm_size: str) -> CapacityPreflightResult:
        checked_at = datetime.now(UTC)
        quota = self._check_quota(region=region, vm_size=vm_size, checked_at=checked_at)
        sku = self._check_sku(region=region, vm_size=vm_size, checked_at=checked_at)

        evidence = [*quota.evidence, *sku.evidence]
        uncertainty_reasons: list[str] = []
        available: bool | None

        if quota.available is False:
            available = False
        elif sku.available is False:
            available = False
        elif quota.available is True and sku.available is True:
            available = True
            uncertainty_reasons.append(
                "Azure quota and SKU checks passed, but physical GPU capacity "
                "is only confirmed by a deployment attempt."
            )
        else:
            available = None
            if quota.available is None:
                uncertainty_reasons.append(
                    "Quota could not be confirmed from the Azure usages API."
                )
            if sku.available is None:
                uncertainty_reasons.append(
                    "SKU availability could not be confirmed from the Azure resource-SKUs API."
                )

        return CapacityPreflightResult(
            region=region,
            vmSize=vm_size,
            available=available,
            currentUsage=quota.currentUsage,
            limit=quota.limit,
            checkedAt=checked_at,
            quota=quota,
            sku=sku,
            evidence=evidence,
            uncertaintyReasons=uncertainty_reasons,
        )

    def _check_quota(self, *, region: str, vm_size: str, checked_at: datetime) -> QuotaCheckResult:
        usage_hint_tokens = SKU_FAMILY_HINTS.get(vm_size.lower(), ())
        try:
            usage_entries = list(self.compute_client.usage.list(location=region))
        except Exception as exc:  # pragma: no cover - exercised via tests with mocks
            return QuotaCheckResult(
                region=region,
                vmSize=vm_size,
                quotaName=None,
                currentUsage=None,
                limit=None,
                available=None,
                checkedAt=checked_at,
                evidence=[f"Quota lookup failed for {region}: {exc}"],
            )

        usage_match = self._match_usage(usage_entries, usage_hint_tokens)
        if usage_match is None:
            return QuotaCheckResult(
                region=region,
                vmSize=vm_size,
                quotaName=None,
                currentUsage=None,
                limit=None,
                available=None,
                checkedAt=checked_at,
                evidence=[
                    f"No matching GPU-family usage record was returned for {vm_size} in {region}."
                ],
            )

        current_value = getattr(usage_match, "current_value", None)
        limit = getattr(usage_match, "limit", None)
        available = None if current_value is None or limit is None else current_value < limit
        usage_name = self._usage_name(usage_match)

        return QuotaCheckResult(
            region=region,
            vmSize=vm_size,
            quotaName=usage_name,
            currentUsage=current_value,
            limit=limit,
            available=available,
            checkedAt=checked_at,
            evidence=[
                f"Quota {usage_name or 'unknown'} in {region}: current={current_value}, "
                f"limit={limit}."
            ],
        )

    def _check_sku(
        self, *, region: str, vm_size: str, checked_at: datetime
    ) -> SkuAvailabilityResult:
        try:
            sku_entries = list(
                self.compute_client.resource_skus.list(filter=f"location eq '{region}'")
            )
        except Exception as exc:  # pragma: no cover - exercised via tests with mocks
            return SkuAvailabilityResult(
                region=region,
                vmSize=vm_size,
                available=None,
                checkedAt=checked_at,
                evidence=[f"SKU lookup failed for {region}: {exc}"],
            )

        sku_entry = next(
            (
                entry
                for entry in sku_entries
                if str(getattr(entry, "name", "")).lower() == vm_size.lower()
                and region.lower()
                in {location.lower() for location in getattr(entry, "locations", [])}
            ),
            None,
        )
        if sku_entry is None:
            return SkuAvailabilityResult(
                region=region,
                vmSize=vm_size,
                available=False,
                checkedAt=checked_at,
                evidence=[f"{vm_size} is not listed in Azure resource SKUs for {region}."],
            )

        restrictions = self._restriction_messages(getattr(sku_entry, "restrictions", []) or [])
        zones = list(getattr(sku_entry, "location_info", []) or [])
        normalized_zones = [
            zone
            for location_info in zones
            for zone in list(getattr(location_info, "zones", []) or [])
        ]

        available = False if restrictions else True
        evidence = [f"{vm_size} is listed for {region}."] if available else []
        if restrictions:
            evidence.append(f"{vm_size} is restricted in {region}: {'; '.join(restrictions)}")

        return SkuAvailabilityResult(
            region=region,
            vmSize=vm_size,
            available=available,
            checkedAt=checked_at,
            restrictions=restrictions,
            zones=normalized_zones,
            evidence=evidence,
        )

    @staticmethod
    def _match_usage(usage_entries: Iterable[Any], hint_tokens: tuple[str, ...]) -> Any | None:
        lowered_hints = tuple(token.lower() for token in hint_tokens)
        fallback: Any | None = None
        for entry in usage_entries:
            name_parts = " ".join(
                part
                for part in [
                    getattr(getattr(entry, "name", None), "value", None),
                    getattr(getattr(entry, "name", None), "localized_value", None),
                ]
                if part
            ).lower()
            if "gpu" in name_parts or "family" in name_parts:
                fallback = fallback or entry
            if any(token in name_parts for token in lowered_hints):
                return entry
        return fallback

    @staticmethod
    def _restriction_messages(restrictions: Iterable[Any]) -> list[str]:
        messages: list[str] = []
        for restriction in restrictions:
            reason_code = getattr(restriction, "reason_code", None)
            restriction_type = getattr(restriction, "type", None)
            values = getattr(restriction, "values", None) or []
            detail = (
                ", ".join(str(value) for value in values) if values else "subscription restriction"
            )
            messages.append(
                f"{restriction_type or 'restriction'}:{reason_code or 'unknown'}:{detail}"
            )
        return messages

    @staticmethod
    def _usage_name(entry: Any) -> str | None:
        name = getattr(entry, "name", None)
        if name is None:
            return None
        return getattr(name, "localized_value", None) or getattr(name, "value", None)
