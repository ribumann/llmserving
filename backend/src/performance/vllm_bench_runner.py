from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.performance.llmperf_runner import (
    PerformanceRunOverloadError,
    _normalize_performance_result,
)

VllmBenchCallable = Callable[..., dict[str, Any]]


class VllmBenchRunner:
    def __init__(self, evaluator: VllmBenchCallable | None = None) -> None:
        self._evaluator = evaluator or self._default_evaluator

    def run(
        self,
        *,
        base_url: str,
        workload: Mapping[str, Any],
        model_id: str,
    ) -> dict[str, Any]:
        raw = self._evaluator(base_url=base_url, workload=workload, model_id=model_id)
        normalized = _normalize_performance_result(
            raw=raw,
            workload=workload,
            runner_name="vllm-bench",
        )
        if bool(raw.get("overloaded")) or str(raw.get("status") or "").lower() in {
            "overload",
            "incomplete",
        }:
            raise PerformanceRunOverloadError(
                str(
                    raw.get("message") or "The vLLM benchmark reported overload or incomplete data."
                ),
                partial_result=normalized,
            )
        return normalized

    def _default_evaluator(
        self,
        *,
        base_url: str,
        workload: Mapping[str, Any],
        model_id: str,
    ) -> dict[str, Any]:
        import vllm  # noqa: F401

        request_count = int(
            (workload.get("durationOrRequestCount") or {}).get("requestCount")
            or (workload.get("completionCriteria") or {}).get("targetCompletedRequests")
            or 1
        )
        command = [
            "vllm",
            "bench",
            "serve",
            "--backend",
            "openai-chat",
            "--base-url",
            str(base_url).rstrip("/"),
            "--endpoint",
            "/v1/chat/completions",
            "--model",
            model_id,
            "--dataset-name",
            "random",
            "--num-prompts",
            str(request_count),
            "--max-concurrency",
            str(int(workload.get("concurrency") or 1)),
            "--metric-percentiles",
            "50,95",
        ]
        completed_safety_limits = dict(workload.get("safetyLimits") or {})
        # Hard wall-clock backstop so a hung/orphaned vllm-bench subprocess can
        # never permanently occupy a worker thread and its held environment lock.
        timeout_seconds = int(completed_safety_limits.get("timeoutSeconds") or 600) + 60
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                cwd=Path.cwd(),
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            partial = _try_parse_json(exc.stdout) or _try_parse_json(exc.stderr)
            raise PerformanceRunOverloadError(
                f"vLLM benchmark did not finish within {timeout_seconds}s and was terminated.",
                partial_result=(
                    _normalize_performance_result(
                        raw=partial,
                        workload=workload,
                        runner_name="vllm-bench",
                    )
                    if isinstance(partial, Mapping)
                    else None
                ),
            ) from exc
        if completed.returncode != 0:
            partial = _try_parse_json(completed.stdout) or _try_parse_json(completed.stderr)
            raise PerformanceRunOverloadError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or "vLLM benchmark execution failed.",
                partial_result=(
                    _normalize_performance_result(
                        raw=partial,
                        workload=workload,
                        runner_name="vllm-bench",
                    )
                    if isinstance(partial, Mapping)
                    else None
                ),
            )
        parsed = _try_parse_json(completed.stdout)
        if parsed is None:
            raise RuntimeError("vLLM benchmark did not emit a parseable JSON payload.")
        return parsed


def _try_parse_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
