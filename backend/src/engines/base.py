from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True, frozen=True)
class SettingsSchema:
    servingSettings: Mapping[str, Any]
    generationSettings: Mapping[str, Any]
    defaults: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DeploymentHandle:
    operationId: str
    deploymentRevisionId: str
    phase: str
    state: str
    diagnostics: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class HealthStatus:
    deploymentRevisionId: str
    ready: bool
    details: Mapping[str, Any]
    checkedAt: datetime


@dataclass(slots=True, frozen=True)
class PromptResult:
    deploymentRevisionId: str
    responseText: str
    ttftMs: float | None
    interTokenLatencyMs: list[float]
    diagnostics: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class PerformanceMetricsStream:
    operationId: str
    samples: list[Mapping[str, Any]]
    units: Mapping[str, str]
    acceleratorUtilizationAvailable: bool


@dataclass(slots=True, frozen=True)
class CancellationAck:
    operationId: str
    accepted: bool
    alreadyTerminal: bool


@runtime_checkable
class InferenceEngineAdapter(Protocol):
    """Contract for pluggable inference engines used by the backend domain layer."""

    def describeSettings(self) -> SettingsSchema:
        """
        Enumerate presenter-controllable serving and generation settings plus visible defaults.
        """

    def deploy(
        self,
        modelConfig: Mapping[str, Any],
        inferenceConfig: Mapping[str, Any],
        targetEnvironment: Mapping[str, Any],
    ) -> DeploymentHandle:
        """Load the checkpoint referenced by modelConfig and apply inferenceConfig."""

    def getHealth(self, deploymentRevisionId: str) -> HealthStatus:
        """Return health, error, and resource information for the active deployment revision."""

    def submitPrompt(self, deploymentRevisionId: str, prompt: str) -> PromptResult:
        """Return response text, timing details, and any prompt execution errors."""

    def runPerformanceWorkload(
        self,
        deploymentRevisionId: str,
        workload: Mapping[str, Any],
    ) -> PerformanceMetricsStream:
        """Stream or accumulate TTFT, latency, throughput, failure, and utilization metrics."""

    def cancel(self, operationId: str) -> CancellationAck:
        """Acknowledge cancellation idempotently without duplicating diagnostics or records."""
