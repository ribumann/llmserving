from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from src.api.errors import ApiError
from src.api.routes.environments import _terraform_variables
from src.config import Settings
from src.domain.profile import CloudDeploymentProfile
from src.providers.azure.adapter import AzureProviderAdapter
from src.providers.azure.provision import AzureProvisioner
from tests.support.demo_backend import MemorySession, MemorySessionContext


def profile():
    return CloudDeploymentProfile(
        profileId="test-profile",
        vmSku="Standard_NC16as_T4_v3",
        configurableInputs={"profileSizeClass": "small"},
        capacityAssumptions={},
    )


def variables(settings, **inputs):
    return _terraform_variables(
        environment_id="demo123",
        profile=profile(),
        settings=settings,
        inputs={"adminSshPublicKey": "test-key", **inputs},
    )


def test_default_group_remains_managed_and_caller_cannot_select_group():
    result = variables(
        Settings(_env_file=None),
        existing_resource_group_name="rg-other",
        existingResourceGroupName="rg-other",
        tags={"managedBy": "copilot-release"},
    )
    assert "existing_resource_group_name" not in result
    assert result["tags"]["managedBy"] == "terraform"


def test_operator_group_and_tags_override_caller():
    result = variables(
        Settings(
            _env_file=None,
            azure_demo_resource_group_name="rg-retained",
            azure_resource_tags={
                "project": "owned-test",
                "managedBy": "copilot-release",
            },
        ),
        existingResourceGroupName="rg-other",
        tags={"project": "forged", "managedBy": "forged", "extra": "kept"},
    )
    assert result["existing_resource_group_name"] == "rg-retained"
    assert result["tags"] == {
        "project": "owned-test",
        "managedBy": "copilot-release",
        "extra": "kept",
    }


def test_operator_tags_parse_from_environment(monkeypatch):
    monkeypatch.setenv("AZURE_RESOURCE_TAGS", '{"managedBy":"copilot-release","project":"owned"}')
    monkeypatch.setenv("AZURE_DEMO_RESOURCE_GROUP_NAME", "rg-retained")
    settings = Settings(_env_file=None)
    assert settings.azure_resource_tags == {
        "managedBy": "copilot-release",
        "project": "owned",
    }
    assert settings.azure_demo_resource_group_name == "rg-retained"


@pytest.mark.parametrize("name", ["", " ", "../group", "group.", "a" * 91])
def test_invalid_group_configuration_fails_closed(name):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, azure_demo_resource_group_name=name)


@pytest.mark.parametrize("tags", ["not-a-map", {"owner": ["invalid"]}])
def test_invalid_caller_tags_are_explicit_errors(tags):
    with pytest.raises(ApiError) as error:
        variables(Settings(_env_file=None), tags=tags)
    assert error.value.status_code == 422
    assert error.value.code == "invalid_resource_tags"


@pytest.mark.parametrize("retained", [False, True])
def test_teardown_preview_uses_saved_mode_not_changed_operator_settings(retained):
    session = MemorySession()
    session.seed_defaults()
    session.environments["env-demo"].providerState = {
        "resourceGroupName": "rg-saved",
        "vmName": "vm-saved",
        "terraform": {
            "variables": ({"existing_resource_group_name": "rg-saved"} if retained else {})
        },
    }
    adapter = AzureProviderAdapter(
        session_factory=lambda: MemorySessionContext(session),
        settings=Settings(
            _env_file=None,
            azure_demo_resource_group_name=None if retained else "rg-current",
        ),
    )
    result = adapter.teardownPreview("env-demo")
    assert any(r["type"] == "resourceGroup" for r in result.resources) is not retained
    assert any(r["type"] == "virtualMachine" for r in result.resources)
    assert ("retained resource group" in result.consequences[0]) is retained


def test_destroy_dispatch_reuses_saved_group_and_tags_after_operator_change():
    session = MemorySession()
    session.seed_defaults()
    saved = {
        "subscription_id": "test-sub",
        "environment_id": "env-demo",
        "existing_resource_group_name": "rg-saved",
        "tags": {"managedBy": "copilot-release", "project": "saved-test"},
    }
    session.environments["env-demo"].providerState = {"terraform": {"variables": saved}}
    session.environments["env-demo"].activeOperationId = None
    client = MagicMock()
    client.__enter__.return_value = client
    client.start_orchestration.return_value = "test-instance"
    provisioner = AzureProvisioner(
        session_factory=lambda: MemorySessionContext(session),
        settings=Settings(
            _env_file=None,
            azure_demo_resource_group_name="rg-new",
            azure_resource_tags={"project": "new-test"},
        ),
        functions_client_factory=lambda: client,
    )
    provisioner._run_teardown("env-demo", "op-test", "presenter@example.com")
    assert client.start_orchestration.call_args.kwargs["job_input"]["terraformVariables"] == saved
