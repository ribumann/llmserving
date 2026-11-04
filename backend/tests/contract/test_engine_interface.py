from __future__ import annotations

from datetime import UTC, datetime

from src.engines.base import (
    CancellationAck,
    DeploymentHandle,
    HealthStatus,
    InferenceEngineAdapter,
    PerformanceMetricsStream,
    PromptResult,
    SettingsSchema,
)


class NoOpInferenceEngineAdapter:
    def describeSettings(self) -> SettingsSchema:
        return SettingsSchema(
            servingSettings={"tensor_parallel_size": {"type": "integer"}},
            generationSettings={"temperature": {"type": "number"}},
            defaults={"temperature": 0.1, "max_tokens": 256},
        )

    def deploy(
        self, modelConfig: dict, inferenceConfig: dict, targetEnvironment: dict
    ) -> DeploymentHandle:
        return DeploymentHandle(
            operationId="deploy-1",
            deploymentRevisionId="revision-1",
            phase="accepted",
            state="deploying",
            diagnostics=[
                str(bool(modelConfig)),
                str(bool(inferenceConfig)),
                str(bool(targetEnvironment)),
            ],
        )

    def getHealth(self, deploymentRevisionId: str) -> HealthStatus:
        return HealthStatus(
            deploymentRevisionId=deploymentRevisionId,
            ready=True,
            details={"health": "green"},
            checkedAt=datetime.now(UTC),
        )

    def submitPrompt(self, deploymentRevisionId: str, prompt: str) -> PromptResult:
        return PromptResult(
            deploymentRevisionId=deploymentRevisionId,
            responseText=f"echo:{prompt}",
            ttftMs=12.5,
            interTokenLatencyMs=[2.1, 2.0, 1.8],
        )

    def runPerformanceWorkload(
        self, deploymentRevisionId: str, workload: dict
    ) -> PerformanceMetricsStream:
        return PerformanceMetricsStream(
            operationId=f"perf-{deploymentRevisionId}",
            samples=[{"metric": "ttft_ms", "value": 10.0, "workload": workload}],
            units={"ttft_ms": "ms"},
            acceleratorUtilizationAvailable=False,
        )

    def cancel(self, operationId: str) -> CancellationAck:
        return CancellationAck(operationId=operationId, accepted=True, alreadyTerminal=False)


def test_noop_engine_adapter_satisfies_contract() -> None:
    adapter = NoOpInferenceEngineAdapter()
    assert isinstance(adapter, InferenceEngineAdapter)

    settings = adapter.describeSettings()
    assert "temperature" in settings.generationSettings

    prompt_result = adapter.submitPrompt("revision-1", "hello")
    assert prompt_result.responseText == "echo:hello"

    cancellation = adapter.cancel("op-1")
    assert cancellation.accepted is True
