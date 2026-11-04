from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.domain.enums import ProviderType
from src.providers.base import UnsupportedProviderError
from src.providers.registry import CompositeProviderAdapter


@pytest.fixture
def providers():
    azure, local = MagicMock(), MagicMock()
    session = MagicMock()

    @contextmanager
    def session_factory():
        yield session

    registry = CompositeProviderAdapter(azure=azure, local=local, session_factory=session_factory)
    return registry, azure, local, session


@pytest.mark.parametrize("provider", ["aws", "gcp", "unknown", "", None])
def test_unknown_provider_never_routes_to_azure(providers, provider) -> None:
    registry, azure, local, session = providers
    session.get.return_value = SimpleNamespace(provider=provider)
    with pytest.raises(UnsupportedProviderError):
        registry.previewEnvironment("profile")
    with pytest.raises(UnsupportedProviderError):
        registry.getEnvironmentState("environment")
    with pytest.raises(UnsupportedProviderError):
        registry.start_provisioning(profile=SimpleNamespace(provider=provider))
    azure.assert_not_called()
    local.assert_not_called()
    assert not azure.mock_calls
    assert not local.mock_calls


def test_missing_profile_provider_is_not_implicitly_azure(providers) -> None:
    registry, azure, local, _ = providers
    with pytest.raises(UnsupportedProviderError):
        registry.start_provisioning(profile=SimpleNamespace())
    with pytest.raises(UnsupportedProviderError):
        registry.start_provisioning()
    assert not azure.mock_calls
    assert not local.mock_calls


@pytest.mark.parametrize("provider", [ProviderType.AZURE, ProviderType.LOCAL])
def test_implemented_provider_routes_without_behavior_change(providers, provider) -> None:
    registry, azure, local, session = providers
    session.get.return_value = SimpleNamespace(provider=provider)
    selected = azure if provider == ProviderType.AZURE else local
    assert (
        registry.previewEnvironment("profile", "region") is selected.previewEnvironment.return_value
    )
    selected.previewEnvironment.assert_called_once_with("profile", "region")
    registry.start_provisioning(profile=SimpleNamespace(provider=provider), region="region")
    selected.start_provisioning.assert_called_once()


def test_unknown_engine_never_routes_to_azure(providers) -> None:
    registry, azure, local, _ = providers
    with pytest.raises(LookupError, match="not supported"):
        registry.get_engine_adapter("unknown")
    assert not azure.mock_calls
    assert not local.mock_calls


def test_capability_catalog_is_explicit_and_does_not_claim_durable_runs() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/providers", headers={"X-Demo-User": "presenter@example.com"})
    assert response.status_code == 200
    providers = {item["provider"]: item for item in response.json()["providers"]}
    assert set(providers) == {"azure", "local"}
    assert providers["azure"]["engines"] == ["vllm"]
    assert providers["azure"]["cloudInfrastructure"] is True
    assert providers["azure"]["durableProvisioning"] is True
    assert providers["local"]["engines"] == ["ollama"]
    assert providers["local"]["cloudInfrastructure"] is False
    assert all(item["durableEvaluation"] is False for item in providers.values())


def test_unsupported_provider_is_an_explicit_api_error(providers) -> None:
    registry, _, _, session = providers
    session.get.return_value = SimpleNamespace(provider="aws")
    app = create_app()
    app.state.provider_adapter = registry
    with TestClient(app) as client:
        response = client.post(
            "/environments/preview",
            headers={"X-Demo-User": "presenter@example.com"},
            json={"profileId": "experimental-profile"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_provider"
