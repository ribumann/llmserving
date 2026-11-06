from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.domain.performance_workload import PerformanceWorkload
from src.performance.llmperf_runner import vllm_warmup_settings


class PerformanceWorkloadValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def validate_performance_workload_for_run(
    workload: PerformanceWorkload, *, engine_id: str | None = None
) -> None:
    if workload.concurrency < 1:
        raise PerformanceWorkloadValidationError(
            "invalid_performance_workload",
            "Performance workloads must set concurrency to at least 1.",
            {"workloadId": workload.workloadId, "field": "concurrency"},
        )
    _require_duration_fields(
        field_name="warmup",
        value=workload.warmup,
        workload_id=workload.workloadId,
    )
    if engine_id == "vllm":
        try:
            vllm_warmup_settings(workload.warmup)
        except ValueError as exc:
            raise PerformanceWorkloadValidationError(
                "invalid_performance_workload",
                str(exc),
                {"workloadId": workload.workloadId, "field": "warmup"},
            ) from exc
    _require_input_profile(workload.inputProfile, workload_id=workload.workloadId)
    _require_duration_fields(
        field_name="durationOrRequestCount",
        value=workload.durationOrRequestCount,
        workload_id=workload.workloadId,
    )
    _require_completion_criteria(
        workload.completionCriteria,
        workload_id=workload.workloadId,
    )


def _require_duration_fields(
    *,
    field_name: str,
    value: Mapping[str, Any] | None,
    workload_id: str,
) -> None:
    payload = dict(value or {})
    if not payload:
        raise PerformanceWorkloadValidationError(
            "invalid_performance_workload",
            "Performance workloads must define warm-up and duration/request-count settings.",
            {"workloadId": workload_id, "field": field_name},
        )
    if not any(payload.get(key) for key in ("requestCount", "durationSeconds")):
        raise PerformanceWorkloadValidationError(
            "invalid_performance_workload",
            "Warm-up and duration/request-count settings must include requestCount or "
            "durationSeconds.",
            {"workloadId": workload_id, "field": field_name},
        )


def _require_input_profile(value: Mapping[str, Any] | None, *, workload_id: str) -> None:
    payload = dict(value or {})
    required_keys = (
        "meanInputTokens",
        "stddevInputTokens",
        "meanOutputTokens",
        "stddevOutputTokens",
    )
    if not payload or any(key not in payload for key in required_keys):
        raise PerformanceWorkloadValidationError(
            "invalid_performance_workload",
            "Performance workloads must define mean/stddev input and output token counts.",
            {"workloadId": workload_id, "field": "inputProfile"},
        )


def _require_completion_criteria(value: Mapping[str, Any] | None, *, workload_id: str) -> None:
    payload = dict(value or {})
    if not payload:
        raise PerformanceWorkloadValidationError(
            "invalid_performance_workload",
            "Performance workloads must define completion criteria.",
            {"workloadId": workload_id, "field": "completionCriteria"},
        )
    if not any(
        payload.get(key)
        for key in (
            "targetCompletedRequests",
            "targetDurationSeconds",
            "stopOnFailureRate",
        )
    ):
        raise PerformanceWorkloadValidationError(
            "invalid_performance_workload",
            "Completion criteria must define a target request count, duration, or "
            "failure threshold.",
            {"workloadId": workload_id, "field": "completionCriteria"},
        )
