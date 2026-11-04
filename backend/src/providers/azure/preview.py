from __future__ import annotations

from dataclasses import dataclass

from src.domain.profile import CloudDeploymentProfile
from src.providers.azure.preflight import AzureCapacityPreflight, CapacityPreflightResult
from src.providers.base import RegionRecommendation

FALLBACK_REGION_ORDER = [
    "polandcentral",
    "eastus2",
    "southcentralus",
    "westus3",
    "westeurope",
    "northeurope",
]

DEFAULT_UNCERTAINTY_NOTE = (
    "llmserving checks quota and SKU signals before deploying, but Azure GPU capacity is "
    "subscription- and time-dependent and cannot be guaranteed in advance. If deployment fails "
    "with AllocationFailed, try an alternate region or SKU."
)


@dataclass(slots=True, frozen=True)
class PreviewEvaluation:
    recommendation: RegionRecommendation
    checks: list[CapacityPreflightResult]


class AzurePreviewService:
    def __init__(self, *, preflight: AzureCapacityPreflight) -> None:
        self._preflight = preflight

    def preview_environment(
        self, *, profile: CloudDeploymentProfile, region_override: str | None = None
    ) -> PreviewEvaluation:
        regions = self._ordered_regions(profile.eligibleRegions, region_override)
        checks = [
            self._preflight.evaluate_region(region=region, vm_size=profile.vmSku)
            for region in regions
        ]

        if region_override is not None:
            selected = checks[0]
            evidence = [
                f"Region override '{region_override}' revalidated for profile {profile.profileId}.",
                *selected.evidence,
            ]
            uncertainty_note = self._compose_uncertainty(selected)
            return PreviewEvaluation(
                recommendation=RegionRecommendation(
                    recommendedRegion=region_override,
                    evidence=evidence,
                    evaluatedAt=selected.checkedAt,
                    uncertaintyNote=uncertainty_note,
                    regionOverrideValidated=True,
                ),
                checks=checks,
            )

        selected = self._pick_best_region(checks)
        evidence = [
            f"Profile {profile.profileId} evaluated across {', '.join(regions)}.",
            *selected.evidence,
        ]
        if selected.available is True:
            evidence.insert(
                1,
                (
                    f"Selected {selected.region} as the first eligible region "
                    "with quota and SKU signals available."
                ),
            )
        elif selected.available is None:
            evidence.insert(
                1,
                (
                    f"Selected {selected.region} as the best fallback region "
                    "with incomplete Azure capacity signals."
                ),
            )
        else:
            evidence.insert(
                1,
                (
                    "No region had confirmed quota and SKU availability; "
                    f"defaulting to {selected.region} for operator review."
                ),
            )

        return PreviewEvaluation(
            recommendation=RegionRecommendation(
                recommendedRegion=selected.region,
                evidence=evidence,
                evaluatedAt=selected.checkedAt,
                uncertaintyNote=self._compose_uncertainty(selected),
                regionOverrideValidated=False,
            ),
            checks=checks,
        )

    @staticmethod
    def _ordered_regions(eligible_regions: list[str], region_override: str | None) -> list[str]:
        if region_override is not None:
            return [region_override]

        prioritized = [region for region in FALLBACK_REGION_ORDER if region in eligible_regions]
        remaining = [region for region in eligible_regions if region not in prioritized]
        return prioritized + remaining

    @staticmethod
    def _pick_best_region(checks: list[CapacityPreflightResult]) -> CapacityPreflightResult:
        available = next((check for check in checks if check.available is True), None)
        if available is not None:
            return available

        uncertain = next((check for check in checks if check.available is None), None)
        if uncertain is not None:
            return uncertain

        return checks[0]

    @staticmethod
    def _compose_uncertainty(check: CapacityPreflightResult) -> str:
        if not check.uncertaintyReasons:
            return DEFAULT_UNCERTAINTY_NOTE

        return f"{DEFAULT_UNCERTAINTY_NOTE} {' '.join(check.uncertaintyReasons)}"
