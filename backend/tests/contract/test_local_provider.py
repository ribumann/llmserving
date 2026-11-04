from __future__ import annotations

import httpx
from src.config import Settings
from src.domain.enums import DemoEnvironmentState, ModelSizeClass, ProviderType
from src.domain.environment import DemoEnvironment
from src.domain.profile import CloudDeploymentProfile
from src.providers.base import ProviderAdapter
from src.providers.local.adapter import LocalProviderAdapter


class FakeSession:
    def __init__(self, environment: DemoEnvironment, profile: CloudDeploymentProfile) -> None:
        self.environment = environment
        self.profile = profile

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get(self, model, identifier):
        if model is DemoEnvironment and identifier == self.environment.environmentId:
            return self.environment
        if model is CloudDeploymentProfile and identifier == self.profile.profileId:
            return self.profile
        return None

    def add(self, obj) -> None:
        if isinstance(obj, DemoEnvironment):
            self.environment = obj

    def commit(self) -> None:
        return None

    def scalars(self, _statement):
        class Empty:
            def all(self):
                return []

        return Empty()


def test_local_provider_satisfies_contract() -> None:
    profile = CloudDeploymentProfile(
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
    environment = DemoEnvironment(
        environmentId="env-local",
        profileId=profile.profileId,
        provider=ProviderType.LOCAL,
        region="local",
        regionRecommendation=None,
        lifecycleState=DemoEnvironmentState.READY,
        activeDeploymentRevisionId=None,
        providerState={},
        createdBy="presenter@example.com",
        lastModifiedBy="presenter@example.com",
    )
    adapter = LocalProviderAdapter(
        session_factory=lambda: FakeSession(environment, profile),
        settings=Settings(ollama_base_url="http://ollama.local"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": []}))
        ),
    )
    assert isinstance(adapter, ProviderAdapter)

    preview = adapter.previewEnvironment("local-ollama")
    assert preview.recommendedRegion == "local"
    assert preview.evidence

    state = adapter.getEnvironmentState("env-local")
    assert state.lifecycleState == "ready"
    assert state.context["provider"] == "local"
