from __future__ import annotations

from collections.abc import Mapping
from statistics import mean
from typing import Any

import httpx

from src.engines.base import PerformanceMetricsStream
from src.performance.llmperf_runner import LlmPerfRunner


class VllmPerformanceRunner:
    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        llmperf_runner: LlmPerfRunner | None = None,
    ) -> None:
        self._http_client = http_client or httpx.Client(timeout=30.0)
        self._llmperf_runner = llmperf_runner or LlmPerfRunner()

    def run(
        self,
        *,
        base_url: str,
        workload: Mapping[str, Any],
        model_id: str,
        operation_id: str,
    ) -> PerformanceMetricsStream:
        result = self._llmperf_runner.run(
            base_url=base_url,
            workload=workload,
            model_id=model_id,
        )
        available, details = self._resolve_accelerator_utilization(base_url)
        sample = {
            **result,
            "acceleratorUtilization": {
                "available": available,
                "details": details,
            },
        }
        return PerformanceMetricsStream(
            operationId=operation_id,
            samples=[sample],
            units=dict(result.get("units") or {}),
            acceleratorUtilizationAvailable=available,
        )

    def _resolve_accelerator_utilization(self, base_url: str) -> tuple[bool, dict[str, Any] | None]:
        try:
            response = self._http_client.get(f"{str(base_url).rstrip('/')}/metrics")
            response.raise_for_status()
        except httpx.HTTPError:
            return False, None

        values_by_metric: dict[str, list[float]] = {}
        for line in response.text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            metric_name, metric_value = _parse_prometheus_sample(stripped)
            if metric_name is None or metric_value is None:
                continue
            if metric_name not in {
                "DCGM_FI_DEV_GPU_UTIL",
                "gpu_utilization",
                "nv_gpu_utilization",
                "vllm:gpu_utilization_perc",
                "vllm:gpu_cache_usage_perc",
            }:
                continue
            values_by_metric.setdefault(metric_name, []).append(metric_value)

        if not values_by_metric:
            return False, None

        metric_name = next(iter(values_by_metric))
        values = values_by_metric[metric_name]
        return True, {
            "metric": metric_name,
            "average": round(mean(values), 4),
            "max": round(max(values), 4),
            "samples": [round(value, 4) for value in values],
        }


def _parse_prometheus_sample(line: str) -> tuple[str | None, float | None]:
    metric_and_labels, _, value_text = line.partition(" ")
    if not value_text:
        return None, None
    metric_name = metric_and_labels.split("{", 1)[0]
    try:
        value = float(value_text.strip())
    except ValueError:
        return None, None
    return metric_name, value
