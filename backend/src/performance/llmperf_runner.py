from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

LlmPerfCallable = Callable[..., dict[str, Any]]
DEFAULT_UNITS = {
    "timeToFirstTokenMs": "ms",
    "interTokenLatencyMs": "ms",
    "endToEndLatencyMs": "ms",
    "throughputTokensPerSec": "tokens/sec",
}


def vllm_warmup_request_count(warmup: Mapping[str, Any] | None) -> int:
    payload = dict(warmup or {})
    count = payload.get("requestCount", 0)
    if (
        "durationSeconds" in payload
        or type(count) is not int
        or count < 0
        or (payload and "requestCount" not in payload)
    ):
        raise ValueError(
            "vLLM warm-up requires a non-negative integer requestCount; duration is unsupported."
        )
    return count


class PerformanceRunOverloadError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        partial_result: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.partial_result = partial_result


class LlmPerfRunner:
    def __init__(self, evaluator: LlmPerfCallable | None = None) -> None:
        self._evaluator = evaluator or self._default_evaluator

    def run(
        self,
        *,
        base_url: str,
        workload: Mapping[str, Any],
        model_id: str,
    ) -> dict[str, Any]:
        warmup_count = vllm_warmup_request_count(workload.get("warmup"))
        warmup_evidence = None
        if warmup_count:
            warmup_workload = {
                **workload,
                "concurrency": 1,
                "durationOrRequestCount": {"requestCount": warmup_count},
                "completionCriteria": {"targetCompletedRequests": warmup_count},
                "_warmupPhase": True,
            }
            try:
                warmup = self._evaluator(
                    base_url=base_url, workload=warmup_workload, model_id=model_id
                )
            except PerformanceRunOverloadError as exc:
                # Warm-up results are never partial measured results.
                raise PerformanceRunOverloadError(f"LLMPerf warm-up failed: {exc}") from exc
            completed = warmup.get("results_num_completed_requests")
            started = warmup.get("results_num_requests_started")
            errors = warmup.get("results_number_errors")
            if (
                bool(warmup.get("overloaded"))
                or str(warmup.get("status") or "").lower() in {"overload", "incomplete", "failed"}
                or type(completed) is not int
                or type(started) is not int
                or type(errors) is not int
                or completed != warmup_count
                or started != warmup_count
                or errors != 0
            ):
                raise PerformanceRunOverloadError(
                    "LLMPerf warm-up failed or did not complete all configured requests."
                )
            warmup_evidence = {"completedRequests": completed, "failedRequests": errors}
        raw = self._evaluator(base_url=base_url, workload=workload, model_id=model_id)
        normalized = _normalize_performance_result(
            raw=raw,
            workload=workload,
            runner_name="llmperf",
        )
        if warmup_evidence is not None:
            normalized["testConditions"]["warmupExecution"] = warmup_evidence
        if bool(raw.get("overloaded")) or str(raw.get("status") or "").lower() in {
            "overload",
            "incomplete",
        }:
            raise PerformanceRunOverloadError(
                str(
                    raw.get("message")
                    or "The performance run reported overload or incomplete data."
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
        import llmperf

        results_dir = Path.cwd() / ".llmperf-results" / uuid4().hex
        results_dir.mkdir(parents=True, exist_ok=True)
        try:
            command = _llmperf_command(
                base_url=base_url,
                workload=workload,
                model_id=model_id,
                package_root=Path(llmperf.__file__).resolve().parent,
                results_dir=results_dir,
            )
            env = os.environ.copy()
            env.setdefault("OPENAI_API_KEY", "unused")
            env["OPENAI_API_BASE"] = f"{str(base_url).rstrip('/')}/v1"
            safety_limits = dict(workload.get("safetyLimits") or {})
            # Give the subprocess a hard wall-clock backstop beyond its own
            # --timeout CLI flag so a hung/orphaned tool can never block a
            # worker thread (and the environment lock it holds) forever.
            timeout_seconds = int(safety_limits.get("timeoutSeconds") or 600) + 60
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                    cwd=Path.cwd(),
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                if workload.get("_warmupPhase"):
                    raise PerformanceRunOverloadError(
                        f"LLMPerf did not finish within {timeout_seconds}s and was terminated."
                    ) from exc
                partial = _try_parse_json(exc.stdout) or _try_parse_json(exc.stderr)
                partial = partial or _read_latest_result(results_dir)
                raise PerformanceRunOverloadError(
                    f"LLMPerf did not finish within {timeout_seconds}s and was terminated.",
                    partial_result=(
                        _normalize_performance_result(
                            raw=partial,
                            workload=workload,
                            runner_name="llmperf",
                        )
                        if isinstance(partial, Mapping)
                        else None
                    ),
                ) from exc
            if completed.returncode != 0:
                if workload.get("_warmupPhase"):
                    raise PerformanceRunOverloadError(
                        completed.stderr.strip()
                        or completed.stdout.strip()
                        or "LLMPerf execution failed."
                    )
                partial = _try_parse_json(completed.stdout) or _try_parse_json(completed.stderr)
                partial = partial or _read_latest_result(results_dir)
                raise PerformanceRunOverloadError(
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or "LLMPerf execution failed.",
                    partial_result=(
                        _normalize_performance_result(
                            raw=partial,
                            workload=workload,
                            runner_name="llmperf",
                        )
                        if isinstance(partial, Mapping)
                        else None
                    ),
                )
            if workload.get("_warmupPhase") and (
                "Test timed out before all requests could be completed." in completed.stdout
            ):
                raise PerformanceRunOverloadError("LLMPerf warm-up timed out.")
            parsed = _try_parse_json(completed.stdout)
            if parsed is not None:
                return parsed
            file_result = _read_latest_result(results_dir)
            if file_result is None:
                raise RuntimeError("LLMPerf did not emit a parseable result payload.")
            return file_result
        finally:
            shutil.rmtree(results_dir, ignore_errors=True)


def _llmperf_command(
    *,
    base_url: str,
    workload: Mapping[str, Any],
    model_id: str,
    package_root: Path,
    results_dir: Path,
) -> list[str]:
    script_path = package_root / "token_benchmark_ray.py"
    if script_path.exists():
        command = [sys.executable, str(script_path)]
    else:
        executable = shutil.which("token_benchmark_ray")
        if executable is None:
            raise RuntimeError(
                "Unable to locate the LLMPerf token_benchmark_ray entrypoint. "
                "Install the optional evaluation dependencies in production."
            )
        command = [executable]
    input_profile = dict(workload.get("inputProfile") or {})
    duration = dict(workload.get("durationOrRequestCount") or {})
    safety_limits = dict(workload.get("safetyLimits") or {})
    return [
        *command,
        "--model",
        model_id,
        "--mean-input-tokens",
        str(int(input_profile.get("meanInputTokens") or 0)),
        "--stddev-input-tokens",
        str(int(input_profile.get("stddevInputTokens") or 0)),
        "--mean-output-tokens",
        str(int(input_profile.get("meanOutputTokens") or 0)),
        "--stddev-output-tokens",
        str(int(input_profile.get("stddevOutputTokens") or 0)),
        "--max-num-completed-requests",
        str(
            int(
                duration.get("requestCount")
                or (workload.get("completionCriteria") or {}).get("targetCompletedRequests")
                or 1
            )
        ),
        "--timeout",
        str(int(safety_limits.get("timeoutSeconds") or 600)),
        "--num-concurrent-requests",
        str(int(workload.get("concurrency") or 1)),
        "--results-dir",
        str(results_dir),
        # "openai" routes through llmperf's OpenAIChatCompletionsClient, which
        # posts directly to {OPENAI_API_BASE}/chat/completions - matching our
        # vLLM OpenAI-compatible server. "litellm" (llmperf's other generic
        # option) forwards the bare model id straight into litellm.completion(),
        # which raises "LLM Provider NOT provided" for a model id with no
        # recognized litellm provider prefix (our resolved checkpoint refs,
        # e.g. "Qwen/Qwen3-4B", don't carry one) - confirmed via a direct
        # litellm.completion() call against this deployment.
        "--llm-api",
        "openai",
        "--additional-sampling-params",
        "{}",
    ]


def _normalize_performance_result(
    *,
    raw: Mapping[str, Any],
    workload: Mapping[str, Any],
    runner_name: str,
) -> dict[str, Any]:
    raw_metrics = dict(raw.get("metrics") or raw)
    request_failures = _resolve_request_failures(raw)
    return {
        "runner": runner_name,
        "metrics": {
            # llmperf's LLMPerfResults.to_dict() (see llmperf/utils.py's
            # flatten_dict) reports these three under "results_<metric>_s"
            # (seconds) rather than a nested "*Ms" mapping, so those flattened
            # aliases carry an explicit seconds->ms scale below.
            "timeToFirstTokenMs": _resolve_percentiles(
                raw_metrics,
                ("timeToFirstTokenMs", "ttft", "ttft_ms", "time_to_first_token_ms"),
                flat_seconds_aliases=("results_ttft_s",),
            ),
            "interTokenLatencyMs": _resolve_percentiles(
                raw_metrics,
                (
                    "interTokenLatencyMs",
                    "itl",
                    "itl_ms",
                    "inter_token_latency_ms",
                    "tpot_ms",
                ),
                flat_seconds_aliases=("results_inter_token_latency_s",),
            ),
            "endToEndLatencyMs": _resolve_percentiles(
                raw_metrics,
                ("endToEndLatencyMs", "e2e", "e2e_latency_ms", "latency_ms"),
                flat_seconds_aliases=("results_end_to_end_latency_s",),
            ),
            "throughputTokensPerSec": _resolve_scalar(
                raw_metrics,
                (
                    "throughputTokensPerSec",
                    "throughput_tokens_per_sec",
                    "output_throughput",
                    "tokens_per_second",
                    "results_mean_output_throughput_token_per_s",
                ),
            ),
        },
        "requestFailures": request_failures,
        "units": dict(raw.get("units") or DEFAULT_UNITS),
        "testConditions": {
            "warmup": dict(workload.get("warmup") or {}),
            "inputProfile": dict(workload.get("inputProfile") or {}),
            "concurrency": int(workload.get("concurrency") or 0),
            "durationOrRequestCount": dict(workload.get("durationOrRequestCount") or {}),
            "safetyLimits": dict(workload.get("safetyLimits") or {}),
            "completionCriteria": dict(workload.get("completionCriteria") or {}),
        },
    }


def _resolve_request_failures(raw: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(raw.get("requestFailures") or {})
    count = int(
        payload.get("count")
        or raw.get("failedRequests")
        or raw.get("failed_requests")
        or raw.get("num_failed_requests")
        # llmperf's flattened summary (see LLMPerfResults.to_dict()) reports
        # the failure count as "results_number_errors".
        or raw.get("results_number_errors")
        or 0
    )
    total = int(
        payload.get("total")
        or raw.get("totalRequests")
        or raw.get("total_requests")
        or raw.get("num_requests")
        or raw.get("completed_requests")
        # llmperf reports the number of requests it attempted to start as
        # "results_num_requests_started" (includes any that errored out).
        or raw.get("results_num_requests_started")
        or 0
    )
    rate = float(payload.get("rate") or (count / total if total else 0.0))
    return {"count": count, "total": total, "rate": round(rate, 4)}


def _resolve_percentiles(
    raw: Mapping[str, Any],
    aliases: tuple[str, ...],
    *,
    flat_seconds_aliases: tuple[str, ...] = (),
) -> dict[str, float]:
    value = _resolve_value(raw, aliases, required=False)
    if isinstance(value, Mapping):
        payload = dict(value)
        return {
            "p50": float(payload.get("p50") or payload.get("50") or payload.get("median") or 0.0),
            "p95": float(payload.get("p95") or payload.get("95") or payload.get("tail") or 0.0),
        }
    # llmperf's LLMPerfResults.to_dict() flattens each metric's nested
    # {"quantiles": {"p50": ..., "p95": ...}} mapping into top-level
    # "<metric>_quantiles_p50" / "_quantiles_p95" keys (see flatten_dict in
    # llmperf/utils.py) and reports the underlying values in seconds, so
    # convert to ms to match this runner's contract.
    for prefix in flat_seconds_aliases:
        p50 = raw.get(f"{prefix}_quantiles_p50")
        p95 = raw.get(f"{prefix}_quantiles_p95")
        if p50 is not None or p95 is not None:
            return {"p50": float(p50 or 0.0) * 1000.0, "p95": float(p95 or 0.0) * 1000.0}
    raise ValueError(f"Missing required performance metric '{aliases[0]}'.")


def _resolve_scalar(raw: Mapping[str, Any], aliases: tuple[str, ...]) -> float:
    value = _resolve_value(raw, aliases)
    return float(value)


def _resolve_value(
    raw: Mapping[str, Any], aliases: tuple[str, ...], *, required: bool = True
) -> Any:
    for key in aliases:
        if key in raw:
            return raw[key]
    if required:
        raise ValueError(f"Missing required performance metric '{aliases[0]}'.")
    return None


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


def _read_latest_result(results_dir: Path) -> dict[str, Any] | None:
    if not results_dir.exists():
        return None
    candidates = sorted(
        results_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            parsed = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
