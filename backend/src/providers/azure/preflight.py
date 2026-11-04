from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient

LOGGER = logging.getLogger(__name__)


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
    requestedVcpus: int | None = None


@dataclass(slots=True, frozen=True)
class SkuAvailabilityResult:
    region: str
    vmSize: str
    available: bool | None
    checkedAt: datetime
    restrictions: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    vcpus: int | None = None
    family: str | None = None


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

    def evaluate_region(
        self, *, region: str, vm_size: str, priority: Literal["Regular", "Spot"] = "Spot"
    ) -> CapacityPreflightResult:
        if priority not in {"Regular", "Spot"}:
            raise ValueError(f"Unsupported VM priority '{priority}'.")
        checked_at = datetime.now(UTC)
        sku = self._check_sku(region=region, vm_size=vm_size, checked_at=checked_at)
        quota = self._check_quota(
            region=region,
            vm_size=vm_size,
            checked_at=checked_at,
            requested_vcpus=sku.vcpus,
            sku_family=sku.family,
            priority=priority,
        )

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

    def _check_quota(
        self,
        *,
        region: str,
        vm_size: str,
        checked_at: datetime,
        requested_vcpus: int | None,
        sku_family: str | None,
        priority: str,
    ) -> QuotaCheckResult:
        usage_hint_tokens = SKU_FAMILY_HINTS.get(vm_size.lower(), ())
        try:
            usage_entries = list(self.compute_client.usage.list(location=region))
        except AzureError as exc:
            LOGGER.warning("Azure quota lookup unavailable (%s).", type(exc).__name__)
            return QuotaCheckResult(
                region=region,
                vmSize=vm_size,
                quotaName=None,
                currentUsage=None,
                limit=None,
                available=None,
                checkedAt=checked_at,
                evidence=[f"Quota lookup failed for {region}: {type(exc).__name__}"],
            )

        if priority == "Spot":
            usage_match = next(
                (
                    entry
                    for entry in usage_entries
                    if str(getattr(getattr(entry, "name", None), "value", "")).lower()
                    == "lowprioritycores"
                ),
                None,
            )
        else:
            usage_match = next(
                (
                    entry
                    for entry in usage_entries
                    if sku_family
                    and str(getattr(getattr(entry, "name", None), "value", "")).lower()
                    == sku_family.lower()
                ),
                None,
            )
            if usage_match is None and not sku_family:
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
                    f"No matching {priority} quota record was returned for {vm_size} in {region}."
                ],
                requestedVcpus=requested_vcpus,
            )

        current_value = getattr(usage_match, "current_value", None)
        limit = getattr(usage_match, "limit", None)
        available = (
            None
            if current_value is None or limit is None or requested_vcpus is None
            else current_value + requested_vcpus <= limit
        )
        usage_name = self._usage_name(usage_match)
        evidence = [
            f"{priority} quota {usage_name or 'unknown'} in {region}: "
            f"current={current_value}, limit={limit}, requestedVcpus={requested_vcpus}."
        ]
        if requested_vcpus is None:
            evidence.append(
                "Requested SKU vCPU count is unavailable; quota sufficiency is unknown."
            )
        if priority == "Regular":
            regional = next(
                (
                    entry
                    for entry in usage_entries
                    if str(getattr(getattr(entry, "name", None), "value", "")).lower() == "cores"
                ),
                None,
            )
            regional_usage = getattr(regional, "current_value", None)
            regional_limit = getattr(regional, "limit", None)
            regional_available = (
                None
                if regional_usage is None or regional_limit is None or requested_vcpus is None
                else regional_usage + requested_vcpus <= regional_limit
            )
            evidence.append(
                f"Total regional vCPUs: current={regional_usage}, limit={regional_limit}, "
                f"requestedVcpus={requested_vcpus}."
            )
            if regional_available is False:
                available = False
            elif available is not False and regional_available is None:
                available = None

        return QuotaCheckResult(
            region=region,
            vmSize=vm_size,
            quotaName=usage_name,
            currentUsage=current_value,
            limit=limit,
            available=available,
            checkedAt=checked_at,
            evidence=evidence,
            requestedVcpus=requested_vcpus,
        )

    def _check_sku(
        self, *, region: str, vm_size: str, checked_at: datetime
    ) -> SkuAvailabilityResult:
        try:
            sku_entries = list(
                self.compute_client.resource_skus.list(filter=f"location eq '{region}'")
            )
        except AzureError as exc:
            LOGGER.warning("Azure SKU lookup unavailable (%s).", type(exc).__name__)
            return SkuAvailabilityResult(
                region=region,
                vmSize=vm_size,
                available=None,
                checkedAt=checked_at,
                evidence=[f"SKU lookup failed for {region}: {type(exc).__name__}"],
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
        raw_vcpus = next(
            (
                getattr(item, "value", None)
                for item in getattr(sku_entry, "capabilities", []) or []
                if str(getattr(item, "name", "")).lower() == "vcpus"
            ),
            None,
        )
        vcpus = (
            int(raw_vcpus)
            if isinstance(raw_vcpus, (str, int))
            and not isinstance(raw_vcpus, bool)
            and str(raw_vcpus).isdecimal()
            else None
        )
        if vcpus is not None and vcpus <= 0:
            vcpus = None
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
            vcpus=vcpus,
            family=getattr(sku_entry, "family", None),
        )

    @staticmethod
    def _match_usage(usage_entries: Iterable[Any], hint_tokens: tuple[str, ...]) -> Any | None:
        lowered_hints = tuple(token.lower() for token in hint_tokens)
        for entry in usage_entries:
            name_parts = " ".join(
                part
                for part in [
                    getattr(getattr(entry, "name", None), "value", None),
                    getattr(getattr(entry, "name", None), "localized_value", None),
                ]
                if part
            ).lower()
            if any(token in name_parts for token in lowered_hints):
                return entry
        return None

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
