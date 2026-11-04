from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from src.domain.enums import ProviderType


class UnsupportedProviderError(ValueError):
    """The requested provider has no implemented adapter."""


@dataclass(slots=True, frozen=True)
class ProviderCapabilities:
    provider: ProviderType
    engines: tuple[str, ...]
    cloudInfrastructure: bool
    durableProvisioning: bool
    durableModelDeployment: bool
    durableEvaluation: bool


@dataclass(slots=True, frozen=True)
class RegionRecommendation:
    recommendedRegion: str
    evidence: list[str]
    evaluatedAt: datetime
    uncertaintyNote: str
    regionOverrideValidated: bool = False


@dataclass(slots=True, frozen=True)
class ProvisioningHandle:
    operationId: str
    phase: str
    state: str
    diagnostics: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class EnvironmentStateView:
    environmentId: str
    lifecycleState: str
    activeRevisionId: str | None
    providerState: Mapping[str, Any]
    context: Mapping[str, Any]


@dataclass(slots=True, frozen=True)
class DeploymentHandle:
    operationId: str
    deploymentRevisionId: str
    phase: str
    state: str
    diagnostics: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class TeardownPreview:
    environmentId: str
    previewToken: str
    resources: list[Mapping[str, Any]]
    consequences: list[str]


@dataclass(slots=True, frozen=True)
class TeardownHandle:
    operationId: str
    phase: str
    state: str
    resourceOutcomes: list[Mapping[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@runtime_checkable
class ProviderAdapter(Protocol):
    """Contract isolating provider-specific lifecycle operations from the domain layer."""

    def previewEnvironment(
        self, profileId: str, regionOverride: str | None = None
    ) -> RegionRecommendation:
        """Evaluate quota and capacity signals, recommend a region, or revalidate an override."""

    def provisionEnvironment(self, profileId: str, region: str) -> ProvisioningHandle:
        """Start async environment provisioning and surface progress plus diagnostics."""

    def getEnvironmentState(self, environmentId: str) -> EnvironmentStateView:
        """Return current resource state, active revision info, and cost/capacity context."""

    def deployRevision(
        self,
        environmentId: str,
        modelConfig: Mapping[str, Any],
        inferenceConfig: Mapping[str, Any],
        engineId: str,
    ) -> DeploymentHandle:
        """Validate infrastructure, model, checkpoint, and inference configuration."""

    def teardownPreview(self, environmentId: str) -> TeardownPreview:
        """Enumerate managed resources and preview the consequences of removing the environment."""

    def teardownEnvironment(self, environmentId: str, previewToken: str) -> TeardownHandle:
        """Execute teardown and report removed, retained, or failed resource actions."""
