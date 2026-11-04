from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from src.engines.base import (
    CancellationAck,
    DeploymentHandle,
    HealthStatus,
    InferenceEngineAdapter,
    PerformanceMetricsStream,
    PromptResult,
    SettingsSchema,
)
from src.engines.vllm.performance import VllmPerformanceRunner
from src.engines.vllm.prompt import VllmPromptClient, build_locator_from_session_factory


class VllmEngineAdapter(InferenceEngineAdapter):
    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        session_factory=None,
        deployment_locator=None,
        performance_runner: VllmPerformanceRunner | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._http_client = http_client or httpx.Client(timeout=timeout_seconds)
        locator = deployment_locator
        if locator is None and session_factory is not None:
            locator = build_locator_from_session_factory(session_factory)
        self._prompt_client = VllmPromptClient(
            http_client=self._http_client,
            deployment_locator=locator,
            timeout_seconds=timeout_seconds,
        )
        self._performance_runner = performance_runner or VllmPerformanceRunner(
            http_client=self._http_client
        )

    def describeSettings(self) -> SettingsSchema:
        defaults = {
            "gpu_memory_utilization": 0.9,
            "max_model_len": 8192,
            "dtype": "auto",
            "temperature": 0.1,
            "top_p": 0.95,
            "max_tokens": 256,
        }
        return SettingsSchema(
            servingSettings={
                "gpu_memory_utilization": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 1.0,
                    "default": defaults["gpu_memory_utilization"],
                },
                "max_model_len": {
                    "type": "integer",
                    "minimum": 1024,
                    "default": defaults["max_model_len"],
                },
                "dtype": {
                    "type": "string",
                    "enum": ["auto", "float16", "bfloat16", "float32"],
                    "default": defaults["dtype"],
                },
            },
            generationSettings={
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
                "max_tokens": {
                    "type": "integer",
                    "minimum": 1,
                    "default": defaults["max_tokens"],
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
        health = self._check_health(targetEnvironment)
        if not health.ready:
            diagnostics = list(health.details.get("diagnostics") or [])
            raise RuntimeError("; ".join(diagnostics) or "vLLM health check did not pass.")
        serving_keys = sorted((inferenceConfig.get("servingSettings") or {}).keys())
        diagnostics = [
            f"Checkpoint {modelConfig.get('resolvedCheckpointRef')} validated against vLLM.",
            f"Serving settings applied: {serving_keys}.",
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

    def runPerformanceWorkload(
        self,
        deploymentRevisionId: str,
        workload: Mapping[str, Any],
    ) -> PerformanceMetricsStream:
        deployment = self._prompt_client._resolve_deployment(deploymentRevisionId)
        provider_state = dict(deployment.get("providerState") or {})
        base_url = (
            provider_state.get("inferenceApiUrl")
            or provider_state.get("baseUrl")
            or deployment.get("baseUrl")
        )
        if not base_url:
            raise RuntimeError("The deployment does not expose an inference API URL.")
        model_id = str(
            deployment.get("huggingFaceRepoId")
            or deployment.get("resolvedCheckpointRef")
            or deploymentRevisionId
        )
        return self._performance_runner.run(
            base_url=str(base_url).rstrip("/"),
            workload=workload,
            model_id=model_id,
            operation_id=f"perf-{deploymentRevisionId}",
        )

    def cancel(self, operationId: str) -> CancellationAck:
        return CancellationAck(operationId=operationId, accepted=True, alreadyTerminal=False)

    def submitPromptWithParameters(
        self,
        deploymentRevisionId: str,
        prompt: str,
        parameters: Mapping[str, Any] | None = None,
    ):
        return self._prompt_client.submitPrompt(deploymentRevisionId, prompt, parameters)

    def _check_health(
        self,
        deployment: Mapping[str, Any],
        *,
        deployment_revision_id: str | None = None,
    ) -> HealthStatus:
        provider_state = dict(deployment.get("providerState") or {})
        base_url = (
            provider_state.get("inferenceApiUrl")
            or provider_state.get("baseUrl")
            or deployment.get("baseUrl")
        )
        revision_id = str(
            deployment_revision_id or deployment.get("deploymentRevisionId") or "unknown-revision"
        )
        diagnostics: list[str] = []
        if not base_url:
            diagnostics.append("No vLLM base URL is available for health checks.")
            return HealthStatus(
                deploymentRevisionId=revision_id,
                ready=False,
                details={"status": "unknown", "diagnostics": diagnostics},
                checkedAt=datetime.now(UTC),
            )

        try:
            health_response = self._http_client.get(f"{str(base_url).rstrip('/')}/health")
            metrics_response = self._http_client.get(f"{str(base_url).rstrip('/')}/metrics")
        except httpx.HTTPError as exc:
            diagnostics.append(str(exc))
            return HealthStatus(
                deploymentRevisionId=revision_id,
                ready=False,
                details={"status": "unhealthy", "diagnostics": diagnostics},
                checkedAt=datetime.now(UTC),
            )

        status = "healthy" if health_response.is_success else "unhealthy"
        if health_response.is_success and not metrics_response.is_success:
            status = "degraded"
            diagnostics.append("Health endpoint passed but metrics endpoint was unavailable.")
        elif not health_response.is_success:
            diagnostics.append(f"/health returned HTTP {health_response.status_code}.")

        return HealthStatus(
            deploymentRevisionId=revision_id,
            ready=status == "healthy",
            details={
                "status": status,
                "diagnostics": diagnostics,
                "metricsAvailable": metrics_response.is_success,
            },
            checkedAt=datetime.now(UTC),
        )
