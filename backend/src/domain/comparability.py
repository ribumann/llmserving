from __future__ import annotations

from typing import Any

from src.domain.enums import ComparisonStatus, ProviderType


def assess_provider_comparability(
    left_provider: ProviderType | str, right_provider: ProviderType | str
) -> tuple[ComparisonStatus, list[str]]:
    left = ProviderType(str(left_provider))
    right = ProviderType(str(right_provider))
    if left != right:
        return (
            ComparisonStatus.NOT_DIRECTLY_COMPARABLE,
            [
                "These results came from different provider types "
                f"({left.value} vs {right.value}) and are not directly comparable."
            ],
        )
    return ComparisonStatus.COMPARABLE, []


def _distinct_values(snapshots: list[dict[str, Any]], *path: str) -> set[Any]:
    values: set[Any] = set()
    for snapshot in snapshots:
        cursor: Any = snapshot
        for key in path:
            cursor = cursor.get(key) if isinstance(cursor, dict) else None
        if cursor is not None:
            values.add(cursor)
    return values


def _test_definition_id(snapshot: dict[str, Any]) -> Any:
    definition = dict(snapshot.get("testDefinition") or {})
    return (
        definition.get("goldenDatasetId")
        or definition.get("workloadId")
        or definition.get("benchmarkId")
    )


def assess_run_comparability(
    snapshots: list[dict[str, Any]],
) -> tuple[ComparisonStatus, list[str]]:
    """Flags result reports produced under materially different conditions
    (FR-059): different checkpoint, test definition, infrastructure profile,
    region, or provider.

    Takes each compared run's immutable `environmentContextSnapshot`
    (captured at run-start time per FR-020), never live environment/revision
    state, so a later redeploy or teardown never changes what an already
    retained `Comparison` says about the runs it covers.
    """
    status = ComparisonStatus.COMPARABLE
    reasons: list[str] = []

    def _flag(values: set[Any], label: str) -> None:
        nonlocal status
        if len(values) > 1:
            status = ComparisonStatus.NOT_DIRECTLY_COMPARABLE
            formatted = ", ".join(str(value) for value in sorted(values, key=str))
            reasons.append(
                f"These results used different {label} ({formatted}) and are not directly "
                "comparable."
            )

    providers = _distinct_values(snapshots, "provider")
    if len(providers) > 1:
        ordered = sorted(providers, key=str)
        provider_status, provider_reasons = assess_provider_comparability(ordered[0], ordered[1])
        if provider_status != ComparisonStatus.COMPARABLE:
            status = provider_status
            reasons.extend(provider_reasons)

    _flag(
        _distinct_values(snapshots, "modelConfiguration", "resolvedCheckpointRef"),
        "model checkpoints",
    )
    test_definition_ids = {
        value for snapshot in snapshots if (value := _test_definition_id(snapshot)) is not None
    }
    _flag(test_definition_ids, "test definitions")
    _flag(_distinct_values(snapshots, "profileId"), "infrastructure profiles")
    _flag(_distinct_values(snapshots, "region"), "regions")

    return status, reasons
