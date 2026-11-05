"""Actual packaged evaluators against the job's owned CPU Ollama server."""

from __future__ import annotations

import argparse
import json
import math
import os
from importlib.metadata import distribution, version
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MODEL_TAG = "qwen2.5:0.5b-instruct"
MODEL_DIGEST = "a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67"
LLMPERF_COMMIT = "f1d6bed47e4501b0e371082b41601b59ab55269f"


def require_local_test_endpoint() -> str:
    value = os.environ.get("LIVE_MODEL_URL", "")
    parsed = urlparse(value)
    if (
        os.environ.get("APP_ENV") != "test"
        or os.environ.get("AUTH_MODE") != "local-demo"
        or parsed.scheme != "http"
        or parsed.hostname
        not in {"localhost", "127.0.0.1", "llmserving-ci-toolkit-ollama"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "Toolkit smoke requires explicit test/local-demo and an owned HTTP endpoint."
        )
    return value.rstrip("/")


def verify_llmperf_provenance() -> dict[str, Any]:
    metadata = json.loads(distribution("llmperf").read_text("direct_url.json") or "{}")
    if (
        metadata.get("url") != "https://github.com/ray-project/llmperf.git"
        or metadata.get("vcs_info", {}).get("commit_id") != LLMPERF_COMMIT
    ):
        raise ValueError(
            "Only the exact genuine ray-project LLMPerf commit is accepted."
        )
    return metadata


def run_benchmark(base_url: str) -> dict[str, Any]:
    from lm_eval import simple_evaluate
    from src.domain.benchmark_definition import BenchmarkDefinition
    from src.evaluation.lm_eval_runner import LmEvalRunner

    raw: dict[str, Any] = {}

    def actual_evaluator(**kwargs: Any) -> dict[str, Any]:
        raw.update(simple_evaluate(**kwargs))
        return raw

    definition = BenchmarkDefinition(
        benchmarkId="gsm8k",
        version="smoke-1-seed-42",
        presentationSubset={
            "task": "gsm8k",
            "metric": "exact_match,strict-match",
            "sampleSize": 1,
            "seed": 42,
            "useChatCompletions": True,
            "maxGenTokens": 8,
            "taskKwargs": {"num_fewshot": 0, "bootstrap_iters": 0, "log_samples": True},
        },
        passFailThreshold={
            "metric": "exact_match,strict-match",
            "baselineScore": 75.0,
            "regressionThresholdPoints": 5.0,
        },
    )
    result = LmEvalRunner(evaluator=actual_evaluator).evaluate(
        base_url=base_url,
        benchmark_definition=definition,
        model_id=MODEL_TAG,
        num_concurrent=1,
        max_retries=0,
    )
    assert raw["n-samples"]["gsm8k"]["effective"] == 1
    samples = raw["samples"]["gsm8k"]
    assert len(samples) == 1
    generated = samples[0]["resps"][0][0]
    assert isinstance(generated, str) and generated.strip()
    assert math.isfinite(result["score"]) and 0 <= result["score"] <= 100
    assert result["passFail"] in {"pass", "fail"}
    return {
        "packageVersion": version("lm_eval"),
        "taskVersion": raw["versions"]["gsm8k"],
        "effectiveSamples": 1,
        "generatedCharacters": len(generated),
        "report": result,
    }


def run_llmperf(base_url: str) -> dict[str, Any]:
    from src.performance.llmperf_runner import LlmPerfRunner

    provenance = verify_llmperf_provenance()
    workload = {
        "warmup": {"requestCount": 0},
        "inputProfile": {
            "meanInputTokens": 128,
            "stddevInputTokens": 0,
            "meanOutputTokens": 8,
            "stddevOutputTokens": 0,
        },
        "concurrency": 1,
        "durationOrRequestCount": {"requestCount": 2},
        "safetyLimits": {"timeoutSeconds": 60, "maxRequests": 2, "maxConcurrency": 1},
        "completionCriteria": {"targetCompletedRequests": 2},
    }
    result = LlmPerfRunner().run(
        base_url=base_url, workload=workload, model_id=MODEL_TAG
    )
    assert result["runner"] == "llmperf"
    assert result["requestFailures"] == {"total": 2, "count": 0, "rate": 0.0}
    for name in ("timeToFirstTokenMs", "interTokenLatencyMs", "endToEndLatencyMs"):
        for percentile in ("p50", "p95"):
            metric = result["metrics"][name][percentile]
            assert math.isfinite(metric) and metric > 0
    throughput = result["metrics"]["throughputTokensPerSec"]
    assert math.isfinite(throughput) and throughput > 0
    return {"provenance": provenance, "report": result}


def main() -> None:
    import httpx

    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=("benchmark", "llmperf"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base_url = require_local_test_endpoint()
    tags = httpx.get(f"{base_url}/api/tags", timeout=10).raise_for_status().json()
    model = next(item for item in tags["models"] if item["name"] == MODEL_TAG)
    assert model["digest"] == MODEL_DIGEST
    evidence = {
        "commit": os.environ["GITHUB_SHA"],
        "tool": args.tool,
        "model": model,
        "scope": "Owned CPU toolkit smoke; not durable routing, GPU/Azure or release performance",
        "passed": False,
    }
    try:
        evidence["result"] = (
            run_benchmark(base_url)
            if args.tool == "benchmark"
            else run_llmperf(base_url)
        )
        evidence["passed"] = True
    finally:
        args.output.write_text(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
