from __future__ import annotations

from collections.abc import Iterable

from src.domain.enums import DatasetProvenance, DuplicateCheckState, ReviewStatus
from src.domain.golden_dataset import GoldenDataset


class GoldenDatasetValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _require_case_fields(cases: Iterable[dict[str, object]]) -> None:
    seen_case_ids: set[str] = set()
    for index, case in enumerate(cases):
        case_id = str(case.get("caseId") or "").strip()
        prompt_input = str(case.get("input") or "").strip()
        evaluation_rule = str(case.get("evaluationRule") or "").strip()
        if not case_id or not prompt_input or not evaluation_rule:
            raise GoldenDatasetValidationError(
                "invalid_dataset_definition",
                "Golden dataset cases must define caseId, input, and evaluationRule.",
                {"caseIndex": index},
            )
        if case_id in seen_case_ids:
            raise GoldenDatasetValidationError(
                "duplicate_case_id",
                f"Golden dataset case '{case_id}' is duplicated.",
                {"caseId": case_id},
            )
        seen_case_ids.add(case_id)


def validate_golden_dataset_registration(dataset: GoldenDataset) -> GoldenDataset:
    _require_case_fields(dataset.cases or [])
    if dataset.provenance == DatasetProvenance.AI_GENERATED and not dataset.generationContext:
        raise GoldenDatasetValidationError(
            "missing_generation_context",
            "AI-generated golden datasets must retain generation context.",
            {"goldenDatasetId": dataset.goldenDatasetId},
        )
    return dataset


def validate_golden_dataset_for_run(dataset: GoldenDataset) -> GoldenDataset:
    validate_golden_dataset_registration(dataset)
    if dataset.duplicateCheckState == DuplicateCheckState.DUPLICATES_DETECTED:
        raise GoldenDatasetValidationError(
            "duplicate_cases_detected",
            "This golden dataset cannot be executed until duplicate cases are resolved.",
            {"goldenDatasetId": dataset.goldenDatasetId},
        )
    if (
        dataset.provenance == DatasetProvenance.AI_GENERATED
        and dataset.reviewStatus == ReviewStatus.UNREVIEWED
    ):
        raise GoldenDatasetValidationError(
            "unreviewed_dataset_rejected",
            "Unreviewed AI-generated golden datasets cannot be executed.",
            {"goldenDatasetId": dataset.goldenDatasetId},
        )
    return dataset
