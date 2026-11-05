from __future__ import annotations

import json
from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from conftest import load_worker_entrypoint

entrypoint = load_worker_entrypoint("terraform_runner")


def state(
    path,
    *,
    mode="managed",
    name="rg-llm-demo-demo123",
    resource_type="azurerm_resource_group",
    attributes=None,
):
    path.joinpath("terraform.tfstate").write_text(
        json.dumps(
            {
                "version": 4,
                "outputs": {},
                "resources": [
                    {
                        "mode": mode,
                        "type": resource_type,
                        "name": "renamed",
                        "instances": [
                            {"index_key": 0, "attributes": attributes or {"name": name}}
                        ],
                    }
                ],
            }
        )
    )


@pytest.mark.parametrize("action", ["apply", "destroy"])
def test_managed_group_cannot_be_adopted_before_any_command(
    tmp_path, monkeypatch, action
):
    state(tmp_path)
    monkeypatch.setattr(entrypoint, "_blob_url", lambda *_: None)
    monkeypatch.setattr(entrypoint, "_ensure_azure_cli_auth", MagicMock())
    monkeypatch.setattr(
        entrypoint,
        "_remote_state_lock",
        lambda *_: nullcontext(entrypoint._StateLock()),
    )
    monkeypatch.setattr(entrypoint, "_download_shared_state", MagicMock())
    monkeypatch.setattr(entrypoint, "_download_remote_state", MagicMock())
    command = MagicMock()
    monkeypatch.setattr(entrypoint, "_run_terraform", command)
    callback = MagicMock()
    with pytest.raises(entrypoint.TerraformRunError, match="ownership mode"):
        entrypoint.run(
            workflow_id="wf",
            environment_id="demo123",
            action=action,
            terraform_variables={"existing_resource_group_name": "rg-retained"},
            working_dir=tmp_path,
            callback=callback,
        )
    command.assert_not_called()
    callback.complete_workflow.assert_not_called()


@pytest.mark.parametrize(
    "mode,name,variables",
    [
        ("managed", "rg-llm-demo-demo123", {}),
        ("data", "RG-Retained", {"existing_resource_group_name": "rg-retained"}),
    ],
)
def test_matching_mode_and_owner_are_accepted(tmp_path, mode, name, variables):
    state(tmp_path, mode=mode, name=name)
    entrypoint._validate_group_ownership(tmp_path, "demo123", variables)


@pytest.mark.parametrize(
    "mode,name,variables",
    [
        ("data", "rg-retained", {}),
        ("data", "rg-unrelated", {"existing_resource_group_name": "rg-retained"}),
        ("managed", "rg-llm-demo-other", {}),
    ],
)
def test_switch_or_wrong_group_is_refused(tmp_path, mode, name, variables):
    state(tmp_path, mode=mode, name=name)
    with pytest.raises(
        entrypoint.TerraformRunError, match="ownership mode|environment owner"
    ):
        entrypoint._validate_group_ownership(tmp_path, "demo123", variables)


@pytest.mark.parametrize("value", ["", " ", "../group", "group.", 42])
def test_invalid_retained_group_never_becomes_default_mode(tmp_path, value):
    with pytest.raises(entrypoint.TerraformRunError, match="Invalid retained"):
        entrypoint._validate_group_ownership(
            tmp_path, "demo123", {"existing_resource_group_name": value}
        )


def test_fresh_retained_state_is_allowed(tmp_path):
    entrypoint._validate_group_ownership(
        tmp_path, "demo123", {"existing_resource_group_name": "rg-retained"}
    )


@pytest.mark.parametrize(
    "attributes",
    [
        {"resource_group_name": "rg-retained", "tags": {"environmentId": "other"}},
        {"resource_group_name": "rg-unrelated", "tags": {"environmentId": "demo123"}},
        {"resource_group_name": "rg-retained", "tags": {}},
    ],
)
def test_resource_without_group_record_still_needs_correct_ownership(
    tmp_path, attributes
):
    state(
        tmp_path, resource_type="azurerm_linux_virtual_machine", attributes=attributes
    )
    with pytest.raises(entrypoint.TerraformRunError, match="environment owner"):
        entrypoint._validate_group_ownership(
            tmp_path, "demo123", {"existing_resource_group_name": "rg-retained"}
        )


def test_valid_owned_resource_without_group_record_is_allowed(tmp_path):
    state(
        tmp_path,
        resource_type="azurerm_linux_virtual_machine",
        attributes={
            "name": "llm-demo123-vm",
            "resource_group_name": "rg-retained",
            "tags": {"environmentId": "demo123"},
        },
    )
    entrypoint._validate_group_ownership(
        tmp_path, "demo123", {"existing_resource_group_name": "rg-retained"}
    )


@pytest.mark.parametrize(
    "resource_type,attributes",
    [
        (
            "azurerm_linux_virtual_machine",
            {"name": "llm-other-vm", "resource_group_name": "rg-retained"},
        ),
        (
            "azurerm_virtual_machine_extension",
            {
                "virtual_machine_id": (
                    "/subscriptions/sub/resourceGroups/rg-retained/providers/"
                    "Microsoft.Compute/virtualMachines/llm-other-vm"
                )
            },
        ),
    ],
)
def test_owned_tags_cannot_hide_wrong_resource_name_or_driver_parent(
    tmp_path, resource_type, attributes
):
    state(
        tmp_path,
        resource_type=resource_type,
        attributes={**attributes, "tags": {"environmentId": "demo123"}},
    )
    with pytest.raises(entrypoint.TerraformRunError, match="environment owner"):
        entrypoint._validate_group_ownership(
            tmp_path, "demo123", {"existing_resource_group_name": "rg-retained"}
        )


def test_owned_driver_parent_is_allowed(tmp_path):
    state(
        tmp_path,
        resource_type="azurerm_virtual_machine_extension",
        attributes={
            "virtual_machine_id": (
                "/subscriptions/sub/resourceGroups/rg-retained/providers/"
                "Microsoft.Compute/virtualMachines/llm-demo123-vm"
            ),
            "tags": {"environmentId": "demo123"},
        },
    )
    entrypoint._validate_group_ownership(
        tmp_path, "demo123", {"existing_resource_group_name": "rg-retained"}
    )


def test_driver_cannot_reference_another_subscription(tmp_path):
    state(
        tmp_path,
        resource_type="azurerm_virtual_machine_extension",
        attributes={
            "virtual_machine_id": (
                "/subscriptions/unrelated/resourceGroups/rg-retained/providers/"
                "Microsoft.Compute/virtualMachines/llm-demo123-vm"
            ),
            "tags": {"environmentId": "demo123"},
        },
    )
    with pytest.raises(entrypoint.TerraformRunError, match="driver subscription"):
        entrypoint._validate_group_ownership(
            tmp_path,
            "demo123",
            {
                "existing_resource_group_name": "rg-retained",
                "subscription_id": "owned",
            },
        )


@pytest.mark.parametrize("resource_type", ["azapi_resource", "tls_private_key"])
def test_unexpected_managed_state_cannot_be_destroyed(tmp_path, resource_type):
    state(tmp_path, resource_type=resource_type)
    with pytest.raises(entrypoint.TerraformRunError, match="Unexpected managed"):
        entrypoint._validate_group_ownership(tmp_path, "demo123", {})


@pytest.mark.parametrize("mode", ["unknown", {}])
def test_invalid_state_mode_is_explicit(tmp_path, mode):
    state(tmp_path, mode=mode)
    with pytest.raises(entrypoint.TerraformRunError, match="ownership mode"):
        entrypoint._validate_group_ownership(tmp_path, "demo123", {})
