import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "bootstrap_plan", Path(__file__).resolve().parents[1] / "validate_bootstrap_plan.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SUBSCRIPTION = "44444444-4444-4444-4444-444444444444"
TENANT = "33333333-3333-3333-3333-333333333333"
GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-retained-shared"
ACCOUNT = f"{GROUP}/providers/Microsoft.Storage/storageAccounts/llmstate08ab7e"
PROVIDER = "registry.terraform.io/azure/azapi"


def target():
    return {
        "subscription_id": SUBSCRIPTION,
        "tenant_id": TENANT,
        "existing_resource_group_name": "rg-retained-shared",
        "location": "polandcentral",
        "name_prefix": "llm",
        "stage": "dev",
        "tags": {"managedBy": "synthetic-operator", "project": "test"},
    }


def plan():
    """Synthetic full show-json fixture matching native 1.16.6/AzAPI 2.4 shapes.

    Resource body/unknown subtrees also match native Terraform 1.9.8 mocked
    plans. No real saved plan, state, account metadata or credentials are stored.
    """
    records = [
        {
            "address": "data.azapi_client_config.current",
            "mode": "data",
            "type": "azapi_client_config",
            "name": "current",
            "provider_name": PROVIDER,
            "values": {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT},
        },
        {
            "address": "data.azapi_resource.shared",
            "mode": "data",
            "type": "azapi_resource",
            "name": "shared",
            "provider_name": PROVIDER,
            "values": {
                "id": GROUP,
                "name": "rg-retained-shared",
                "type": "Microsoft.Resources/resourceGroups@2024-03-01",
                "location": "eastus",
            },
        },
    ]
    account_body = {
        "kind": "StorageV2",
        "sku": {"name": "Standard_LRS"},
        "properties": {
            "supportsHttpsTrafficOnly": True,
            "minimumTlsVersion": "TLS1_2",
            "allowSharedKeyAccess": False,
            "allowBlobPublicAccess": False,
            "allowCrossTenantReplication": False,
            "defaultToOAuthAuthentication": True,
            "publicNetworkAccess": "Enabled",
            "networkAcls": {"bypass": "None", "defaultAction": "Allow"},
            "encryption": {
                "keySource": "Microsoft.Storage",
                "services": {"blob": {"enabled": True, "keyType": "Account"}},
            },
        },
    }
    bodies = [
        account_body,
        {
            "properties": {
                "isVersioningEnabled": True,
                "deleteRetentionPolicy": {"enabled": True, "days": 7},
                "containerDeleteRetentionPolicy": {"enabled": True, "days": 7},
            }
        },
        {"properties": {"publicAccess": "None"}},
    ]
    types = [
        "Microsoft.Storage/storageAccounts@2023-05-01",
        "Microsoft.Storage/storageAccounts/blobServices@2023-05-01",
        "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01",
    ]
    changes, configured = [], []
    for index, name in enumerate(("state", "blobs", "tfstate")):
        address = f"azapi_resource.{name}"
        values = {
            "type": types[index],
            "name": ("llmstate08ab7e", "default", "tfstate")[index],
            "body": bodies[index],
            "parent_id": GROUP if index == 0 else None,
            "response_export_values": [],
            "identity": [],
            "sensitive_body": None,
        }
        unknown = {"id": True, "output": True, "body": {"properties": {}}}
        if index == 0:
            values.update(location="polandcentral", tags=target()["tags"])
            unknown.update(tags={})
            unknown["body"]["properties"] = {
                "encryption": {"services": {"blob": {}}},
                "networkAcls": {},
            }
        else:
            unknown.update(parent_id=True)
            if index == 1:
                unknown["body"]["properties"] = {
                    "deleteRetentionPolicy": {},
                    "containerDeleteRetentionPolicy": {},
                }
        item = {
            "address": address,
            "mode": "managed",
            "type": "azapi_resource",
            "name": name,
            "provider_name": PROVIDER,
        }
        records.append({**item, "values": copy.deepcopy(values)})
        changes.append(
            {
                **item,
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": values,
                    "after_unknown": unknown,
                },
            }
        )
        ref = (
            "data.azapi_resource.shared",
            "azapi_resource.state",
            "azapi_resource.blobs",
        )[index]
        configured.append(
            {
                **item,
                "provider_config_key": "azapi",
                "expressions": {
                    "type": {"constant_value": types[index]},
                    "parent_id": {"references": [f"{ref}.id", ref]},
                },
            }
        )
    for item in records[:2]:
        configured.append(
            {
                **{k: v for k, v in item.items() if k != "values"},
                "provider_config_key": "azapi",
                "expressions": {},
            }
        )
    return {
        "format_version": "1.2",
        "terraform_version": "1.16.6",
        "complete": True,
        "applyable": True,
        "errored": False,
        "variables": {k: {"value": v} for k, v in target().items() if k != "tenant_id"},
        "planned_values": {"root_module": {"resources": records}},
        "prior_state": {
            "values": {"root_module": {"resources": copy.deepcopy(records[:2])}}
        },
        "resource_changes": changes,
        "configuration": {
            "provider_config": {
                "azapi": {
                    "name": "azapi",
                    "full_name": PROVIDER,
                    "version_constraint": "2.4.0",
                    "expressions": {
                        "subscription_id": {"references": ["var.subscription_id"]},
                        "skip_provider_registration": {"constant_value": True},
                        "enable_preflight": {"constant_value": False},
                        "disable_default_output": {"constant_value": True},
                    },
                }
            },
            "root_module": {"resources": configured},
        },
    }


class BootstrapPlanTests(unittest.TestCase):
    def reject(self, data, expected=None):
        with self.assertRaises(guard.PlanRejected):
            guard.validate_plan(data, target() if expected is None else expected)

    def test_native_unknown_child_parents_and_empty_unknown_objects(self):
        guard.validate_plan(plan(), target())

    def test_native_argumentless_client_data_omits_expressions(self):
        data = plan()
        current = next(
            item
            for item in data["configuration"]["root_module"]["resources"]
            if item["address"] == "data.azapi_client_config.current"
        )
        del current["expressions"]
        guard.validate_plan(data, target())
        current["expressions"] = None
        self.reject(data)
        current["expressions"] = {"subscription_id": {"constant_value": SUBSCRIPTION}}
        self.reject(data)
        data = plan()
        shared = next(
            item
            for item in data["configuration"]["root_module"]["resources"]
            if item["address"] == "data.azapi_resource.shared"
        )
        del shared["expressions"]
        self.reject(data)

    def test_known_exact_parent_chain_and_absent_prior(self):
        data = plan()
        del data["prior_state"]
        for item, parent in zip(
            data["resource_changes"][1:], (ACCOUNT, f"{ACCOUNT}/blobServices/default")
        ):
            item["change"]["after"]["parent_id"] = parent
            item["change"]["after_unknown"]["parent_id"] = False
            resource = next(
                r
                for r in data["planned_values"]["root_module"]["resources"]
                if r["address"] == item["address"]
            )
            resource["values"]["parent_id"] = parent
        guard.validate_plan(data, target())

    def test_foreign_or_missing_parent_dependency(self):
        for index in range(3):
            for value in (
                None,
                {},
                {"constant_value": "foreign"},
                {"references": ["azapi_resource.foreign.id"]},
                {"references": [{}]},
            ):
                data = plan()
                data["configuration"]["root_module"]["resources"][index]["expressions"][
                    "parent_id"
                ] = value
                self.reject(data)

    def test_foreign_or_ambiguous_parent_value(self):
        for index in range(3):
            for value in ("foreign", "", 1):
                data = plan()
                data["resource_changes"][index]["change"]["after"]["parent_id"] = value
                self.reject(data)
        data = plan()
        data["resource_changes"][0]["change"]["after_unknown"]["parent_id"] = True
        self.reject(data)

    def test_security_and_recovery_values_are_exact_and_typed(self):
        for index, key, value in (
            (0, "allowSharedKeyAccess", True),
            (0, "allowBlobPublicAccess", True),
            (0, "supportsHttpsTrafficOnly", False),
            (0, "minimumTlsVersion", "TLS1_0"),
            (0, "defaultToOAuthAuthentication", False),
            (0, "supportsHttpsTrafficOnly", 1),
            (0, "allowCrossTenantReplication", True),
            (1, "isVersioningEnabled", False),
            (2, "publicAccess", "Blob"),
            (2, "publicAccess", None),
        ):
            data = plan()
            data["resource_changes"][index]["change"]["after"]["body"]["properties"][
                key
            ] = value
            self.reject(data)
        for key in ("deleteRetentionPolicy", "containerDeleteRetentionPolicy"):
            for value in (
                {"enabled": True, "days": 1},
                {"enabled": 1, "days": 7},
                {"enabled": True, "days": "7"},
            ):
                data = plan()
                data["resource_changes"][1]["change"]["after"]["body"]["properties"][
                    key
                ] = value
                self.reject(data)
        for field in ("sku", "kind"):
            data = plan()
            data["resource_changes"][0]["change"]["after"]["body"][field] = "foreign"
            self.reject(data)
        data = plan()
        data["resource_changes"][0]["change"]["after"]["body"]["properties"][
            "encryption"
        ]["keySource"] = "Microsoft.Keyvault"
        self.reject(data)

    def test_unknown_critical_values_and_malformed_unknown_metadata(self):
        for index in range(3):
            for unknown in (
                True,
                {"properties": True},
                {"properties": {"publicAccess": True}},
                None,
                1,
                "true",
            ):
                data = plan()
                data["resource_changes"][index]["change"]["after_unknown"][
                    "body"
                ] = unknown
                self.reject(data)
        for key in ("tags", "location", "type", "name", "response_export_values"):
            data = plan()
            data["resource_changes"][0]["change"]["after_unknown"][key] = True
            self.reject(data)

    def test_target_identity_variables_names_tags_and_region(self):
        for key, value in (
            ("tenant_id", SUBSCRIPTION),
            ("subscription_id", TENANT),
            ("location", "eastus"),
            ("tags", {}),
            ("stage", "release"),
            ("name_prefix", "other"),
            ("existing_resource_group_name", "rg-foreign"),
        ):
            expected = target()
            expected[key] = value
            self.reject(plan(), expected)
        for key in target():
            expected = target()
            del expected[key]
            self.reject(plan(), expected)
        for index in range(3):
            data = plan()
            data["resource_changes"][index]["change"]["after"]["name"] = "foreign"
            self.reject(data)

    def test_exact_resource_allowlist_in_every_surface(self):
        for container in ("changes", "planned", "prior", "configuration"):
            for address in (
                "azurerm_role_assignment.extra",
                "azapi_resource.extra",
                "azapi_resource.group",
            ):
                data = plan()
                if container == "changes":
                    resources = data["resource_changes"]
                elif container == "configuration":
                    resources = data["configuration"]["root_module"]["resources"]
                else:
                    root = (
                        data["planned_values"]
                        if container == "planned"
                        else data["prior_state"]["values"]
                    )
                    resources = root["root_module"]["resources"]
                extra = copy.deepcopy(data["resource_changes"][0])
                extra["address"] = address
                resources.append(extra)
                self.reject(data)

    def test_prior_managed_import_update_delete_noop_and_move_rejected(self):
        data = plan()
        data["prior_state"]["values"]["root_module"]["resources"].append(
            data["planned_values"]["root_module"]["resources"][2]
        )
        self.reject(data)
        for actions in (
            ["update"],
            ["delete"],
            ["delete", "create"],
            ["no-op"],
            ["read"],
            ["forget"],
        ):
            data = plan()
            data["resource_changes"][0]["change"]["actions"] = actions
            self.reject(data)
        for field in ("previous_address", "deposed", "generated_config"):
            data = plan()
            data["resource_changes"][0][field] = None
            self.reject(data)
        data = plan()
        data["resource_changes"][0]["change"]["importing"] = {"id": "existing"}
        self.reject(data)
        data = plan()
        data["resource_changes"][0]["change"]["before"] = {}
        self.reject(data)

    def test_different_api_provider_or_hidden_payload_rejected(self):
        for field, value in (
            ("type", "Microsoft.Authorization/roleAssignments@2022-04-01"),
            ("identity", [{"type": "SystemAssigned"}]),
            ("sensitive_body", {}),
            ("create_headers", {"x": "y"}),
            ("response_export_values", ["*"]),
            ("new_provider_attribute", True),
        ):
            data = plan()
            data["resource_changes"][0]["change"]["after"][field] = value
            self.reject(data)
        for section in ("resource_changes",):
            data = plan()
            data[section][0]["provider_name"] = "registry.terraform.io/foreign/provider"
            self.reject(data)
        for value in ("3.0.0", "~> 2.4.0", None, 2):
            data = plan()
            data["configuration"]["provider_config"]["azapi"][
                "version_constraint"
            ] = value
            self.reject(data)
        data = plan()
        data["configuration"]["provider_config"]["azapi"]["expressions"]["endpoint"] = {
            "constant_value": "foreign"
        }
        self.reject(data)

    def test_structural_inconsistency_and_nested_modules_rejected(self):
        data = plan()
        data["planned_values"]["root_module"]["resources"][2]["values"]["body"] = {}
        self.reject(data)
        for key in ("complete", "applyable"):
            data = plan()
            data[key] = False
            self.reject(data)
        for key in ("deferred_changes", "resource_drift", "action_invocations"):
            data = plan()
            data[key] = [{}]
            self.reject(data)
        for root in ("planned_values", "configuration"):
            data = plan()
            data[root]["root_module"]["child_modules"] = [{}]
            self.reject(data)
        for data in (None, {}, {"format_version": "2.0"}):
            self.reject(data)

    def test_duplicate_or_nonfinite_json_rejected(self):
        for text in (
            '{"x":1,"x":2}',
            '{"x":NaN}',
            '{"x":Infinity}',
            "malformed SECRET",
        ):
            with self.assertRaises(guard.PlanRejected) as raised:
                guard._json(text)
            self.assertNotIn("SECRET", str(raised.exception))

    def test_private_copy_exact_apply_and_environment_sanitized(self):
        for apply in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                original = Path(directory) / "original.tfplan"
                original.write_bytes(b"native private plan")
                log = Path(directory) / "private.log"
                calls = []

                def invoke(command, **kwargs):
                    saved = Path(command[-1])
                    calls.append(saved)
                    self.assertNotEqual(saved, original)
                    self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(saved.read_bytes(), b"native private plan")
                    self.assertFalse(
                        any(
                            key.startswith(("TF_CLI_ARGS", "TF_LOG"))
                            for key in kwargs["env"]
                        )
                    )
                    if command[1] == "show":
                        original.write_bytes(b"replaced after show")
                        return subprocess.CompletedProcess(
                            command, 0, json.dumps(plan())
                        )
                    self.assertEqual(
                        command[1:4], ["apply", "-input=false", "-no-color"]
                    )
                    kwargs["stdout"].write("PRIVATE OUTPUT")
                    return subprocess.CompletedProcess(command, 0)

                with patch.dict(
                    os.environ,
                    {"TF_CLI_ARGS_apply": "-target=foreign", "TF_LOG": "TRACE"},
                ), patch.object(guard.subprocess, "run", side_effect=invoke):
                    guard.run_saved_plan(
                        original, target(), log, terraform="terraform", apply=apply
                    )
                self.assertEqual(len(calls), 2 if apply else 1)
                self.assertTrue(all(path == calls[0] for path in calls))
                self.assertFalse(calls[0].exists())
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_rejection_show_and_apply_failure_are_private(self):
        for result in (
            subprocess.CompletedProcess([], 0, '{"private":"SECRET"}'),
            subprocess.CompletedProcess([], 0, "malformed SECRET"),
            subprocess.CompletedProcess([], 1, ""),
        ):
            with tempfile.TemporaryDirectory() as directory:
                original = Path(directory) / "original"
                original.write_bytes(b"native")
                with patch.object(
                    guard.subprocess, "run", return_value=result
                ) as runner:
                    with self.assertRaises(guard.PlanRejected) as raised:
                        guard.run_saved_plan(
                            original,
                            target(),
                            Path(directory) / "log",
                            terraform="terraform",
                            apply=True,
                        )
                self.assertEqual(runner.call_count, 1)
                self.assertNotIn("SECRET", str(raised.exception))

    def test_existing_log_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original"
            original.write_bytes(b"native")
            log = Path(directory) / "log"
            log.write_text("existing")
            with self.assertRaises(FileExistsError):
                guard.run_saved_plan(
                    original, target(), log, terraform="terraform", apply=False
                )
            self.assertEqual(log.read_text(), "existing")


if __name__ == "__main__":
    unittest.main()
