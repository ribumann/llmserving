from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from src.domain.catalog import ModelCatalogEntry
from src.domain.deployment_revision import DeploymentRevision
from src.domain.environment import DemoEnvironment
from src.domain.model_configuration import ModelConfiguration

DeploymentLocator = Callable[[str], Mapping[str, Any]]


@dataclass(slots=True, frozen=True)
class PromptExecution:
    responseText: str
    timing: dict[str, float]
    interTokenLatencyMs: list[float]
    diagnostics: list[str]


class VllmPromptClient:
    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        deployment_locator: DeploymentLocator | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._http_client = http_client or httpx.Client(timeout=timeout_seconds)
        self._deployment_locator = deployment_locator

    def submitPrompt(
        self,
        deploymentRevisionId: str,
        prompt: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> PromptExecution:
        deployment = self._resolve_deployment(deploymentRevisionId)
        base_url = _resolve_base_url(deployment)
        payload = {
            # vLLM's OpenAI-compatible API requires "model" to match the repo id
            # the server was started with (`--model`, see
            # jobs/model_deployment/entrypoint.py); `resolvedCheckpointRef` is
            # only a revision *within* that repo (e.g. "main") and is not a
            # loadable model id on its own, so `huggingFaceRepoId` (resolved via
            # the model's catalog entry, see `_locator` below) must take
            # precedence here.
            "model": str(
                deployment.get("huggingFaceRepoId")
                or deployment.get("resolvedCheckpointRef")
                or deploymentRevisionId
            ),
            "messages": [{"role": "user", "content": prompt}],
            **dict(parameters or {}),
            # Force streaming so TTFT and inter-token latency reflect real chunk
            # arrival times instead of being derived from total request latency.
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        started = perf_counter()
        ttft_ms: float | None = None
        chunk_timestamps: list[float] = []
        content_parts: list[str] = []
        completion_tokens = 0
        diagnostics: list[str] = []

        with self._http_client.stream(
            "POST", f"{base_url}/v1/chat/completions", json=payload
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
                content_parts.append(content)

        total_latency_ms = (perf_counter() - started) * 1000
        response_text = "".join(content_parts)

        if ttft_ms is None:
            # No streamed content chunks were observed (e.g. an empty completion).
            # Fall back to treating the whole request latency as TTFT rather than
            # reporting a misleading zero.
            ttft_ms = total_latency_ms
            diagnostics.append(
                "No streamed content chunks were observed; TTFT reflects total request latency."
            )

        inter_token_latencies = _inter_chunk_latencies_ms(chunk_timestamps)
        if not inter_token_latencies and completion_tokens > 1:
            # Fewer content chunks than completion tokens (e.g. multi-token
            # deltas): fall back to an even estimate across the residual time.
            inter_token_latencies = _estimate_inter_token_latencies(
                total_latency_ms=total_latency_ms,
                ttft_ms=ttft_ms,
                completion_tokens=completion_tokens,
            )
            diagnostics.append("Inter-token latency was estimated from aggregate request timing.")

        inter_token_avg = (
            sum(inter_token_latencies) / len(inter_token_latencies)
            if inter_token_latencies
            else 0.0
        )
        return PromptExecution(
            responseText=response_text,
            timing={
                "ttftMs": ttft_ms,
                "interTokenLatencyMsAvg": inter_token_avg,
                "totalLatencyMs": total_latency_ms,
            },
            interTokenLatencyMs=inter_token_latencies,
            diagnostics=diagnostics,
        )

    def _resolve_deployment(self, deployment_revision_id: str) -> Mapping[str, Any]:
        if self._deployment_locator is None:
            raise LookupError(
                f"No deployment locator is configured for revision '{deployment_revision_id}'."
            )
        return self._deployment_locator(deployment_revision_id)


def build_locator_from_session_factory(session_factory) -> DeploymentLocator:
    def _locator(deployment_revision_id: str) -> Mapping[str, Any]:
        with session_factory() as session:
            revision = session.get(DeploymentRevision, deployment_revision_id)
            if revision is None:
                raise LookupError(f"Deployment revision '{deployment_revision_id}' was not found.")
            environment = session.get(DemoEnvironment, revision.environmentId)
            model_configuration = session.get(ModelConfiguration, revision.modelConfigId)
            if environment is None:
                raise LookupError(f"Environment '{revision.environmentId}' was not found.")
            catalog_entry = (
                session.get(ModelCatalogEntry, model_configuration.catalogEntryId)
                if model_configuration is not None
                else None
            )
            return {
                "deploymentRevisionId": revision.deploymentRevisionId,
                "huggingFaceRepoId": (
                    catalog_entry.huggingFaceRepoId if catalog_entry is not None else None
                ),
                "resolvedCheckpointRef": (
                    model_configuration.resolvedCheckpointRef
                    if model_configuration is not None
                    else revision.modelConfigId
                ),
                "providerState": dict(environment.providerState or {}),
            }

    return _locator


def _resolve_base_url(deployment: Mapping[str, Any]) -> str:
    provider_state = dict(deployment.get("providerState") or {})
    base_url = (
        provider_state.get("inferenceApiUrl")
        or provider_state.get("baseUrl")
        or deployment.get("baseUrl")
    )
    if not base_url:
        raise RuntimeError("The deployment does not expose an inference API URL.")
    return str(base_url).rstrip("/")


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
