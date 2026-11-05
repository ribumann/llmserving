from __future__ import annotations

import json
from unittest.mock import Mock

import httpx
import pytest
from src.engines.base import PerformanceMetricsStream
from src.engines.vllm.performance import VllmPerformanceRunner
from src.performance.llmperf_runner import LlmPerfRunner


def _run_with_metrics(metrics: str) -> PerformanceMetricsStream:
    llmperf = Mock(spec=LlmPerfRunner)
    llmperf.run.return_value = {"metrics": {}}
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text=metrics))
    with httpx.Client(transport=transport) as client:
        return VllmPerformanceRunner(http_client=client, llmperf_runner=llmperf).run(
            base_url="http://inference",
            workload={},
            model_id="test-model",
            operation_id="test-operation",
        )


@pytest.mark.parametrize(
    "metric",
    ["vllm:gpu_cache_usage_perc", "vllm:kv_cache_usage_perc"],
)
def test_cache_occupancy_is_not_accelerator_utilization(metric: str) -> None:
    stream = _run_with_metrics(f'{metric}{{model_name="test-model"}} 0.75\n')

    assert stream.acceleratorUtilizationAvailable is False
    assert stream.samples[0]["acceleratorUtilization"] == {"available": False, "details": None}


@pytest.mark.parametrize("cache_first", [True, False])
def test_physical_gpu_samples_are_not_shadowed_by_cache_occupancy(cache_first: bool) -> None:
    cache = 'vllm:gpu_cache_usage_perc{model_name="test-model"} 0.75\n'
    physical = 'DCGM_FI_DEV_GPU_UTIL{gpu="0"} 76\nDCGM_FI_DEV_GPU_UTIL{gpu="1"} 82\n'
    stream = _run_with_metrics(cache + physical if cache_first else physical + cache)

    assert stream.acceleratorUtilizationAvailable is True
    assert stream.samples[0]["acceleratorUtilization"] == {
        "available": True,
        "details": {
            "metric": "DCGM_FI_DEV_GPU_UTIL",
            "average": 79.0,
            "max": 82.0,
            "samples": [76.0, 82.0],
        },
    }


@pytest.mark.parametrize(
    "metric",
    [
        "DCGM_FI_DEV_GPU_UTIL",
        "gpu_utilization",
        "nv_gpu_utilization",
        "vllm:gpu_utilization_perc",
    ],
)
@pytest.mark.parametrize("sample", ["NaN", "+Inf", "-Inf", "invalid"])
def test_unusable_physical_samples_are_unavailable(metric: str, sample: str) -> None:
    stream = _run_with_metrics(f"{metric} {sample}\n")

    assert stream.acceleratorUtilizationAvailable is False
    assert stream.samples[0]["acceleratorUtilization"] == {"available": False, "details": None}
    json.dumps(stream.samples, allow_nan=False)


def test_nonfinite_samples_do_not_poison_valid_physical_samples() -> None:
    stream = _run_with_metrics(
        'DCGM_FI_DEV_GPU_UTIL{gpu="0"} NaN\nDCGM_FI_DEV_GPU_UTIL{gpu="1"} 76\n'
    )

    assert stream.acceleratorUtilizationAvailable is True
    assert stream.samples[0]["acceleratorUtilization"]["details"] == {
        "metric": "DCGM_FI_DEV_GPU_UTIL",
        "average": 76.0,
        "max": 76.0,
        "samples": [76.0],
    }
    json.dumps(stream.samples, allow_nan=False)
