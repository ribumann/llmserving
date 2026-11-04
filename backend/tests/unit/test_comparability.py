from __future__ import annotations

from src.domain.comparability import assess_run_comparability
from src.domain.enums import ComparisonStatus


def _snapshot(**overrides) -> dict:
    snapshot = {
        "environmentId": "env-demo",
        "profileId": "azure-single-gpu-3b",
        "region": "eastus2",
        "provider": "azure",
        "modelConfiguration": {"resolvedCheckpointRef": "Qwen/Qwen3-4B@main"},
        "testDefinition": {"goldenDatasetId": "golden-default"},
    }
    snapshot.update(overrides)
    return snapshot


def test_identical_snapshots_are_comparable() -> None:
    status, reasons = assess_run_comparability([_snapshot(), _snapshot()])

    assert status == ComparisonStatus.COMPARABLE
    assert reasons == []


def test_different_checkpoints_are_not_directly_comparable() -> None:
    status, reasons = assess_run_comparability(
        [
            _snapshot(),
            _snapshot(modelConfiguration={"resolvedCheckpointRef": "Qwen/Qwen3-4B@v2"}),
        ]
    )

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert any("checkpoint" in reason.lower() for reason in reasons)


def test_different_test_definitions_are_not_directly_comparable() -> None:
    status, reasons = assess_run_comparability(
        [
            _snapshot(),
            _snapshot(testDefinition={"goldenDatasetId": "golden-other"}),
        ]
    )

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert any("test definition" in reason.lower() for reason in reasons)


def test_different_test_definition_kinds_are_not_directly_comparable() -> None:
    status, reasons = assess_run_comparability(
        [
            _snapshot(testDefinition={"goldenDatasetId": "golden-default"}),
            _snapshot(testDefinition={"workloadId": "workload-default"}),
        ]
    )

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert any("test definition" in reason.lower() for reason in reasons)


def test_different_profiles_are_not_directly_comparable() -> None:
    status, reasons = assess_run_comparability(
        [
            _snapshot(),
            _snapshot(profileId="local-ollama"),
        ]
    )

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert any("infrastructure profile" in reason.lower() for reason in reasons)


def test_different_regions_are_not_directly_comparable() -> None:
    status, reasons = assess_run_comparability(
        [
            _snapshot(),
            _snapshot(region="westus3"),
        ]
    )

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert any("region" in reason.lower() for reason in reasons)


def test_different_providers_are_not_directly_comparable() -> None:
    status, reasons = assess_run_comparability(
        [
            _snapshot(),
            _snapshot(provider="local"),
        ]
    )

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert any("provider" in reason.lower() for reason in reasons)


def test_multiple_differences_accumulate_reasons() -> None:
    status, reasons = assess_run_comparability(
        [
            _snapshot(),
            _snapshot(region="westus3", profileId="local-ollama"),
        ]
    )

    assert status == ComparisonStatus.NOT_DIRECTLY_COMPARABLE
    assert len(reasons) >= 2
