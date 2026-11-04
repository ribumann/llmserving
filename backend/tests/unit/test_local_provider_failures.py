from __future__ import annotations

from datetime import UTC, datetime

import httpx
from src.config import Settings
from src.domain.deployment_revision import DeploymentRevision
from src.domain.enums import (
    DemoEnvironmentState,
    DeploymentRevisionState,
    ModelSizeClass,
    ProviderType,
)
from src.domain.environment import DemoEnvironment
from src.domain.profile import CloudDeploymentProfile
from src.providers.local.adapter import LocalProviderAdapter


class FakeSession:
    def __init__(
        self,
        environment: DemoEnvironment,
        profile: CloudDeploymentProfile,
        revision: DeploymentRevision | None = None,
    ) -> None:
        self.environment = environment
        self.profile = profile
        self.revision = revision

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get(self, model, identifier):
        if model is DemoEnvironment and identifier == self.environment.environmentId:
            return self.environment
        if model is CloudDeploymentProfile and identifier == self.profile.profileId:
            return self.profile
        if (
            model is DeploymentRevision
            and self.revision
            and identifier == self.revision.deploymentRevisionId
        ):
            return self.revision
        return None

    def add(self, obj) -> None:
        if isinstance(obj, DemoEnvironment):
            self.environment = obj
        if isinstance(obj, DeploymentRevision):
            self.revision = obj

    def commit(self) -> None:
        return None

    def scalars(self, _statement):
        class Empty:
            def all(self):
                return []

        return Empty()


def _profile() -> CloudDeploymentProfile:
    return CloudDeploymentProfile(
        profileId="local-ollama",
        provider=ProviderType.LOCAL,
        modelSizeClass=ModelSizeClass.THREE_B,
        eligibleRegions=[],
        vmSku="local-machine",
        capacityAssumptions={},
        configurableInputs={},
        knownLimitations=[],
        version=1,
    )


def test_local_provisioning_fails_with_remediation_when_ollama_is_unreachable() -> None:
    environment = DemoEnvironment(
        environmentId="env-local",
        profileId="local-ollama",
        provider=ProviderType.LOCAL,
        region="local",
        regionRecommendation=None,
        lifecycleState=DemoEnvironmentState.PROVISIONING,
        activeDeploymentRevisionId=None,
        providerState={},
        createdBy="presenter@example.com",
        lastModifiedBy="presenter@example.com",
    )
    session = FakeSession(environment, _profile())
    adapter = LocalProviderAdapter(
        session_factory=lambda: session,
        settings=Settings(ollama_base_url="http://ollama.local"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ),
    )

    handle = adapter.start_provisioning(
        environment_id="env-local",
        operation_id="prov-1",
        actor_email="presenter@example.com",
        profile=_profile(),
        region="local",
        terraform_variables={},
    )

    assert handle.state == DemoEnvironmentState.PROVISIONING_FAILED.value
    assert "Install and start Ollama" in handle.diagnostics[0]
    assert environment.lifecycleState == DemoEnvironmentState.PROVISIONING_FAILED


def test_local_deployment_fails_when_checkpoint_pull_fails_without_marking_ready() -> None:
    now = datetime.now(UTC)
    environment = DemoEnvironment(
        environmentId="env-local",
        profileId="local-ollama",
        provider=ProviderType.LOCAL,
        region="local",
        regionRecommendation=None,
        lifecycleState=DemoEnvironmentState.READY,
        activeDeploymentRevisionId=None,
        providerState={},
        createdBy="presenter@example.com",
        lastModifiedBy="presenter@example.com",
    )
    revision = DeploymentRevision(
        deploymentRevisionId="env-local-deployment-1",
        environmentId="env-local",
        modelConfigId="model-1",
        inferenceConfigId="inference-1",
        engineId="ollama",
        lifecycleState=DeploymentRevisionState.PENDING,
        activePeriod={"startedAt": None, "endedAt": None},
        health={"status": "unknown", "diagnostics": []},
        createdBy="presenter@example.com",
        createdAt=now,
    )
    session = FakeSession(environment, _profile(), revision=revision)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path in {"", "/"}:
            return httpx.Response(200)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/pull":
            return httpx.Response(500, json={"error": "pull failed"})
        return httpx.Response(200)

    adapter = LocalProviderAdapter(
        session_factory=lambda: session,
        settings=Settings(ollama_base_url="http://ollama.local"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    handle = adapter.start_deployment(
        environment_id="env-local",
        deployment_revision_id="env-local-deployment-1",
        operation_id="deploy-1",
        actor_email="presenter@example.com",
        model_config={"resolvedCheckpointRef": "qwen2.5:0.5b-instruct"},
        inference_config={},
        engine_id="ollama",
        target_environment={},
    )

    assert handle.state == DeploymentRevisionState.DEPLOYMENT_FAILED.value
    assert "retry deployment" in handle.diagnostics[0].lower()
    assert revision.lifecycleState == DeploymentRevisionState.DEPLOYMENT_FAILED
    assert environment.activeDeploymentRevisionId is None
