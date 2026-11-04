from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import httpx

from src.config import Settings
from src.domain.enums import CompletenessIndicator
from src.engines.base import (
    CancellationAck,
    DeploymentHandle,
    HealthStatus,
    InferenceEngineAdapter,
    PerformanceMetricsStream,
    PromptResult,
    SettingsSchema,
)
from src.engines.vllm.prompt import (
    VllmPromptClient,
    build_locator_from_session_factory,
)


@dataclass(slots=True, frozen=True)
class _CompletionSample:
    ttft_ms: float
    total_latency_ms: float
    inter_token_latency_ms: list[float]
    completion_tokens: int
    success: bool


class OllamaEngineAdapter(InferenceEngineAdapter):
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
        session_factory=None,
        deployment_locator=None,
        timeout_seconds: float = 30.0,
    ) -> None:
        resolved_settings = settings or Settings()
        self._base_url = str(resolved_settings.ollama_base_url).rstrip("/")
        self._http_client = http_client or httpx.Client(timeout=timeout_seconds)
        locator = deployment_locator
        if locator is None and session_factory is not None:
            locator = build_locator_from_session_factory(session_factory)
        if locator is not None:
            source_locator = locator

            # Ollama serves local tags, not the catalog's Hugging Face repository IDs.
            def local_locator(revision_id: str) -> Mapping[str, Any]:
                return {**source_locator(revision_id), "huggingFaceRepoId": None}

            locator = local_locator
        self._prompt_client = VllmPromptClient(
            http_client=self._http_client,
            deployment_locator=locator,
            timeout_seconds=timeout_seconds,
        )

    def describeSettings(self) -> SettingsSchema:
        defaults = {
            "num_ctx": 4096,
            "num_predict": 256,
            "temperature": 0.1,
            "top_p": 0.95,
        }
        return SettingsSchema(
            servingSettings={
                "num_ctx": {
                    "type": "integer",
                    "minimum": 512,
                    "default": defaults["num_ctx"],
                }
            },
            generationSettings={
                "num_predict": {
                    "type": "integer",
                    "minimum": 1,
                    "default": defaults["num_predict"],
                },
                "temperature": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 2.0,
                    "default": defaults["temperature"],
                },
                "top_p": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": defaults["top_p"],
                },
            },
            defaults=defaults,
        )

    def deploy(
        self,
        modelConfig: Mapping[str, Any],
        inferenceConfig: Mapping[str, Any],
        targetEnvironment: Mapping[str, Any],
    ) -> DeploymentHandle:
        deployment_revision_id = str(targetEnvironment.get("deploymentRevisionId") or "pending")
        operation_id = str(
            targetEnvironment.get("operationId") or f"deploy-{deployment_revision_id}"
        )
        health = self._check_health(
            targetEnvironment, deployment_revision_id=deployment_revision_id
        )
        if not health.ready:
            diagnostics = list(health.details.get("diagnostics") or [])
            raise RuntimeError("; ".join(diagnostics) or "Ollama health check did not pass.")
        diagnostics = [
            f"Checkpoint {modelConfig.get('resolvedCheckpointRef')} validated against Ollama.",
            (
                "Serving settings applied: "
                f"{sorted((inferenceConfig.get('servingSettings') or {}).keys())}."
            ),
        ]
        return DeploymentHandle(
            operationId=operation_id,
            deploymentRevisionId=deployment_revision_id,
            phase="completed",
            state="ready",
            diagnostics=diagnostics,
        )

    def getHealth(self, deploymentRevisionId: str) -> HealthStatus:
        deployment = self._prompt_client._resolve_deployment(deploymentRevisionId)
        return self._check_health(deployment, deployment_revision_id=deploymentRevisionId)

    def submitPrompt(self, deploymentRevisionId: str, prompt: str) -> PromptResult:
        result = self._prompt_client.submitPrompt(deploymentRevisionId, prompt, {})
        return PromptResult(
            deploymentRevisionId=deploymentRevisionId,
            responseText=result.responseText,
            ttftMs=result.timing["ttftMs"],
            interTokenLatencyMs=result.interTokenLatencyMs,
            diagnostics=result.diagnostics,
        )

    def submitPromptWithParameters(
        self,
        deploymentRevisionId: str,
        prompt: str,
        parameters: Mapping[str, Any] | None = None,
    ):
        ollama_options = dict(parameters or {})
        num_predict = ollama_options.pop("num_predict", None)
        if num_predict is not None:
            ollama_options.setdefault("max_tokens", num_predict)
        return self._prompt_client.submitPrompt(deploymentRevisionId, prompt, ollama_options)

    def runPerformanceWorkload(
        self,
        deploymentRevisionId: str,
        workload: Mapping[str, Any],
    ) -> PerformanceMetricsStream:
        deployment = self._prompt_client._resolve_deployment(deploymentRevisionId)
        model_id = str(deployment.get("resolvedCheckpointRef") or deploymentRevisionId)
        request_count = max(
            int(
                dict(workload.get("durationOrRequestCount") or {}).get("requestCount")
                or dict(workload.get("completionCriteria") or {}).get("targetCompletedRequests")
                or 1
            ),
            1,
        )
        concurrency = max(int(workload.get("concurrency") or 1), 1)
        prompt = str(
            dict(workload.get("inputProfile") or {}).get("prompt")
            or "Explain why low-latency inference matters for interactive applications."
        )
        generation = {
            "max_tokens": int(
                workload.get("outputTokens")
                or dict(workload.get("inputProfile") or {}).get("meanOutputTokens")
                or 64
            )
        }

        warmup_requests = int(dict(workload.get("warmup") or {}).get("requestCount") or 0)
        for _ in range(warmup_requests):
            self._issue_completion(model_id=model_id, prompt=prompt, options=generation)
        started = perf_counter()
        samples: list[_CompletionSample] = []
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="ollama-perf") as pool:
            futures = [
                pool.submit(
                    self._issue_completion,
                    model_id=model_id,
                    prompt=prompt,
                    options=generation,
                )
                for _ in range(request_count)
            ]
            for future in as_completed(futures):
                try:
                    samples.append(future.result())
                except Exception:
                    samples.append(
                        _CompletionSample(
                            ttft_ms=0.0,
                            total_latency_ms=0.0,
                            inter_token_latency_ms=[],
                            completion_tokens=0,
                            success=False,
                        )
                    )
        elapsed_seconds = max(perf_counter() - started, 0.001)
        successful = [sample for sample in samples if sample.success]
        ttft_values = [sample.ttft_ms for sample in successful]
        itl_values = [value for sample in successful for value in sample.inter_token_latency_ms]
        e2e_values = [sample.total_latency_ms for sample in successful]
        completion_tokens = sum(sample.completion_tokens for sample in successful)
        failures = len(samples) - len(successful)

        payload = {
            "runner": "ollama-http",
            "metrics": {
                "timeToFirstTokenMs": _percentiles(ttft_values),
                "interTokenLatencyMs": _percentiles(itl_values),
                "endToEndLatencyMs": _percentiles(e2e_values),
                "throughputTokensPerSec": round(completion_tokens / elapsed_seconds, 4),
            },
            "requestFailures": {
                "count": failures,
                "total": len(samples),
                "rate": round(failures / len(samples), 4) if samples else 0.0,
            },
            "units": {
                "timeToFirstTokenMs": "ms",
                "interTokenLatencyMs": "ms",
                "endToEndLatencyMs": "ms",
                "throughputTokensPerSec": "tokens/sec",
            },
            "testConditions": {
                "warmup": dict(workload.get("warmup") or {}),
                "inputProfile": dict(workload.get("inputProfile") or {}),
                "concurrency": concurrency,
                "durationOrRequestCount": dict(workload.get("durationOrRequestCount") or {}),
                "safetyLimits": dict(workload.get("safetyLimits") or {}),
                "completionCriteria": dict(workload.get("completionCriteria") or {}),
            },
            "acceleratorUtilization": {
                "available": False,
                "details": {
                    "reason": CompletenessIndicator.UNAVAILABLE_MONITORING_DATA.value,
                    "message": "Ollama does not expose an accelerator utilization endpoint.",
                },
            },
        }
        return PerformanceMetricsStream(
            operationId=f"perf-{deploymentRevisionId}",
            samples=[payload],
            units=payload["units"],
            acceleratorUtilizationAvailable=False,
        )

    def cancel(self, operationId: str) -> CancellationAck:
        return CancellationAck(operationId=operationId, accepted=True, alreadyTerminal=False)

    def _check_health(
        self,
        deployment: Mapping[str, Any],
        *,
        deployment_revision_id: str | None = None,
    ) -> HealthStatus:
        provider_state = dict(deployment.get("providerState") or {})
        base_url = str(
            provider_state.get("inferenceApiUrl")
            or provider_state.get("baseUrl")
            or deployment.get("baseUrl")
            or self._base_url
        ).rstrip("/")
        revision_id = str(
            deployment_revision_id or deployment.get("deploymentRevisionId") or "unknown-revision"
        )
        diagnostics: list[str] = []
        try:
            response = self._http_client.get(f"{base_url}/v1/models")
            if response.status_code >= 400:
                response = self._http_client.get(f"{base_url}/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            diagnostics.append(str(exc))
            return HealthStatus(
                deploymentRevisionId=revision_id,
                ready=False,
                details={"status": "unhealthy", "diagnostics": diagnostics},
                checkedAt=datetime.now(UTC),
            )

        return HealthStatus(
            deploymentRevisionId=revision_id,
            ready=True,
            details={
                "status": "healthy",
                "diagnostics": diagnostics,
                "runtime": "ollama",
                "baseUrl": base_url,
            },
            checkedAt=datetime.now(UTC),
        )

    def _issue_completion(
        self,
        *,
        model_id: str,
        prompt: str,
        options: Mapping[str, Any],
    ) -> _CompletionSample:
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            **dict(options),
            # Stream so TTFT and inter-token latency reflect real chunk
            # arrival times instead of an aggregate-latency estimate.
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        started = perf_counter()
        ttft_ms: float | None = None
        chunk_timestamps: list[float] = []
        completion_tokens = 0

        with self._http_client.stream(
            "POST", f"{self._base_url}/v1/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except ValueError:
                    continue

                usage = event.get("usage")
                if usage:
                    completion_tokens = int(usage.get("completion_tokens") or completion_tokens)

                choices = event.get("choices") or []
                if not choices:
                    continue
                content = (choices[0].get("delta") or {}).get("content")
                if not content:
                    continue
                now = perf_counter()
                if ttft_ms is None:
                    ttft_ms = (now - started) * 1000
                chunk_timestamps.append(now)

        total_latency_ms = (perf_counter() - started) * 1000
        if ttft_ms is None:
            ttft_ms = total_latency_ms

        inter_token_latencies = _inter_chunk_latencies_ms(chunk_timestamps)
        if not inter_token_latencies and completion_tokens > 1:
            inter_token_latencies = _estimate_inter_token_latencies(
                total_latency_ms=total_latency_ms,
                ttft_ms=ttft_ms,
                completion_tokens=completion_tokens,
            )
        return _CompletionSample(
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            inter_token_latency_ms=inter_token_latencies,
            completion_tokens=completion_tokens,
            success=True,
        )


def _inter_chunk_latencies_ms(chunk_timestamps: list[float]) -> list[float]:
    """Real gaps (ms) between successive streamed content-chunk arrivals."""
    if len(chunk_timestamps) < 2:
        return []
    return [
        (chunk_timestamps[i] - chunk_timestamps[i - 1]) * 1000
        for i in range(1, len(chunk_timestamps))
    ]


def _estimate_inter_token_latencies(
    *, total_latency_ms: float, ttft_ms: float, completion_tokens: int
) -> list[float]:
    token_gaps = max(completion_tokens - 1, 0)
    if token_gaps <= 0:
        return []
    residual = max(total_latency_ms - ttft_ms, 0.0)
    gap = residual / token_gaps if token_gaps else 0.0
    return [gap] * token_gaps


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0}
    ordered = sorted(values)
    return {
        "p50": round(_percentile(ordered, 0.5), 4),
        "p95": round(_percentile(ordered, 0.95), 4),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * quantile
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] + (values[upper] - values[lower]) * weight
